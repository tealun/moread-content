# 词汇模块设计

> **状态**: 🟡 草案 — 待用户确认
> **创建**: 2026-05-04
> **更新**: 2026-05-04（全量词库 19 个，73,542 词）

---

## 1. 架构：词单 + 底座分离

**底座**（`dictionary/`）：ECDICT 70万词条，含 phonetic、pos、zh、definitions、examples、cefr、frequency 等完整数据。已按首字母分文件存储，也可导入 PostgreSQL。

**词库**（`vocabulary/`）：只有词单——告诉消费端"这个词库包含哪些单词"。不存释义、不存音标，释义由底座统一提供。

```
用户选词库 → 后端从词单抽词 → 去 ECDICT 底座查完整数据 → 写入用户个人词库
```

---

## 2. 词库文件格式

每个词库一个 JSON，只存词单：

```json
{
  "id": "exam-gaokao",
  "name": "高考考纲",
  "category": "exam",
  "difficulty": "B1-B2",
  "words": [
    "abandon",
    "ability",
    "able",
    "about",
    "..."
  ]
}
```

**就这么简单。** 没有音标、没有释义、没有词性。那些全部从 `dictionary/` 查。

---

## 3. 词库索引 `vocabulary/index.json`

```json
[
  { "id": "cefr-a1",      "name": "CEFR A1",              "category": "cefr",      "difficulty": "A1",    "word_count": 600,   "file": "cefr/a1.json" },
  { "id": "cefr-a2",      "name": "CEFR A2",              "category": "cefr",      "difficulty": "A2",    "word_count": 600,   "file": "cefr/a2.json" },
  { "id": "cefr-b1",      "name": "CEFR B1",              "category": "cefr",      "difficulty": "B1",    "word_count": 1298,  "file": "cefr/b1.json" },
  { "id": "cefr-b2",      "name": "CEFR B2",              "category": "cefr",      "difficulty": "B2",    "word_count": 2500,  "file": "cefr/b2.json" },
  { "id": "cefr-c1",      "name": "CEFR C1",              "category": "cefr",      "difficulty": "C1",    "word_count": 1026,  "file": "cefr/c1.json" },
  { "id": "cefr-c2",      "name": "CEFR C2",              "category": "cefr",      "difficulty": "C2",    "word_count": 999,   "file": "cefr/c2.json" },
  { "id": "exam-cet4",    "name": "大学英语四级 CET-4",   "category": "exam",      "difficulty": "B1-B2", "word_count": 5183,  "file": "exam/cet4.json" },
  { "id": "exam-cet6",    "name": "大学英语六级 CET-6",   "category": "exam",      "difficulty": "B2-C1", "word_count": 5974,  "file": "exam/cet6.json" },
  { "id": "exam-gaokao",  "name": "高考考纲",             "category": "exam",      "difficulty": "B1-B2", "word_count": 3837,  "file": "exam/gaokao.json" },
  { "id": "exam-gre",     "name": "GRE 研究生入学",       "category": "exam",      "difficulty": "C1-C2", "word_count": 9468,  "file": "exam/gre.json" },
  { "id": "exam-ielts",   "name": "雅思 IELTS",           "category": "exam",      "difficulty": "B2-C1", "word_count": 3576,  "file": "exam/ielts.json" },
  { "id": "exam-kaoyan",  "name": "考研英语",             "category": "exam",      "difficulty": "B2-C1", "word_count": 5648,  "file": "exam/kaoyan.json" },
  { "id": "exam-toefl",   "name": "托福 TOEFL",           "category": "exam",      "difficulty": "B2-C1", "word_count": 10365, "file": "exam/toefl.json" },
  { "id": "exam-zhongkao","name": "中考考纲",             "category": "exam",      "difficulty": "A1-A2", "word_count": 1600,  "file": "exam/zhongkao.json" },
  { "id": "freq-1000",    "name": "高频词 Top 1000",      "category": "frequency", "difficulty": "",      "word_count": 1000,  "file": "frequency/top-1000.json" },
  { "id": "freq-2000",    "name": "高频词 Top 2000",      "category": "frequency", "difficulty": "",      "word_count": 2000,  "file": "frequency/top-2000.json" },
  { "id": "freq-3000",    "name": "高频词 Top 3000",      "category": "frequency", "difficulty": "",      "word_count": 3000,  "file": "frequency/top-3000.json" },
  { "id": "freq-5000",    "name": "高频词 Top 5000",      "category": "frequency", "difficulty": "",      "word_count": 5000,  "file": "frequency/top-5000.json" },
  { "id": "freq-10000",   "name": "高频词 Top 10000",     "category": "frequency", "difficulty": "",      "word_count": 9868,  "file": "frequency/top-10000.json" }
]
```

---

## 4. 目录结构

```
moread-content/
├── dictionary/              ← 底座（ECDICT 70万词条，已有）
│   ├── a.json ~ z.json      ← JSON 格式，按首字母分文件
│   ├── a.sql ~ z.sql        ← SQL 格式（对称）
│   └── schema.sql
├── vocabulary/              ← 词单（轻量，只有单词列表）
│   ├── index.json           ← 词库索引（19 个词库）
│   ├── cefr/                ← CEFR 分级词单（6 个）
│   │   ├── a1.json
│   │   ├── a2.json
│   │   ├── b1.json
│   │   ├── b2.json
│   │   ├── c1.json
│   │   └── c2.json
│   ├── exam/                ← 考试考纲词单（8 个）
│   │   ├── zhongkao.json    ← 中考 1600
│   │   ├── gaokao.json      ← 高考 3837
│   │   ├── cet4.json        ← 四级 5183
│   │   ├── cet6.json        ← 六级 5974
│   │   ├── kaoyan.json      ← 考研 5648
│   │   ├── ielts.json       ← 雅思 3576
│   │   ├── toefl.json       ← 托福 10365
│   │   └── gre.json         ← GRE 9468
│   ├── frequency/           ← 词频词单（5 个，按 Google 10K 真实词频排序）
│   │   ├── top-1000.json
│   │   ├── top-2000.json
│   │   ├── top-3000.json
│   │   ├── top-5000.json
│   │   └── top-10000.json
│   └── textbook/            ← 教材词单（教材提取后追加）
│       └── ...
├── textbook/                ← 教材同步数据（待讨论）
└── tools/
    └── sync-to-db.ts        ← 一键同步到 PostgreSQL
```

---

## 5. 词库分类说明

| 类别 | 数量 | 说明 |
|------|------|------|
| **CEFR** | 6 | A1~C2 分级，各级独立无重叠，累计 6,823 词 |
| **考试** | 8 | 中考/高考/CET-4/CET-6/考研/雅思/托福/GRE，双源合并去重 |
| **词频** | 5 | Top 1k~10k，按真实词频排序（Google 10K 语料），含嵌套关系 |
| **教材** | 待定 | 从 textbook/ 提取后追加 |

**词频系列的嵌套关系**：Top-1000 ⊂ Top-2000 ⊂ Top-3000 ⊂ Top-5000 ⊂ Top-10000

---

## 6. 消费端（Moread）使用方式

### 方式一：数据库（推荐）

1. `sync-to-db.ts` 把 dictionary/ 导入 PostgreSQL 的 `dictionary` 表
2. `sync-to-db.ts` 把词库 JSON 导入 `word_packs` + `word_pack_words` 表
3. Moread 后端：抽词从 `word_pack_words` 取，查释义从 `dictionary` 表 JOIN

```sql
-- 抽20个高考词库中用户没背过的词，附带完整释义
SELECT w.word, d.phonetic, d.pos, d.definitions, d.examples, d.cefr
FROM word_pack_words w
JOIN dictionary d ON w.word = d.word
WHERE w.pack_id = 'exam-gaokao'
  AND w.word NOT IN (SELECT word FROM vocabulary_book WHERE user_id = $1)
ORDER BY RANDOM()
LIMIT 20;
```

### 方式二：纯 JSON

1. 前端加载词库 JSON 拿到词单
2. 需要释义时查 dictionary JSON 或后端 API
3. 适合轻量场景

---

## 7. 数据质量

- 全部 19 个词库结构完整，无内部重复
- 考试词库为 mahavivo（教育部考纲）+ KyleBing（官方词表）双源合并
- 词频系列按 Google 10K 真实词频排序，已清理网页残留和非单词垃圾
- 所有拼写错误已修正（GRE/TOEFL/CET-6）
- 每个词库随机抽检 20 词，在 dictionary/ 底座中命中率 > 99%
