#!/usr/bin/env python3
"""
Generate per-letter SQL files from dictionary JSON files.

Reads dictionary/a.json through dictionary/z.json and produces
dictionary/a.sql through dictionary/z.sql with batch INSERT statements.
"""

import json
import string
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DICT_DIR = REPO_ROOT / "dictionary"
BATCH_SIZE = 5000
LETTERS = list(string.ascii_lowercase)


def escape_sql_string(s: str) -> str:
    """Escape a string for use in a SQL literal (single quotes)."""
    return s.replace("'", "''")


def format_text_array(items: list) -> str:
    """Format a list of strings as a PostgreSQL ARRAY[...] literal."""
    if not items:
        return "ARRAY[]::TEXT[]"
    escaped = [escape_sql_string(item) for item in items]
    inner = ",".join(f"'{e}'" for e in escaped)
    return f"ARRAY[{inner}]"


def format_row(word: str, entry: dict) -> str:
    """Format a single row for the VALUES clause."""
    phonetic = entry.get("phonetic", "") or ""
    pos = entry.get("pos", []) or []
    definitions = json.dumps(entry.get("definitions", []) or [], ensure_ascii=False)
    examples = json.dumps(entry.get("examples", []) or [], ensure_ascii=False)
    frequency = entry.get("frequency", 0) or 0
    cefr = entry.get("cefr", "") or ""
    forms = entry.get("forms", []) or []
    letter = word[0].lower() if word else ""

    parts = [
        f"'{escape_sql_string(word)}'",
        f"'{escape_sql_string(letter)}'",
        f"'{escape_sql_string(phonetic)}'",
        format_text_array(pos),
        f"'{escape_sql_string(definitions)}'",
        f"'{escape_sql_string(examples)}'",
        str(int(frequency)),
        f"'{escape_sql_string(cefr)}'",
        format_text_array(forms),
    ]
    return "(" + ",".join(parts) + ")"


def generate_letter_sql(letter: str):
    """Generate a .sql file for a single letter."""
    json_path = DICT_DIR / f"{letter}.json"
    sql_path = DICT_DIR / f"{letter}.sql"

    if not json_path.exists():
        print(f"  ⚠  Missing {json_path}, skipping.")
        return

    print(f"  Processing {letter}.json ...", end=" ", flush=True)
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    entries = list(data.items())
    count = len(entries)
    print(f"{count} entries", end=" ", flush=True)

    columns = "word, letter, phonetic, pos, definitions, examples, frequency, cefr, forms"

    lines = []
    lines.append(f"-- dictionary/{letter}.sql")
    lines.append(f"-- Generated from {letter}.json ({count} entries)")
    lines.append("BEGIN;")
    lines.append("")

    for batch_start in range(0, count, BATCH_SIZE):
        batch = entries[batch_start:batch_start + BATCH_SIZE]
        lines.append(
            f"INSERT INTO dictionary ({columns}) VALUES"
        )
        row_strs = [format_row(word, entry) for word, entry in batch]
        # Join with comma+newline, last row gets semicolon
        for i, rs in enumerate(row_strs):
            if i < len(row_strs) - 1:
                lines.append(f"  {rs},")
            else:
                lines.append(f"  {rs};")
        lines.append("")

    lines.append("COMMIT;")

    with open(sql_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"→ {sql_path.name} ({sql_path.stat().st_size / 1024 / 1024:.1f} MB)")


def main():
    print("Generating per-letter SQL files ...")
    for letter in LETTERS:
        generate_letter_sql(letter)
    print("\n✅ Done!")


if __name__ == "__main__":
    main()
