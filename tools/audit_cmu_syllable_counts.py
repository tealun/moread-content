"""Compare overlay syllable counts with CMUdict pronunciation syllable counts.

This is an audit/report tool. It does not mutate dictionary data.
CMUdict is used only for open, reproducible pronunciation syllable counts; the
orthographic boundary in overlay may still need human review.
"""

from __future__ import annotations

import csv
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import cmudict


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dictionary" / "overlay.db"
REPORT_PATH = ROOT / "dictionary" / "cmu_syllable_mismatches.csv"


def cmu_counts() -> dict[str, set[int]]:
    counts: dict[str, set[int]] = defaultdict(set)
    for word, phones in cmudict.entries():
        counts[word.lower()].add(sum(1 for phone in phones if phone[-1:].isdigit()))
    return dict(counts)


def classify(word: str) -> str:
    if len(word) <= 4 and word.isalpha() and word.upper() == word:
        return "acronym"
    if word.endswith("ism"):
        return "suffix_ism"
    if word.endswith(("ian", "ia", "ium", "ious", "eous", "uous")):
        return "vowel_sequence_suffix"
    if word.endswith(("ically", "ally")):
        return "adverb_ically_ally"
    if word.endswith(("able", "ible")):
        return "suffix_able_ible"
    if word.endswith(("tion", "sion", "cian")):
        return "suffix_tion_sion_cian"
    if word.endswith(("ity", "ety")):
        return "suffix_ity_ety"
    return "other"


def main() -> int:
    counts = cmu_counts()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("select word, phonetic, syllables from overlay order by word").fetchall()
    con.close()

    mismatches = []
    category_counts = Counter()
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
        category = classify(word)
        category_counts[category] += 1
        mismatches.append({
            "word": word,
            "syllables": syllables,
            "actual_count": actual,
            "cmu_counts": "/".join(str(n) for n in sorted(expected)),
            "category": category,
            "phonetic": row["phonetic"] or "",
        })

    with REPORT_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            ["word", "syllables", "actual_count", "cmu_counts", "category", "phonetic"],
        )
        writer.writeheader()
        writer.writerows(mismatches)

    print(f"rows={len(rows)}")
    print(f"cmu_covered={covered}")
    print(f"count_match={matched}")
    print(f"count_mismatch={len(mismatches)}")
    print(f"report={REPORT_PATH}")
    print("categories:")
    for category, count in category_counts.most_common():
        print(f"  {category}: {count}")
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
