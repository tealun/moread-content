-- Dictionary table for moread-content
-- Generated from ECDICT (https://github.com/skywind3000/ECDICT)
-- Total words: 699,895
--
-- Import: Use tools/import_dictionary.py to load JSON data into PostgreSQL.
--   DATABASE_URL=postgres://user:pass@host:5432/dbname python tools/import_dictionary.py
--
-- Or apply this file first to create the schema:
--   psql -d yourdb -f dictionary.sql

DROP TABLE IF EXISTS dictionary;

CREATE TABLE dictionary (
    id          SERIAL PRIMARY KEY,
    word        VARCHAR(100) NOT NULL UNIQUE,
    letter      CHAR(1) NOT NULL,
    phonetic    VARCHAR(100) DEFAULT '',
    pos         TEXT[] DEFAULT '{}',
    definitions JSONB DEFAULT '[]',
    examples    JSONB DEFAULT '[]',
    frequency   INTEGER DEFAULT 0,
    cefr        VARCHAR(4) DEFAULT '',
    forms       TEXT[] DEFAULT '{}',
    created_at  TIMESTAMP DEFAULT NOW()
);

-- Indexes
CREATE INDEX idx_dictionary_letter ON dictionary (letter);
CREATE INDEX idx_dictionary_frequency ON dictionary (frequency DESC);
CREATE INDEX idx_dictionary_word_trgm ON dictionary USING gin (word gin_trgm_ops);
CREATE INDEX idx_dictionary_cefr ON dictionary (cefr) WHERE cefr != '';
