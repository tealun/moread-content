"""Fill UK/US pronunciation fields in dictionary/overlay.db.

This script is intentionally conservative:
  * It keeps the legacy phonetic field untouched.
  * phonetic_us is filled only from CMUdict.
  * phonetic_uk is filled only from Kaikki/Wiktionary entries explicitly
    tagged as UK, British, RP, or Received Pronunciation.
  * Free Dictionary is not used for main writes; keep it for audit-only work.
  * Conflicting candidates are preserved in phonetic_sources for review.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import quote

import cmudict
import requests

from fix_overlay_phonetics import arpabet_to_ipa


ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "dictionary" / "overlay.db"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

IPA_HINT_RE = re.compile(r"[ˈˌəɪɛæɑɒɔʊʌθðʃʒŋɹɚɝ]")
IPA_VOWELS = "aeiouæɑɒɔəɜɪiʊuɛɐɚɝeøœɶɘɵɞɤɯyɨʌ"

UK_HINTS = ("british", "england", "received pronunciation", "rp", "non rhotic")
US_HINTS = ("american", "genam", "general american", "america")
NON_UK_REGIONS = ("australian", "new zealand", "canadian", "irish", "scottish", "welsh")


def normalize_ipa(text: str | None) -> str:
    if not text:
        return ""
    value = text.strip()
    if not value:
        return ""
    if value.startswith("[") and value.endswith("]"):
        value = "/" + value[1:-1].strip() + "/"
    elif not (value.startswith("/") and value.endswith("/")):
        value = f"/{value.strip('/')}/"

    body = value[1:-1].strip()
    body = body.replace("ә", "ə").replace("'", "ˈ").replace(",", "ˌ")
    body = body.replace(".", "")
    body = re.sub(r"\s+", "", body)
    value = f"/{body}/"
    return normalize_initial_stress(value)


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

    stress_positions = [(idx, mark) for mark in ("ˈ", "ˌ") if (idx := body.find(mark)) > 0]
    if not stress_positions:
        return text

    stress_idx, mark = min(stress_positions)
    before_stress = body[:stress_idx]
    if len(before_stress) <= 4 and not any(ch in IPA_VOWELS for ch in before_stress):
        body = mark + before_stress + body[stress_idx + 1:]
        return f"{prefix}{body}{suffix}"
    return text


def ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(overlay)")}
    additions = {
        "phonetic_uk": "TEXT NOT NULL DEFAULT ''",
        "phonetic_us": "TEXT NOT NULL DEFAULT ''",
        "phonetic_variant_status": "TEXT NOT NULL DEFAULT 'legacy_single'",
        "phonetic_sources": "TEXT NOT NULL DEFAULT '{}'",
    }
    for name, ddl in additions.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE overlay ADD COLUMN {name} {ddl}")
    conn.commit()


def labels_from_sound(sound: dict) -> str:
    bits: list[str] = []
    for key in ("tags", "raw_tags", "topics"):
        value = sound.get(key)
        if isinstance(value, list):
            bits.extend(str(v) for v in value)
    for key in ("audio", "ogg_url", "mp3_url", "text"):
        value = sound.get(key)
        if value:
            bits.append(str(value))
    return " ".join(bits).lower()


def classify_dialects(label_text: str) -> list[str]:
    label = re.sub(r"[-_]+", " ", label_text.lower())
    tokens = set(re.findall(r"[a-z]+", label))
    has_uk = any(hint in label for hint in UK_HINTS)
    has_uk = has_uk or "uk" in tokens
    if has_uk and any(region in label for region in NON_UK_REGIONS) and "uk" not in tokens and "british" not in label:
        has_uk = False
    has_us = any(hint in label for hint in US_HINTS)
    has_us = has_us or "us" in tokens

    dialects = []
    if has_uk:
        dialects.append("uk")
    if has_us:
        dialects.append("us")
    return dialects


def add_candidate(candidates: dict[str, list[dict]], dialects: list[str], ipa: str, source: str, detail: str) -> None:
    normalized = normalize_ipa(ipa)
    if not dialects or not normalized or not IPA_HINT_RE.search(normalized):
        return
    if any(char in normalized for char in "-()"):
        return
    for dialect in dialects:
        candidates[dialect].append({"ipa": normalized, "source": source, "detail": detail[:160]})


def fetch_kaikki(word: str) -> list[dict]:
    first = quote(word[:1])
    first2 = quote(word[:2])
    encoded = quote(word)
    url = f"https://kaikki.org/dictionary/English/meaning/{first}/{first2}/{encoded}.jsonl"
    try:
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return []
        entries = []
        for line in resp.text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return entries
    except requests.RequestException:
        return []


def collect_kaikki_candidates(word: str, candidates: dict[str, list[dict]]) -> None:
    for entry in fetch_kaikki(word):
        if entry.get("word", "").lower() != word.lower():
            continue
        for sound in entry.get("sounds", []) or []:
            ipa = sound.get("ipa") or ""
            label = labels_from_sound(sound)
            dialects = [dialect for dialect in classify_dialects(label) if dialect == "uk"]
            add_candidate(candidates, dialects, ipa, "kaikki", label)


def fetch_free_dictionary(word: str) -> dict | None:
    try:
        resp = requests.get(f"https://api.dictionaryapi.dev/api/v2/entries/en/{quote(word)}", timeout=8)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0]
    except (requests.RequestException, ValueError):
        return None
    return None


def collect_free_dictionary_candidates(word: str, candidates: dict[str, list[dict]]) -> None:
    data = fetch_free_dictionary(word)
    if not data:
        return
    for sound in data.get("phonetics", []) or []:
        ipa = sound.get("text") or ""
        classifier_detail = " ".join(str(sound.get(k, "")) for k in ("audio", "sourceUrl"))
        evidence_detail = " ".join(str(sound.get(k, "")) for k in ("audio", "sourceUrl"))
        add_candidate(candidates, classify_dialects(classifier_detail), ipa, "free_dictionary", evidence_detail)


def build_cmu() -> dict[str, list[list[str]]]:
    entries: dict[str, list[list[str]]] = defaultdict(list)
    for word, phones in cmudict.entries():
        entries[word.lower()].append(phones)
    return dict(entries)


def collect_cmu_candidate(word: str, candidates: dict[str, list[dict]], cmu: dict[str, list[list[str]]]) -> None:
    pronunciations = cmu.get(word.lower()) or []
    if not pronunciations:
        return
    seen: set[str] = set()
    for index, phones in enumerate(pronunciations, start=1):
        ipa = arpabet_to_ipa(phones)
        if ipa in seen:
            continue
        seen.add(ipa)
        add_candidate(candidates, ["us"], ipa, "cmudict", f"CMU pronunciation {index}/{len(pronunciations)}")


def choose(candidates: dict[str, list[dict]], legacy_phonetic: str) -> tuple[str, str, str, dict]:
    sources = {
        "candidates": {
            dialect: values
            for dialect, values in candidates.items()
            if values
        }
    }

    chosen: dict[str, str] = {}
    conflicts: list[str] = []
    source_variants: list[str] = []
    for dialect in ("uk", "us"):
        seen: list[str] = []
        for item in candidates.get(dialect, []):
            if item["ipa"] not in seen:
                seen.append(item["ipa"])
        if seen:
            votes = Counter(item["ipa"] for item in candidates.get(dialect, []))
            top_count = max(votes.values())
            top = [ipa for ipa, count in votes.items() if count == top_count]
            if len(seen) > 1:
                source_variants.append(dialect)
            if len(top) > 1:
                conflicts.append(dialect)
            else:
                chosen[dialect] = top[0]

    uk = chosen.get("uk", "")
    us = chosen.get("us", "")
    if conflicts:
        status = "conflict"
    elif uk and us and uk == us:
        status = "same"
    elif uk and us:
        status = "verified"
    elif uk:
        status = "uk_only"
    elif us:
        status = "us_only"
    elif legacy_phonetic:
        status = "legacy_single"
    else:
        status = "missing"

    sources["status_reason"] = status
    if source_variants:
        sources["source_variants"] = source_variants
    if conflicts:
        sources["conflict_dialects"] = conflicts
    return uk, us, status, sources


def process_row(row: sqlite3.Row | dict, cmu: dict[str, list[list[str]]]) -> tuple[str, str, str, str, str]:
    word = row["word"]
    candidates: dict[str, list[dict]] = defaultdict(list)
    collect_kaikki_candidates(word, candidates)
    collect_cmu_candidate(word, candidates, cmu)
    uk, us, status, sources = choose(candidates, row["phonetic"] or "")
    sources["source_policy"] = {
        "uk": "kaikki_wiktionary_explicit_uk_british_rp_only",
        "us": "cmudict_only",
        "main_write_excludes": ["free_dictionary"],
    }
    return uk, us, status, json.dumps(sources, ensure_ascii=False), word


def write_updates(conn: sqlite3.Connection, updates: list[tuple[str, str, str, str, str]]) -> None:
    if not updates:
        return
    conn.executemany(
        """
        update overlay
           set phonetic_uk = ?,
               phonetic_us = ?,
               phonetic_variant_status = ?,
               phonetic_sources = ?
         where word = ? collate nocase
        """,
        updates,
    )
    conn.commit()


def fill(
    words: list[str] | None,
    limit: int | None,
    dry_run: bool,
    delay: float,
    workers: int,
    commit_every: int,
) -> dict[str, int]:
    cmu = build_cmu()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_columns(conn)

    if words:
        placeholders = ",".join("?" for _ in words)
        rows = conn.execute(
            f"select word, phonetic from overlay where word in ({placeholders}) collate nocase order by word",
            tuple(w.lower() for w in words),
        ).fetchall()
    else:
        sql = "select word, phonetic from overlay where audit_pass = 2 order by frequency desc, word"
        if limit:
            sql += f" limit {int(limit)}"
        rows = conn.execute(sql).fetchall()

    counts: dict[str, int] = defaultdict(int)
    updates: list[tuple[str, str, str, str, str]] = []
    committed = 0
    row_dicts = [dict(row) for row in rows]
    if workers <= 1:
        for index, row in enumerate(row_dicts, start=1):
            uk, us, status, sources_json, word = process_row(row, cmu)
            counts[status] += 1
            updates.append((uk, us, status, sources_json, word))
            if not dry_run and len(updates) >= commit_every:
                write_updates(conn, updates)
                committed += len(updates)
                updates.clear()
                print(f"committed={committed}/{len(rows)}")
            print(f"{index}/{len(rows)} {word}: uk={uk or '-'} us={us or '-'} status={status}")
            if delay:
                time.sleep(delay)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(process_row, row, cmu): row["word"] for row in row_dicts}
            for index, future in enumerate(as_completed(future_map), start=1):
                uk, us, status, sources_json, word = future.result()
                counts[status] += 1
                updates.append((uk, us, status, sources_json, word))
                if not dry_run and len(updates) >= commit_every:
                    write_updates(conn, updates)
                    committed += len(updates)
                    updates.clear()
                    print(f"committed={committed}/{len(rows)}")
                if index <= 20 or index % 100 == 0 or index == len(rows):
                    print(f"{index}/{len(rows)} {word}: uk={uk or '-'} us={us or '-'} status={status}")

    if not dry_run and updates:
        write_updates(conn, updates)
        committed += len(updates)
        updates.clear()
        print(f"committed={committed}/{len(rows)}")

    conn.close()
    return dict(counts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--word", action="append", dest="words")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--delay", type=float, default=0.15)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--commit-every", type=int, default=500)
    args = parser.parse_args()

    counts = fill(args.words, args.limit, args.dry_run, args.delay, args.workers, args.commit_every)
    print("summary:", json.dumps(counts, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
