# Vocabulary Data

This directory contains CEFR-graded vocabulary lists and Chinese exam (高考/中考) vocabulary data.

## Directory Structure

```
vocabulary/
├── README.md
├── TODO.json
├── cefr/                  ← CEFR official levels
│   ├── a1.json
│   ├── a2.json
│   ├── b1.json
│   ├── b2.json
│   ├── c1.json
│   └── c2.json
└── exam/                  ← Chinese exam syllabi
    ├── gaokao.json        ← 高考 (College Entrance Exam) vocabulary
    └── zhongkao.json      ← 中考 (High School Entrance Exam) vocabulary
```

## Files

### CEFR Level Vocabulary (`cefr/`)
- `a1.json` - CEFR A1 (Beginner) ~600 words
- `a2.json` - CEFR A2 (Elementary) ~600 words  
- `b1.json` - CEFR B1 (Intermediate) ~1300 words
- `b2.json` - CEFR B2 (Upper-Intermediate) ~2500 words
- `c1.json` - CEFR C1 (Advanced) ~1129 words
- `c2.json` - CEFR C2 (Proficiency) ~1053 words

### Chinese Exam Vocabulary (`exam/`)
- `gaokao.json` - 高考 (College Entrance Exam) ~2288 words (with Chinese translations)
- `zhongkao.json` - 中考 (High School Entrance Exam) ~1600 words (with Chinese translations)

## Data Sources

1. **CEFR A1-B2**: `vocabulary-list-statistics` npm package (50k word frequency list) mapped to CEFR levels using rank boundaries:
   - A1: rank 1-600
   - A2: rank 601-1200
   - B1: rank 1201-2500
   - B2: rank 2501-5000

2. **CEFR C1-C2**: Octanove Vocabulary Profile C1/C2 1.0 dataset from michigan-musicer/cefr-text-vocab-scanner

3. **高考/中考**: HK-SHAO/English-Dictionary (Apache-2.0) - word frequency data from Chinese English exam papers

4. **Chinese Translations**: Primarily from HK-SHAO/English-Dictionary dictionary data (~2288 words with full Chinese definitions)

## Known Limitations / TODOs

1. **CEFR levels are approximate**: A1-B2 levels are assigned based on frequency rank, not actual English Profile CEFR ratings. For accurate CEFR assignments, consider using the Cambridge English Vocabulary Profile API (https://www.englishprofile.org/wordlists)

2. **Missing Chinese translations**: Many words in the CEFR lists lack Chinese definitions. The dictionary source only had ~2288 words. Consider:
   - Using Youdao/Baidu translation API for batch translation
   - Incorporating data from open Chinese-English dictionaries
   - Using the ECDICT open dictionary project

3. **高考/中考 word counts**: 
   - 高考 standard syllabus is ~3500 words; current data has ~2288
   - 中考 standard syllabus is ~1600-1800 words; current data has ~1600
   - Both lists are derived from exam paper frequency, not the official syllabus
   - Consider supplementing with the official 教育部考试中心 word list

4. **POS (Part of Speech) tagging**: POS data is incomplete. Consider running a POS tagger on the vocabulary or using dictionary API data.

## JSON Format

### CEFR Format
```json
{
  "level": "A1",
  "word_count": 600,
  "source": "data source description",
  "words": [
    {"word": "about", "pos": "", "zh": "关于"}
  ]
}
```

### Exam Format
```json
{
  "exam": "高考",
  "year": 2024,
  "word_count": 2288,
  "words": [
    {"word": "abandon", "zh": "放弃", "frequency_rank": 1}
  ]
}
```
