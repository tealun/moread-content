"""Cross-check CMU mismatch rows against Kaikki/Wiktionary syllable categories.

Kaikki exposes Wiktionary-derived JSONL per word. Many entries include
categories like "English 4-syllable words"; this script uses those categories
as a second open confirmation source.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MISMATCH_PATH = ROOT / "dictionary" / "cmu_syllable_mismatches.csv"
REPORT_PATH = ROOT / "dictionary" / "kaikki_syllable_audit.csv"
CACHE_DIR = ROOT / "dictionary" / ".kaikki_cache"

COUNT_RE = re.compile(r"English (\d+)-syllable words")


def word_url(word: str) -> str:
    lower = word.lower()
    return f"https://kaikki.org/dictionary/English/meaning/{lower[0]}/{lower[:2]}/{lower}.jsonl"


def fetch_jsonl(word: str, refresh: bool = False) -> list[dict]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = CACHE_DIR / f"{word.lower()}.jsonl"
    if cache_path.exists() and not refresh:
        raw = cache_path.read_text(encoding="utf-8")
    else:
        try:
            with urllib.request.urlopen(word_url(word), timeout=8) as response:
                raw = response.read().decode("utf-8")
            cache_path.write_text(raw, encoding="utf-8")
            time.sleep(0.05)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return []
            raise
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def extract_counts(entries: list[dict]) -> set[int]:
    counts: set[int] = set()
    for entry in entries:
        for sense in entry.get("senses", []):
            for category in sense.get("categories", []):
                match = COUNT_RE.fullmatch(category)
                if match:
                    counts.add(int(match.group(1)))
        for category in entry.get("categories", []):
            match = COUNT_RE.fullmatch(category)
            if match:
                counts.add(int(match.group(1)))
    return counts


def extract_ipa(entries: list[dict]) -> str:
    values = []
    for entry in entries:
        for sound in entry.get("sounds", []):
            ipa = sound.get("ipa")
            if ipa and ipa not in values:
                values.append(ipa)
    return "; ".join(values)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()

    with MISMATCH_PATH.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[:args.limit]

    reviewed = []
    for idx, row in enumerate(rows, 1):
        word = row["word"]
        try:
            entries = fetch_jsonl(word, refresh=args.refresh)
            counts = extract_counts(entries)
            ipa = extract_ipa(entries)
            error = ""
        except Exception as exc:
            entries = []
            counts = set()
            ipa = ""
            error = repr(exc)

        actual = int(row["actual_count"])
        cmu_counts = {int(v) for v in row["cmu_counts"].split("/") if v.isdigit()}
        if not entries:
            decision = "kaikki_missing"
        elif not counts:
            decision = "kaikki_no_count"
        elif actual in counts:
            decision = "kaikki_confirms_current"
        elif counts & cmu_counts:
            decision = "kaikki_confirms_cmu_mismatch"
        else:
            decision = "kaikki_disagrees_with_both"

        reviewed.append({
            **row,
            "kaikki_counts": "/".join(str(n) for n in sorted(counts)),
            "kaikki_ipa": ipa,
            "kaikki_decision": decision,
            "kaikki_error": error,
        })
        if idx % 10 == 0:
            print(f"processed={idx}/{len(rows)}")

    with REPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, reviewed[0].keys() if reviewed else [])
        writer.writeheader()
        writer.writerows(reviewed)

    counts_by_decision: dict[str, int] = {}
    for row in reviewed:
        counts_by_decision[row["kaikki_decision"]] = counts_by_decision.get(row["kaikki_decision"], 0) + 1
    print(f"reviewed={len(reviewed)}")
    print(f"report={REPORT_PATH}")
    for key in sorted(counts_by_decision):
        print(f"{key}: {counts_by_decision[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
