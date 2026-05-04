# moread-content

> 开源英语教学内容资源库，面向中国初高中学习者。
> 提供词典底座、分级词表、考试词库、词频词表、教材同步数据。
> MIT 许可证，可商用。

---

## 两大使命

1. **词库数据管理** — 为背单词功能提供系统内置词库（19 个，73,542 词）
2. **教材同步数据** — 按初高中教学大纲生成同步阅读文章（待建设）

---

## 目录结构

```
moread-content/
├── dictionary/              ← 底座（ECDICT 70万词条）
│   ├── a.json ~ z.json      ← JSON 格式，按首字母分文件
│   ├── a.sql ~ z.sql        ← SQL 格式（对称）
│   └── schema.sql           ← PostgreSQL 建表语句
│
├── vocabulary/              ← 词单（轻量，只有单词列表）
│   ├── SPEC.md              ← 词汇模块完整设计文档
│   ├── index.json           ← 词库索引（19 个词库）
│   ├── cefr/                ← CEFR 分级（6 个：A1~C2）
│   ├── exam/                ← 考试考纲（8 个：中考/高考/CET-4/CET-6/考研/雅思/托福/GRE）
│   ├── frequency/           ← 词频词表（5 个：Top 1k~10k，按真实词频排序）
│   └── textbook/            ← 教材词单（待追加）
│
├── textbook/                ← 教材同步数据
│   ├── SPEC.md              ← 教材数据设计文档
│   ├── pep/                 ← 人教版（待提取）
│   └── fltrp/               ← 外研版（待提取）
│
├── api/                     ← FastAPI 词库底座服务（开发测试用）
│   ├── main.py
│   └── requirements.txt
│
└── tools/
    ├── generate_dictionary_sql.py  ← dictionary JSON → SQL
    └── import_dictionary.py        ← 导入到 PostgreSQL
```

---

## 架构：词单 + 底座分离

**词库文件只存单词列表**，不存音标、不存释义。释义从 `dictionary/`（ECDICT 70万词条底座）按需查。

```json
// vocabulary/exam/gaokao.json — 词库只长这样
{
  "id": "exam-gaokao",
  "name": "高考考纲",
  "category": "exam",
  "difficulty": "A2-B2",
  "words": ["abandon", "ability", "able", ...]
}
```

```
用户选词库 → 后端从词单抽词 → 去 ECDICT 底座查完整释义 → 展示给用户
```

---

## 19 个词库一览

| 类别 | 词库 | 词数 | 难度 |
|------|------|------|------|
| CEFR | A1 | 600 | A1 |
| CEFR | A2 | 600 | A2 |
| CEFR | B1 | 1,298 | B1 |
| CEFR | B2 | 2,500 | B2 |
| CEFR | C1 | 1,026 | C1 |
| CEFR | C2 | 999 | C2 |
| 考试 | 中考 | 1,600 | A1-A2 |
| 考试 | 高考 | 3,837 | A2-B2 |
| 考试 | CET-4 | 5,183 | B1-B2 |
| 考试 | CET-6 | 5,974 | B2-C1 |
| 考试 | 考研 | 5,648 | B2-C1 |
| 考试 | 雅思 | 3,576 | B1-C1 |
| 考试 | 托福 | 10,365 | B2-C2 |
| 考试 | GRE | 9,468 | C1-C2 |
| 词频 | Top 1000 | 1,000 | — |
| 词频 | Top 2000 | 2,000 | — |
| 词频 | Top 3000 | 3,000 | — |
| 词频 | Top 5000 | 5,000 | — |
| 词频 | Top 10000 | 9,868 | — |

**总计 73,542 词**

---

## 集成方式

### 导入 PostgreSQL（推荐）

```bash
# 生成 SQL
python tools/generate_dictionary_sql.py

# 导入到 PostgreSQL
python tools/import_dictionary.py
```

导入后生成 3 张表：`dictionary`（底座）+ `word_packs`（词库）+ `word_pack_words`（词库单词）

```sql
-- 示例：抽20个高考词库中用户没背过的词
SELECT w.word, d.phonetic, d.pos, d.definitions, d.cefr
FROM word_pack_words w
JOIN dictionary d ON w.word = d.word
WHERE w.pack_id = 'exam-gaokao'
  AND w.word NOT IN (SELECT word FROM vocabulary_book WHERE user_id = $1)
ORDER BY RANDOM()
LIMIT 20;
```

### 直接使用 JSON

```javascript
import packs from 'moread-content/vocabulary/index.json'
import gaokao from 'moread-content/vocabulary/exam/gaokao.json'
```

---

## 数据来源与版权

| 数据 | 来源 | 许可证 |
|------|------|--------|
| 词典底座 | [ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| CEFR 词表 | vocabulary.englishprofile.org | 整理加工 |
| 考试词库 | mahavivo/english-wordlists + KyleBing/english-vocabulary | 双源合并 |
| 词频词表 | Google 10K Corpus | 整理加工 |
| 教材同步 | AI 自创 + 人工审核 | MIT（本仓库） |

---

## 内容格式约定

- 所有文件 **UTF-8** 编码
- JSON **2 空格缩进**
- 等级标签使用 **CEFR 标准**（A1~C2）
- 词库 JSON 统一格式：`{id, name, category, difficulty, words: ["word1", ...]}`

---

## 详细设计文档

- `vocabulary/SPEC.md` — 词库模块完整设计（架构、格式、消费端指南）
- `textbook/SPEC.md` — 教材同步数据设计（JSON Schema、学段隔离原则）
