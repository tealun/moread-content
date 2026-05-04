# 词汇模块设计

> **状态**: 🟡 草案 — 待用户确认
> **创建**: 2026-05-04
> **更新**: 2026-05-04（简化架构：词单+底座分离）

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
  "description": "高考英语核心词汇",
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
  {
    "id": "cefr-a1",
    "name": "CEFR A1 入门",
    "category": "cefr",
    "difficulty": "A1",
    "word_count": 600,
    "file": "cefr/a1.json"
  },
  {
    "id": "cefr-a2",
    "name": "CEFR A2 基础",
    "category": "cefr",
    "difficulty": "A2",
    "word_count": 600,
    "file": "cefr/a2.json"
  },
  {
    "id": "cefr-b1",
    "name": "CEFR B1 中级",
    "category": "cefr",
    "difficulty": "B1",
    "word_count": 1300,
    "file": "cefr/b1.json"
  },
  {
    "id": "cefr-b2",
    "name": "CEFR B2 中高级",
    "category": "cefr",
    "difficulty": "B2",
    "word_count": 2500,
    "file": "cefr/b2.json"
  },
  {
    "id": "cefr-c1",
    "name": "CEFR C1 高级",
    "category": "cefr",
    "difficulty": "C1",
    "word_count": 1129,
    "file": "cefr/c1.json"
  },
  {
    "id": "cefr-c2",
    "name": "CEFR C2 精通",
    "category": "cefr",
    "difficulty": "C2",
    "word_count": 1053,
    "file": "cefr/c2.json"
  },
  {
    "id": "exam-zhongkao",
    "name": "中考考纲",
    "category": "exam",
    "difficulty": "A2-B1",
    "word_count": 1600,
    "file": "exam/zhongkao.json"
  },
  {
    "id": "exam-gaokao",
    "name": "高考考纲",
    "category": "exam",
    "difficulty": "B1-B2",
    "word_count": 2288,
    "file": "exam/gaokao.json"
  }
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
│   ├── index.json           ← 词库索引
│   ├── cefr/                ← CEFR 分级词单
│   │   ├── a1.json
│   │   ├── a2.json
│   │   ├── b1.json
│   │   ├── b2.json
│   │   ├── c1.json
│   │   └── c2.json
│   ├── exam/                ← 考试考纲词单
│   │   ├── zhongkao.json
│   │   └── gaokao.json
│   └── textbook/            ← 教材词单（教材提取后追加）
│       └── ...
├── textbook/                ← 教材同步数据（待讨论）
└── tools/
    └── sync-to-db.ts        ← 一键同步到 PostgreSQL
```

---

## 5. 现有文件需要做的变更

**cefr/*.json**：从现在的 `{level, word_count, words: [{word, pos, zh}]}` 简化为 `{id, name, category, difficulty, words: ["word1", "word2", ...]}`

**exam/*.json**：同上简化

**dictionary/**：不动，已经是底座

**新增 index.json**：词库索引

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

## 7. 待办

- [ ] 简化 cefr/*.json 格式（去掉 pos/phonetic/zh，只留单词列表）
- [ ] 简化 exam/*.json 格式
- [ ] 创建 vocabulary/index.json
- [ ] 更新 vocabulary/README.md
- [ ] 教材词单（textbook 提取后追加）
- [ ] 教材同步数据设计（待讨论）
