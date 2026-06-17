"""Normalize and repair phonetics in dictionary/overlay.db.

The overlay was originally seeded from ECDICT, whose phonetic field mixes
old DJ-style ASCII notation with partial IPA.  This script fixes that layer
without touching meanings or other overlay fields:

1. Words with a single CMUdict pronunciation are replaced with IPA converted
   from CMU ARPABET.
2. Other entries are normalized from ECDICT-style notation into slash-wrapped
   IPA-like notation.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

import cmudict


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dictionary" / "overlay.db"


VOWELS = {
    "AA": "ɑ",
    "AE": "æ",
    "AH": "ʌ",
    "AO": "ɔ",
    "AW": "aʊ",
    "AY": "aɪ",
    "EH": "ɛ",
    "ER": "ɝ",
    "EY": "eɪ",
    "IH": "ɪ",
    "IY": "iː",
    "OW": "oʊ",
    "OY": "ɔɪ",
    "UH": "ʊ",
    "UW": "uː",
}

CONSONANTS = {
    "B": "b",
    "CH": "tʃ",
    "D": "d",
    "DH": "ð",
    "F": "f",
    "G": "ɡ",
    "HH": "h",
    "JH": "dʒ",
    "K": "k",
    "L": "l",
    "M": "m",
    "N": "n",
    "NG": "ŋ",
    "P": "p",
    "R": "ɹ",
    "S": "s",
    "SH": "ʃ",
    "T": "t",
    "TH": "θ",
    "V": "v",
    "W": "w",
    "Y": "j",
    "Z": "z",
    "ZH": "ʒ",
}

IPA_VOWELS = "aeiouæɑɒɔəɜɪiʊuɛɐɚɝeøœɶɘɵɞɤɯyɨʌ"
BAD_CHARS_RE = re.compile(r"[0-9!%=*^]")
ALT_MARKER_RE = re.compile(r"\(\?@\)")
POLLUTED_RE = re.compile(r"-|\u200d|ɜɜː|əj|[ˈˌ]{2,}")
VALID_ONSETS = {
    ("B", "L"), ("B", "R"), ("B", "Y"),
    ("CH", "R"),
    ("D", "R"), ("D", "W"), ("D", "Y"),
    ("F", "L"), ("F", "R"), ("F", "Y"),
    ("G", "L"), ("G", "R"), ("G", "W"), ("G", "Y"),
    ("K", "L"), ("K", "R"), ("K", "W"), ("K", "Y"),
    ("P", "L"), ("P", "R"), ("P", "Y"),
    ("S", "F"), ("S", "K"), ("S", "L"), ("S", "M"), ("S", "N"), ("S", "P"), ("S", "T"), ("S", "W"),
    ("SH", "R"),
    ("T", "R"), ("T", "W"), ("T", "Y"),
    ("TH", "R"), ("TH", "W"),
    ("V", "R"), ("V", "Y"),
    ("Z", "W"),
    ("S", "K", "L"), ("S", "K", "R"), ("S", "K", "W"),
    ("S", "P", "L"), ("S", "P", "R"), ("S", "P", "Y"),
    ("S", "T", "R"), ("S", "T", "Y"),
}

MANUAL_FIXES = {
    "anthropocentrism": "/ˌænθrəpəʊˈsentrɪzəm/",
    "assonate": "/ˈæsəneɪt/",
    "barcarole": "/ˈbɑːkəˌrəʊl/",
    "electroencephalogram": "/ɪˌlektrəʊenˈsefələɡræm/",
    "enhanced": "/ɪnˈhænst/",
    "eusocial": "/juːˈsəʊʃəl/",
    "forecasts": "/ˈfɔːrkɑːsts/",
    "gasolene": "/ˈɡæsəliːn/",
    "kilogramme": "/ˈkɪləɡræm/",
    "landownership": "/ˈlændˌəʊnəʃɪp/",
    "mobilise": "/ˈməʊbɪlaɪz/",
    "overexploitation": "/ˌəʊvərˌeksplɔɪˈteɪʃən/",
    "proprietorial": "/prəˌpraɪəˈtɔːrɪəl/",
    "sunburnt": "/ˈsʌnbɜːnt/",
    "thaumaturgist": "/ˈθɔːmətɜːdʒɪst/",
    "unenviably": "/ʌnˈenviəblɪ/",
}


def build_cmu() -> dict[str, list[list[str]]]:
    entries: dict[str, list[list[str]]] = defaultdict(list)
    for word, phones in cmudict.entries():
        entries[word.lower()].append(phones)
    return dict(entries)


def arpabet_to_ipa(phones: list[str]) -> str:
    parts: list[str] = []
    vowel_flags: list[bool] = []
    bases: list[str] = []
    for phone in phones:
        match = re.fullmatch(r"([A-Z]+)([012])?", phone)
        if not match:
            continue
        base, stress = match.groups()
        if base in VOWELS:
            ipa = VOWELS[base]
            if base == "AH" and stress == "0":
                ipa = "ə"
            elif base == "ER" and stress == "0":
                ipa = "ɚ"
            elif base == "IY" and stress == "0":
                ipa = "i"
            elif base == "UW" and stress == "0":
                ipa = "u"
            if stress == "1":
                mark = "ˈ"
            elif stress == "2":
                mark = "ˌ"
            else:
                mark = ""
            if mark:
                cluster_start = len(parts)
                while cluster_start > 0 and not vowel_flags[cluster_start - 1]:
                    cluster_start -= 1
                cluster = bases[cluster_start:]
                onset_len = 0
                for size in range(len(cluster), 0, -1):
                    suffix = tuple(cluster[-size:])
                    if size == 1 or suffix in VALID_ONSETS:
                        onset_len = size
                        break
                insert_at = len(parts) - onset_len
                parts.insert(insert_at, mark)
                vowel_flags.insert(insert_at, False)
                bases.insert(insert_at, "")
            parts.append(ipa)
            vowel_flags.append(True)
            bases.append(base)
        else:
            parts.append(CONSONANTS.get(base, ""))
            vowel_flags.append(False)
            bases.append(base)
    return "/" + "".join(parts) + "/"


def normalize_initial_stress(phonetic: str) -> str:
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

    stress_idx = body.find("ˈ")
    if stress_idx <= 0:
        return text

    before_stress = body[:stress_idx]
    if len(before_stress) <= 4 and not any(ch in IPA_VOWELS for ch in before_stress):
        body = "ˈ" + before_stress + body[stress_idx + 1 :]
        return f"{prefix}{body}{suffix}"
    return text


def normalize_legacy_phonetic(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""

    if text[0] in "/[" and text[-1:] in "/]":
        body = text[1:-1].strip()
    else:
        body = text

    body = body.replace("ә", "ə")
    body = body.replace("^", "ɡ")
    body = body.replace("є", "e")
    body = body.replace("ˊ", "ˈ")
    body = body.replace("\\", "ɜ")
    body = body.replace("\u200d", "")
    body = ALT_MARKER_RE.sub("", body)
    body = body.replace(":", "ː")
    body = body.replace("'", "ˈ")
    body = body.replace(",", "ˌ")
    body = re.sub(r"(?<!\d)\.(?=[A-Za-zæɑɒɔəɜɪʊʌθðʃʒŋ])", "ˌ", body)
    body = body.replace(".", "")

    replacements = [
        ("iː", "iː"),
        ("uː", "uː"),
        ("ɔː", "ɔː"),
        ("ɑː", "ɑː"),
        ("ɜː", "ɜː"),
        ("əː", "ɜː"),
        ("eɪ", "eɪ"),
        ("ei", "eɪ"),
        ("ai", "aɪ"),
        ("au", "aʊ"),
        ("ɔi", "ɔɪ"),
        ("oi", "ɔɪ"),
        ("əu", "əʊ"),
        ("ou", "əʊ"),
        ("iə", "ɪə"),
        ("uə", "ʊə"),
        ("eə", "eə"),
    ]
    for old, new in replacements:
        body = body.replace(old, new)

    body = body.replace("i", "ɪ")
    body = body.replace("ɪː", "iː")
    body = body.replace("ʊː", "uː")
    body = body.replace("ɜɜː", "ɜː")
    body = re.sub(r"(?<=\S)-(?=\S)", "", body)
    while "-" in body:
        idx = body.index("-")
        sep = max(body.rfind(";", 0, idx), body.rfind(" ", 0, idx), body.rfind("ˌ", 0, idx))
        if sep >= 0:
            body = body[:sep]
        else:
            body = body.replace("-", "")
    body = re.sub(r"\s+", " ", body)
    body = body.replace("; ;", ";")
    body = body.replace("; /", "; ")
    body = body.strip(" ;")
    body = normalize_initial_stress(f"/{body}/")[1:-1]
    return f"/{body}/"


def choose_repair(word: str, phonetic: str, cmu: dict[str, list[list[str]]]) -> tuple[str, str]:
    manual = MANUAL_FIXES.get(word.lower())
    if manual:
        return manual, "manual"

    pronunciations = cmu.get(word.lower())
    if pronunciations and len(pronunciations) == 1:
        return arpabet_to_ipa(pronunciations[0]), "cmu_single"
    if pronunciations and (
        BAD_CHARS_RE.search(phonetic or "")
        or ALT_MARKER_RE.search(phonetic or "")
        or POLLUTED_RE.search(phonetic or "")
    ):
        return arpabet_to_ipa(pronunciations[0]), "cmu_polluted"
    return normalize_legacy_phonetic(phonetic), "legacy_normalized"


def audit_rows(rows: list[sqlite3.Row]) -> dict[str, int]:
    counts = {
        "not_wrapped": 0,
        "cyrillic_schwa": 0,
        "ascii_stress": 0,
        "ascii_length": 0,
        "bad_chars": 0,
    }
    for row in rows:
        ph = row["phonetic"] or ""
        if not (ph.startswith("/") and ph.endswith("/")):
            counts["not_wrapped"] += 1
        if "ә" in ph:
            counts["cyrillic_schwa"] += 1
        if "'" in ph or "," in ph:
            counts["ascii_stress"] += 1
        if ":" in ph:
            counts["ascii_length"] += 1
        if BAD_CHARS_RE.search(ph):
            counts["bad_chars"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cmu = build_cmu()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = list(con.execute("select word, phonetic from overlay order by word"))

    before = audit_rows(rows)
    updates: list[tuple[str, str, str]] = []
    sources = defaultdict(int)
    for row in rows:
        fixed, source = choose_repair(row["word"], row["phonetic"], cmu)
        sources[source] += 1
        if fixed != row["phonetic"]:
            updates.append((fixed, source, row["word"]))

    print("rows:", len(rows))
    print("before:", dict(before))
    print("planned_updates:", len(updates))
    print("sources:", dict(sources))
    print("samples:", updates[:20])

    if not args.dry_run:
        con.executemany(
            "update overlay set phonetic = ? where word = ?",
            [(fixed, word) for fixed, _source, word in updates],
        )
        con.commit()
        after_rows = list(con.execute("select word, phonetic from overlay order by word"))
        print("after:", dict(audit_rows(after_rows)))

    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
