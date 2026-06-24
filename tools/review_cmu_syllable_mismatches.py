"""AI-assisted review of CMU syllable-count mismatches.

The review is rule-backed and auditable. It applies only high-confidence fixes
that are explainable from the spelling plus CMU syllable count. Other rows are
kept in a review CSV with a decision and reason.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dictionary" / "overlay.db"
MISMATCH_PATH = ROOT / "dictionary" / "cmu_syllable_mismatches.csv"
REVIEW_PATH = ROOT / "dictionary" / "cmu_syllable_ai_review.csv"

VOWELS = set("aeiouy")
BAD_DIGRAPH_SPLIT_RE = re.compile(r"(c-h|p-h|s-h|t-h)")


def count(syllables: str) -> int:
    return syllables.count("-") + 1 if syllables else 0


def parts(syllables: str) -> list[str]:
    return [p for p in syllables.split("-") if p]


def join(parts_: list[str]) -> str:
    return "-".join(p for p in parts_ if p)


def split_initialism(word: str, phonetic: str, target: int) -> str | None:
    if not (2 <= len(word) <= 5):
        return None
    if target != len(word):
        return None
    if not re.search(r"[ˈˌ].*[ˈˌ]|[ˈˌ].*[iɪeɛɑɔəuʊ]", phonetic):
        return None
    return "-".join(word)


def split_suffix_vowels(parts_: list[str], target: int) -> str | None:
    candidates: list[list[str]] = []
    for idx, part in enumerate(parts_):
        lower = part.lower()
        transforms: list[list[str]] = []
        if len(part) > 2 and lower.endswith("ia"):
            transforms.append([part[:-2], part[-2], part[-1]])
        if len(part) > 3 and lower.endswith("ian"):
            transforms.append([part[:-3], part[-3], part[-2:]])
        if len(part) > 3 and lower.endswith("ium"):
            transforms.append([part[:-3], part[-3], part[-2:]])
        if len(part) > 2 and lower.endswith("io"):
            transforms.append([part[:-2], part[-2], part[-1]])
        if len(part) > 4 and lower.endswith("uity"):
            transforms.append([part[:-4], part[-4], part[-3], part[-2:]])
        if len(part) > 4 and lower.endswith("iety"):
            transforms.append([part[:-4], part[-4], part[-3], part[-2:]])
        if len(part) > 4 and lower.endswith("eous"):
            transforms.append([part[:-4], part[-4], part[-3:]])
        if len(part) > 4 and lower.endswith("ious"):
            transforms.append([part[:-4], part[-4], part[-3:]])
        if len(part) > 5 and lower.endswith("iable"):
            transforms.append([part[:-5], part[-5], part[-4], part[-3:]])
        if len(part) > 3 and lower.endswith("ism"):
            transforms.append([part[:-3], part[-3], part[-2:]])

        for replacement in transforms:
            candidate = parts_[:idx] + [p for p in replacement if p] + parts_[idx + 1:]
            candidates.append(candidate)

    for candidate in candidates:
        value = join(candidate)
        if count(value) == target and not BAD_DIGRAPH_SPLIT_RE.search(value):
            return value
    return None


def split_embedded_vowel_sequences(parts_: list[str], target: int) -> str | None:
    candidates: list[list[str]] = []
    for idx, part in enumerate(parts_):
        lower = part.lower()
        for seq in ("io", "ia", "ie", "ea", "ua", "ui", "eo"):
            pos = lower.find(seq)
            if pos <= 0:
                continue
            replacement = [part[:pos + 1], part[pos + 1:]]
            candidate = parts_[:idx] + replacement + parts_[idx + 1:]
            candidates.append(candidate)

    for candidate in candidates:
        value = join(candidate)
        if count(value) == target and not BAD_DIGRAPH_SPLIT_RE.search(value):
            return value
    return None


def choose_fix(row: dict[str, str]) -> tuple[str, str, str]:
    word = row["word"]
    syllables = row["syllables"]
    phonetic = row["phonetic"]
    targets = [int(x) for x in row["cmu_counts"].split("/") if x.isdigit()]
    target = min(targets)
    actual = int(row["actual_count"])
    p = parts(syllables)

    if actual == target:
        return "accepted", syllables, "already matches minimum CMU count"

    initialism = split_initialism(word, phonetic, target)
    if initialism:
        return "fixed_high_confidence", initialism, "initialism letter-name syllables"

    if actual < target:
        fixed = split_suffix_vowels(p, target)
        if fixed:
            return "fixed_high_confidence", fixed, "split pronounced vowel sequence/suffix"
        fixed = split_embedded_vowel_sequences(p, target)
        if fixed:
            return "fixed_high_confidence", fixed, "split embedded pronounced vowel sequence"

    if row["category"] in {"adverb_ically_ally"} and actual > target:
        return "accepted_standard_difference", syllables, "orthographic -ical-ly spelling split differs from reduced pronunciation"
    if row["category"] in {"suffix_ism"}:
        return "needs_human_source", syllables, "-ism boundary needs dictionary-specific policy"
    if actual > target:
        return "accepted_standard_difference", syllables, "orthographic spelling split has more parts than CMU pronunciation"
    return "needs_human_source", syllables, "no high-confidence automatic boundary rule"


def load_mismatches() -> list[dict[str, str]]:
    with MISMATCH_PATH.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def apply_updates(updates: list[tuple[str, str]]) -> None:
    if not updates:
        return
    con = sqlite3.connect(DB_PATH)
    try:
        con.executemany("update overlay set syllables = ? where word = ? collate nocase", updates)
        con.commit()
    finally:
        con.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    rows = load_mismatches()
    reviewed = []
    updates = []
    for row in rows:
        decision, reviewed_syllables, reason = choose_fix(row)
        reviewed.append({
            **row,
            "decision": decision,
            "reviewed_syllables": reviewed_syllables,
            "reason": reason,
        })
        if decision == "fixed_high_confidence" and reviewed_syllables != row["syllables"]:
            updates.append((reviewed_syllables, row["word"]))

    if args.apply:
        apply_updates(updates)

    with REVIEW_PATH.open("w", newline="", encoding="utf-8") as f:
        fieldnames = list(reviewed[0].keys()) if reviewed else []
        writer = csv.DictWriter(f, fieldnames)
        writer.writeheader()
        writer.writerows(reviewed)

    counts: dict[str, int] = {}
    for row in reviewed:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    print(f"reviewed={len(reviewed)}")
    print(f"planned_updates={len(updates)}")
    print(f"applied={len(updates) if args.apply else 0}")
    print(f"report={REVIEW_PATH}")
    for key in sorted(counts):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
