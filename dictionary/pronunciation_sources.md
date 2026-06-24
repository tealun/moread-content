# Pronunciation Data Sources

This project uses a conservative pronunciation policy:

- US pronunciations are filled only from CMUdict.
- UK pronunciations are filled only from Kaikki/Wiktionary entries explicitly tagged as UK, British, RP, or Received Pronunciation.
- Free Dictionary is not used for main pronunciation writes.
- Entries with multiple competing source pronunciations are marked `conflict` instead of being forced into one default variant.

## Sources

- CMU Pronouncing Dictionary: https://github.com/cmusphinx/cmudict
- Kaikki English Wiktionary extraction: https://kaikki.org/dictionary/rawdata.html
- Wiktionary licensing notes: https://en.wiktionary.org/wiki/Wiktionary:Copyrights

## Status Values

- `same`: UK and US fields are both present and identical under the strict source policy.
- `verified`: UK and US fields are both present and differ under the strict source policy.
- `us_only`: only the CMUdict-derived US field is present.
- `uk_only`: only the explicitly UK/British/RP Kaikki/Wiktionary field is present.
- `conflict`: at least one source side has multiple competing pronunciations; do not present it as a single verified pronunciation.
- `legacy_single`: no strict-source UK/US variant was found; keep the legacy `phonetic` value.
