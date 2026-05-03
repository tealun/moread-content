#!/usr/bin/env python3
"""
Import dictionary JSON files into PostgreSQL.

Usage:
    DATABASE_URL=postgres://user:pass@host:5432/dbname python tools/import_dictionary.py

Reads dictionary/a.json through dictionary/z.json from the repository root,
then batch-inserts into the `dictionary` table.

Requirements:
    pip install psycopg2-binary
"""

import json
import os
import sys
import string
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("Error: psycopg2 is required. Install with: pip install psycopg2-binary")
    sys.exit(1)

# ── Config ──────────────────────────────────────────────────────────────────
REPO_ROOT = Path(__file__).resolve().parent.parent
DICT_DIR = REPO_ROOT / "dictionary"
BATCH_SIZE = 5000
LETTERS = list(string.ascii_lowercase)

# ── Helpers ─────────────────────────────────────────────────────────────────

def dict_from_repo_root():
    """Determine the dictionary directory relative to this script."""
    d = REPO_ROOT / "dictionary"
    if d.is_dir():
        return d
    # Fallback: maybe running from the repo root itself
    d = Path("dictionary")
    if d.is_dir():
        return d
    print(f"Error: cannot find dictionary/ directory (tried {REPO_ROOT / 'dictionary'})")
    sys.exit(1)


def iter_words():
    """Yield (word, entry_dict) for every word in every a.json..z.json."""
    for letter in LETTERS:
        path = DICT_DIR / f"{letter}.json"
        if not path.exists():
            print(f"  ⚠  Missing {path}, skipping.")
            continue
        print(f"  Loading {path.name} ...", end=" ", flush=True)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = 0
        for word, entry in data.items():
            yield (word, entry)
            count += 1
        print(f"{count} entries")


def build_row(word, entry):
    """Convert a JSON entry into a tuple matching the INSERT columns."""
    phonetic = entry.get("phonetic", "")
    if phonetic is None:
        phonetic = ""
    pos = entry.get("pos", []) or []
    definitions = json.dumps(entry.get("definitions", []) or [], ensure_ascii=False)
    examples = json.dumps(entry.get("examples", []) or [], ensure_ascii=False)
    frequency = entry.get("frequency", 0) or 0
    cefr = entry.get("cefr", "") or ""
    forms = entry.get("forms", []) or []
    letter = word[0].lower() if word else ""
    return (word, letter, phonetic, pos, definitions, examples, frequency, cefr, forms)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable is required.")
        print("  Example: DATABASE_URL=postgres://user:pass@localhost:5432/mydb python tools/import_dictionary.py")
        sys.exit(1)

    print(f"Connecting to PostgreSQL ...")
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    # Ensure table exists (run dictionary.sql first, or create inline)
    cur.execute("""
        SELECT to_regclass('public.dictionary')
    """)
    if cur.fetchone()[0] is None:
        print("Table 'dictionary' not found. Creating schema ...")
        sql_path = DICT_DIR / "schema.sql"
        if sql_path.exists():
            with open(sql_path, "r", encoding="utf-8") as f:
                cur.execute(f.read())
            conn.commit()
            print("Schema created from dictionary/schema.sql.")
        else:
            print("Error: dictionary/schema.sql not found. Create the table first.")
            sys.exit(1)

    # Clear existing data
    print("Truncating existing dictionary data ...")
    cur.execute("TRUNCATE TABLE dictionary RESTART IDENTITY;")
    conn.commit()

    # Insert in batches
    print("Importing words:")
    INSERT_SQL = """
        INSERT INTO dictionary (word, letter, phonetic, pos, definitions, examples, frequency, cefr, forms)
        VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
        ON CONFLICT (word) DO NOTHING
    """
    batch = []
    total = 0
    for word, entry in iter_words():
        batch.append(build_row(word, entry))
        if len(batch) >= BATCH_SIZE:
            cur.executemany(INSERT_SQL, batch)
            conn.commit()
            total += len(batch)
            print(f"    → {total} words inserted so far")
            batch = []

    # Flush remaining
    if batch:
        cur.executemany(INSERT_SQL, batch)
        conn.commit()
        total += len(batch)

    cur.close()
    conn.close()
    print(f"\n✅ Done! {total} words imported into 'dictionary' table.")


if __name__ == "__main__":
    main()
