"""Audit overlay pronunciation and syllable data against a small golden gate.

This tool is intentionally conservative:
  * It never rewrites phonetics.
  * With --apply-golden-syllables, it only updates exact golden syllable
    mismatches in dictionary/pronunciation_golden.json.
  * It reports broad hygiene counts so a batch repair cannot hide regressions.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

import cmudict


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dictionary" / "overlay.db"
GOLDEN_PATH = ROOT / "dictionary" / "pronunciation_golden.json"
CMU_REPORT_PATH = ROOT / "dictionary" / "cmu_syllable_mismatches.csv"

POLLUTED_PHONETIC_RE = re.compile(r"[0-9!%=*^]|ә|'|,")
INITIAL_CLUSTER_STRESS_RE = re.compile(r"^/[^aeiouæɑɒɔəɜɪiʊuɛɐɚɝeøœɶɘɵɞɤɯyɨʌ/]{1,4}[ˈˌ]")
IPA_VOWELS = "aeiouæɑɒɔəɜɪiʊuɛɐɚɝeøœɶɘɵɞɤɯyɨʌ"


def load_golden() -> list[dict[str, Any]]:
    return json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))["entries"]


def load_cmu_counts() -> dict[str, set[int]]:
    counts: dict[str, set[int]] = defaultdict(set)
    for word, phones in cmudict.entries():
        counts[word.lower()].add(sum(1 for phone in phones if phone[-1:].isdigit()))
    return dict(counts)


def normalize_initial_stress(phonetic: str | None) -> str:
    if not phonetic:
        return ""

    text = phonetic.strip()
    prefix = ""
    suffix = ""
    body = text
    if body and body[0] in "/[":
        prefix = body[0]
        body = body[1:]
    if body and body[-1] in "/]":
        suffix = body[-1]
        body = body[:-1]

    stress_positions = [(idx, mark) for mark in ("ˈ", "ˌ") if (idx := body.find(mark)) > 0]
    if not stress_positions:
        return text

    stress_idx, mark = min(stress_positions)
    before_stress = body[:stress_idx]
    if len(before_stress) <= 4 and not any(ch in IPA_VOWELS for ch in before_stress):
        body = mark + before_stress + body[stress_idx + 1:]
        return f"{prefix}{body}{suffix}"
    return text


def fetch_overlay(words: list[str]) -> dict[str, sqlite3.Row]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" * len(words))
        rows = con.execute(
            f"select word, phonetic, syllables from overlay where word in ({placeholders}) collate nocase",
            tuple(words),
        ).fetchall()
        return {row["word"].lower(): row for row in rows}
    finally:
        con.close()


def hygiene_counts() -> dict[str, int]:
    con = sqlite3.connect(DB_PATH)
    try:
        phonetic_rows = con.execute("select word, phonetic from overlay").fetchall()
        stress_after_initial_cluster = [
            (word, phonetic)
            for word, phonetic in phonetic_rows
            if phonetic and INITIAL_CLUSTER_STRESS_RE.search(phonetic)
        ]
        return {
            "rows": con.execute("select count(*) from overlay").fetchone()[0],
            "polluted_phonetic": con.execute(
                """
                select count(*) from overlay
                where phonetic glob '*[0-9!%=*^]*'
                   or phonetic like '%ә%'
                   or phonetic like '%''%'
                   or phonetic like '%,%'
                """
            ).fetchone()[0],
            "missing_syllables": con.execute(
                "select count(*) from overlay where syllables is null or syllables = ''"
            ).fetchone()[0],
            "stress_after_initial_cluster": len(stress_after_initial_cluster),
            "stress_after_initial_cluster_samples": stress_after_initial_cluster[:10],
        }
    finally:
        con.close()


def audit_golden() -> list[dict[str, Any]]:
    golden = load_golden()
    rows = fetch_overlay([entry["word"] for entry in golden])
    failures: list[dict[str, Any]] = []

    for entry in golden:
        word = entry["word"].lower()
        row = rows.get(word)
        if row is None:
            failures.append({"word": word, "field": "row", "actual": None, "expected": "present"})
            continue

        phonetic = row["phonetic"] or ""
        accepted = set(entry.get("accepted_phonetics", []))
        rejected = set(entry.get("rejected_phonetics", []))
        if phonetic in rejected:
            failures.append({"word": word, "field": "phonetic", "actual": phonetic, "expected": "not rejected"})
        elif accepted and phonetic not in accepted:
            failures.append({"word": word, "field": "phonetic", "actual": phonetic, "expected": sorted(accepted)})
        if INITIAL_CLUSTER_STRESS_RE.search(phonetic):
            failures.append({"word": word, "field": "phonetic_stress", "actual": phonetic, "expected": "stress before initial consonant cluster"})

        expected_syllables = entry.get("syllables", "")
        actual_syllables = row["syllables"] or ""
        if expected_syllables and actual_syllables != expected_syllables:
            failures.append({"word": word, "field": "syllables", "actual": actual_syllables, "expected": expected_syllables})

        expected_count = entry.get("syllable_count")
        if expected_count is not None and actual_syllables:
            actual_count = actual_syllables.count("-") + 1
            if actual_count != expected_count:
                failures.append({"word": word, "field": "syllable_count", "actual": actual_count, "expected": expected_count})

    return failures


def apply_golden_syllables(failures: list[dict[str, Any]]) -> int:
    golden_by_word = {entry["word"].lower(): entry for entry in load_golden()}
    updates: list[tuple[str, str]] = []
    for failure in failures:
        if failure["field"] != "syllables":
            continue
        entry = golden_by_word[failure["word"]]
        updates.append((entry["syllables"], failure["word"]))

    if not updates:
        return 0

    con = sqlite3.connect(DB_PATH)
    try:
        con.executemany("update overlay set syllables = ? where word = ? collate nocase", updates)
        con.commit()
    finally:
        con.close()
    return len(updates)


def apply_initial_stress_fixes() -> int:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("select word, phonetic from overlay").fetchall()
        updates = []
        for row in rows:
            fixed = normalize_initial_stress(row["phonetic"])
            if fixed != row["phonetic"]:
                updates.append((fixed, row["word"]))
        if updates:
            con.executemany("update overlay set phonetic = ? where word = ?", updates)
            con.commit()
        return len(updates)
    finally:
        con.close()


def write_cmu_mismatch_report() -> dict[str, Any]:
    from audit_cmu_syllable_counts import classify

    counts = load_cmu_counts()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("select word, phonetic, syllables from overlay order by word").fetchall()
    finally:
        con.close()

    mismatches = []
    covered = 0
    matched = 0
    for row in rows:
        word = row["word"].lower()
        expected = counts.get(word)
        if not expected:
            continue
        covered += 1
        syllables = row["syllables"] or ""
        actual = syllables.count("-") + 1 if syllables else 0
        if actual in expected:
            matched += 1
            continue
        mismatches.append({
            "word": word,
            "syllables": syllables,
            "actual_count": actual,
            "cmu_counts": "/".join(str(n) for n in sorted(expected)),
            "category": classify(word),
            "phonetic": row["phonetic"] or "",
        })

    with CMU_REPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            ["word", "syllables", "actual_count", "cmu_counts", "category", "phonetic"],
        )
        writer.writeheader()
        writer.writerows(mismatches)

    return {
        "cmu_covered": covered,
        "cmu_count_match": matched,
        "cmu_count_mismatch": len(mismatches),
        "cmu_mismatch_report": str(CMU_REPORT_PATH),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply-golden-syllables", action="store_true")
    parser.add_argument("--apply-initial-stress-fixes", action="store_true")
    args = parser.parse_args()

    failures = audit_golden()
    applied = apply_golden_syllables(failures) if args.apply_golden_syllables else 0
    stress_applied = apply_initial_stress_fixes() if args.apply_initial_stress_fixes else 0
    if applied:
        failures = audit_golden()
    if stress_applied:
        failures = audit_golden()

    report = {
        "hygiene": hygiene_counts(),
        "golden_entry_count": len(load_golden()),
        "golden_failures": failures,
        "cmu_syllable_count_audit": write_cmu_mismatch_report(),
        "applied_golden_syllable_updates": applied,
        "applied_initial_stress_updates": stress_applied,
        "ok": (
            not failures
            and hygiene_counts()["polluted_phonetic"] == 0
            and hygiene_counts()["missing_syllables"] == 0
            and hygiene_counts()["stress_after_initial_cluster"] == 0
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
