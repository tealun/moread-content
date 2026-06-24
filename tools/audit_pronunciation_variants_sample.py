"""Random-sample audit for pronunciation variant accuracy.

The audit does not modify dictionary/overlay.db. It samples at least 10% of
active overlay entries, recollects external UK/US pronunciation evidence, and
writes a CSV report with reproducible decisions.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from fill_pronunciation_variants import (
    build_cmu,
    choose,
    collect_cmu_candidate,
    collect_kaikki_candidates,
    ensure_columns,
    normalize_ipa,
)


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dictionary" / "overlay.db"
REPORT_PATH = ROOT / "dictionary" / "pronunciation_variant_sample_audit.csv"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def parse_sources(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def flatten_candidates(sources: dict) -> set[str]:
    values: set[str] = set()
    for dialect_items in sources.get("candidates", {}).values():
        if not isinstance(dialect_items, list):
            continue
        for item in dialect_items:
            if isinstance(item, dict):
                ipa = normalize_ipa(item.get("ipa", ""))
                if ipa:
                    values.add(ipa)
    return values


def audit_one(row: dict, cmu: dict[str, list[list[str]]]) -> dict:
    word = row["word"]
    candidates: dict[str, list[dict]] = {"uk": [], "us": []}
    collect_kaikki_candidates(word, candidates)
    collect_cmu_candidate(word, candidates, cmu)
    expected_uk, expected_us, expected_status, expected_sources = choose(candidates, row["phonetic"] or "")

    current_phonetic = normalize_ipa(row["phonetic"] or "")
    current_uk = normalize_ipa(row.get("phonetic_uk", "") or "")
    current_us = normalize_ipa(row.get("phonetic_us", "") or "")
    current_status = row.get("phonetic_variant_status", "") or "legacy_single"

    external_values = flatten_candidates(expected_sources)
    variant_mismatches: list[str] = []
    if expected_uk and current_uk and current_uk != expected_uk:
        variant_mismatches.append("uk")
    if expected_us and current_us and current_us != expected_us:
        variant_mismatches.append("us")

    if not current_phonetic:
        verdict = "fail_missing_phonetic"
    elif variant_mismatches:
        verdict = "fail_variant_mismatch"
    elif not external_values:
        verdict = "review_no_external_evidence"
    elif expected_status == "conflict":
        verdict = "review_external_conflict"
    elif external_values and current_phonetic not in external_values and not (current_phonetic in {expected_uk, expected_us}):
        verdict = "review_legacy_not_in_external"
    elif expected_status in {"verified", "same"} and (not current_uk or not current_us):
        verdict = "gap_missing_verified_variant_fields"
    elif expected_status == "us_only" and not current_us:
        verdict = "gap_missing_us_field"
    elif expected_status == "uk_only" and not current_uk:
        verdict = "gap_missing_uk_field"
    else:
        verdict = "pass"

    return {
        "word": word,
        "frequency": row.get("frequency", 0),
        "current_phonetic": current_phonetic,
        "current_uk": current_uk,
        "current_us": current_us,
        "current_status": current_status,
        "expected_uk": expected_uk,
        "expected_us": expected_us,
        "expected_status": expected_status,
        "verdict": verdict,
        "source_variants": "|".join(expected_sources.get("source_variants", [])),
        "conflict_dialects": "|".join(expected_sources.get("conflict_dialects", [])),
        "candidate_count_uk": len(expected_sources.get("candidates", {}).get("uk", [])),
        "candidate_count_us": len(expected_sources.get("candidates", {}).get("us", [])),
        "sources_json": json.dumps(expected_sources, ensure_ascii=False),
    }


def load_rows(seed: int, sample_rate: float, sample_size: int | None) -> tuple[int, list[dict]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)
    rows = [
        dict(row)
        for row in conn.execute(
            """
            select word, frequency, phonetic, phonetic_uk, phonetic_us,
                   phonetic_variant_status, phonetic_sources
              from overlay
             where audit_pass = 2
             order by word
            """
        )
    ]
    conn.close()

    rng = random.Random(seed)
    target = sample_size if sample_size is not None else math.ceil(len(rows) * sample_rate)
    target = min(len(rows), max(1, target))
    return len(rows), rng.sample(rows, target)


def write_report(results: list[dict]) -> None:
    fieldnames = [
        "word",
        "frequency",
        "current_phonetic",
        "current_uk",
        "current_us",
        "current_status",
        "expected_uk",
        "expected_us",
        "expected_status",
        "verdict",
        "source_variants",
        "conflict_dialects",
        "candidate_count_uk",
        "candidate_count_us",
        "sources_json",
    ]
    with REPORT_PATH.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def summarize(results: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        verdict = result["verdict"]
        counts[verdict] = counts.get(verdict, 0) + 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-rate", type=float, default=0.10)
    parser.add_argument("--sample-size", type=int)
    parser.add_argument("--seed", type=int, default=20260624)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--progress-every", type=int, default=50)
    args = parser.parse_args()

    if args.sample_rate < 0.10 and args.sample_size is None:
        raise SystemExit("--sample-rate must be at least 0.10 unless --sample-size is explicit")

    total, sample = load_rows(args.seed, args.sample_rate, args.sample_size)
    print(f"total_rows={total} sample_rows={len(sample)} sample_rate={len(sample) / total:.4f} seed={args.seed}")

    cmu = build_cmu()
    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(audit_one, row, cmu): row["word"] for row in sample}
        for index, future in enumerate(as_completed(future_map), start=1):
            word = future_map[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({
                    "word": word,
                    "frequency": "",
                    "current_phonetic": "",
                    "current_uk": "",
                    "current_us": "",
                    "current_status": "",
                    "expected_uk": "",
                    "expected_us": "",
                    "expected_status": "",
                    "verdict": "audit_error",
                    "source_variants": "",
                    "conflict_dialects": "",
                    "candidate_count_uk": 0,
                    "candidate_count_us": 0,
                    "sources_json": json.dumps({"error": str(exc)}, ensure_ascii=False),
                })
            if args.progress_every and index % args.progress_every == 0:
                print(f"progress={index}/{len(sample)}")

    results.sort(key=lambda item: item["word"])
    write_report(results)
    summary = summarize(results)
    print("summary:", json.dumps(summary, ensure_ascii=False, sort_keys=True))
    print(f"report={REPORT_PATH}")
    return 1 if any(k.startswith("fail_") or k == "audit_error" for k in summary) else 0


if __name__ == "__main__":
    raise SystemExit(main())
