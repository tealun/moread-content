# 词汇模块设计

> **状态**: 🟡 草案 — 待用户确认
> **创建**: 2026-05-04
> **更新**: 2026-05-04（全量词库 19 个，73,542 词；补充 API 文档）

---

## 1. 架构：词单 + 底座分离

**底座**（`dictionary/`）：ECDICT 70万词条，含 phonetic、pos、zh、definitions、examples、cefr、frequency 等完整数据。按首字母分文件存储（a.json ~ z.json），同时提供 SQL 格式（a.sql ~ z.sql）。

**词库**（`vocabulary/`）：只有词单——告诉消费端"这个词库包含哪些单词"。不存释义、不存音标，释义由底座统一提供。

**API**（`api/`）：FastAPI 模块化服务，`main.py` 为启动入口。路由拆分为词库（vocabulary.py）和词典（dictionary.py），中间件和数据加载层各自独立。

```
消费端 → GET /api/packs → 拿到词库列表（缓存到本地）
消费端 → GET /api/packs/{pack_id} → 拿到词单（缓存 JSON 文件）
消费端 → POST /api/dictionary/batch → 批量拿释义
```

---

## 2. 词库文件格式

每个词库一个 JSON，只存词单：

```json
{
  "id": "exam-gaokao",
  "name": "高考考纲",
  "category": "exam",
  "difficulty": "A2-B2",
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
  { "id": "exam-gaokao",  "name": "高考考纲",             "category": "exam",      "difficulty": "A2-B2", "word_count": 3837,  "file": "exam/gaokao.json" },
  { "id": "exam-gre",     "name": "GRE 研究生入学",       "category": "exam",      "difficulty": "C1-C2", "word_count": 9468,  "file": "exam/gre.json" },
  { "id": "exam-ielts",   "name": "雅思 IELTS",           "category": "exam",      "difficulty": "B1-C1", "word_count": 3576,  "file": "exam/ielts.json" },
  { "id": "exam-kaoyan",  "name": "考研英语",             "category": "exam",      "difficulty": "B2-C1", "word_count": 5648,  "file": "exam/kaoyan.json" },
  { "id": "exam-toefl",   "name": "托福 TOEFL",           "category": "exam",      "difficulty": "B2-C2", "word_count": 10365, "file": "exam/toefl.json" },
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
├── dictionary/              ← 底座（ECDICT 70万词条）
│   ├── a.json ~ z.json      ← JSON 格式，按首字母分文件
│   ├── a.sql ~ z.sql        ← SQL 格式（对称）
│   └── schema.sql           ← PostgreSQL 建表语句
├── vocabulary/              ← 词单（轻量，只有单词列表）
│   ├── index.json           ← 词库索引（19 个词库）
│   ├── cefr/                ← CEFR 分级词单（6 个）
│   ├── exam/                ← 考试考纲词单（8 个）
│   └── frequency/           ← 词频词单（5 个，按 Google 10K 真实词频排序）
├── textbook/                ← 教材同步数据
│   ├── SPEC.md
│   ├── pep/                 ← 人教版（待提取）
│   └── fltrp/               ← 外研版（待提取）
├── api/                     ← API 模块
│   ├── middleware.py        ← IP 白名单 + CORS + 配置加载
│   ├── data.py              ← 数据加载层（索引/词库/词典缓存）
│   ├── vocabulary.py        ← 词库路由（packs/words/stats/health）
│   └── dictionary.py        ← 词典路由（lookup/batch/search）
├── main.py                  ← 启动入口（创建 app + 挂载路由）
├── DATA_API_SPEC.md         ← 本文件（数据端完整规格）
└── requirements.txt         ← Python 依赖
```

---

## 5. 词库分类说明

| 类别 | 数量 | 说明 |
|------|------|------|
| **CEFR** | 6 | A1~C2 分级，各级有少量跨级重叠，去重累计 6,780 词 |
| **考试** | 8 | 中考/高考/CET-4/CET-6/考研/雅思/托福/GRE，双源合并去重 |
| **词频** | 5 | Top 1k~10k，按真实词频排序（Google 10K 语料），含嵌套关系 |
| **教材** | 待定 | 从 textbook/ 提取后追加 |

**词频系列的嵌套关系**：Top-1000 ⊂ Top-2000 ⊂ Top-3000 ⊂ Top-5000 ⊂ Top-10000

---

## 6. API 接口

启动方式：`uvicorn main:app --host 0.0.0.0 --port 8900`

### 6.1 健康检查

```
GET /api/health
```

**返回**：
```json
{ "status": "ok", "packs": 19 }
```

### 6.2 词库列表

```
GET /api/packs
```

**返回**：index.json 原始格式（19 条记录的数组）
```json
[
  { "id": "cefr-a1", "name": "CEFR A1", "category": "cefr", "difficulty": "A1", "word_count": 600, "file": "cefr/a1.json" },
  ...
]
```

### 6.3 词库详情（含完整词单）

```
GET /api/packs/{pack_id}
```

**返回**：词库 JSON 原始格式
```json
{
  "id": "exam-gaokao",
  "name": "高考考纲",
  "category": "exam",
  "difficulty": "A2-B2",
  "words": ["abandon", "ability", ...]
}
```

### 6.4 词库单词分页

```
GET /api/packs/{pack_id}/words?offset=0&limit=100
```

**参数**：
- `offset`：偏移量（默认 0）
- `limit`：每页数量（默认 100，最大 1000）

**返回**：
```json
{
  "pack_id": "exam-gaokao",
  "offset": 0,
  "limit": 100,
  "total": 3837,
  "words": ["abandon", "ability", ...]
}
```

### 6.5 单词释义查询

```
GET /api/dictionary/{word}
```

**返回**：ECDICT 底座中的完整词条
```json
{
  "word": "abandon",
  "phonetic": "/əˈbændən/",
  "pos": "v. n.",
  "zh": "v. 放弃；抛弃  n. 放纵；放纵",
  "definitions": "v. 放弃；抛弃  n. 放纵",
  "examples": "",
  "cefr": "B1",
  "frequency": 3000
}
```

查不到时返回 HTTP 404：`{ "error": "Word not found", "word": "xxx" }`

### 6.6 批量单词释义

```
POST /api/dictionary/batch?words=abandon&words=ability&words=...
```

**返回**：
```json
{
  "abandon": { "phonetic": "...", "pos": "...", "zh": "...", ... },
  "ability": { "phonetic": "...", "pos": "...", "zh": "...", ... }
}
```

### 6.7 单词前缀搜索

```
GET /api/search?q=ab&limit=20
```

**返回**：
```json
{
  "query": "ab",
  "count": 20,
  "words": ["ab", "abandon", "abandoned", "abandonment", ...]
}
```

### 6.8 词库统计

```
GET /api/stats
```

**返回**：
```json
{
  "total_packs": 19,
  "total_words": 73542,
  "categories": { "cefr": 6, "exam": 8, "frequency": 5 },
  "packs": [...]
}
```

---

## 7. 消费端集成方式

### 推荐方式：API + 本地 JSON 缓存

消费端部署 moread-content API 服务，启动时将词库数据缓存为本地 JSON 文件，运行时从缓存抽词、从 API 查释义。

**启动时同步（系统行为，一次性）**：
1. `GET /api/packs` → 拿到词库列表，存为 `cache/packs.json`
2. 对每个词库 `GET /api/packs/{pack_id}` → 拿到词单，存为 `cache/{pack_id}.json`
3. 对比本地缓存与远端数据：若词库数量或总词数不一致，重新拉取覆盖

**运行时**：
- **抽词出题**：读本地缓存 JSON，内存中过滤已背词，`random.sample` 抽词
- **查释义**：`POST /api/dictionary/batch` 批量获取释义
- **用户选词库**：消费端只写一条用户记录（pack_id 字符串），不触发同步

**缓存更新**：
- 启动时自动检查：`GET /api/stats` 对比 `total_packs` + `total_words`，有变化则重新拉取
- 也可手动触发：管理接口清除缓存，下次请求自动重新拉取

**缓存文件结构**（消费端本地）：
```
data/cache/
├── packs.json                    ← GET /api/packs 的返回结果
├── exam-gaokao.json              ← 高考考纲词单
├── exam-cet4.json                ← 四级词单
├── ...（共 19 个词库 JSON）
```

**量级**：19 个 JSON 文件，总计约 2~3 MB（最大的托福 10,365 词约 100 KB）。

### 离线方式：直接读 JSON

消费端直接 clone 仓库，读 JSON 文件。适合完全离线场景。

### 对接关键接口

| 消费端需求 | 数据端接口 | 返回内容 |
|---|---|---|
| 词库列表（缓存） | `GET /api/packs` | 19 个词库的 id/name/category/word_count |
| 词单（缓存） | `GET /api/packs/{pack_id}` | `{id, name, words: [...]}` |
| 批量释义 | `POST /api/dictionary/batch` | `{word: {phonetic, pos, zh, ...}}` |
| 缓存校验 | `GET /api/stats` | `{total_packs, total_words}` |
| 单词释义 | `GET /api/dictionary/{word}` | 完整词条（单查用） |

---

## 8. 数据质量

- 全部 19 个词库结构完整，无内部重复
- 考试词库为 mahavivo（教育部考纲）+ KyleBing（官方词表）双源合并
- 词频系列按 Google 10K 真实词频排序，已清理网页残留和非单词垃圾
- 所有拼写错误已修正（GRE/TOEFL/CET-6）
- 每个词库随机抽检 20 词，在 dictionary/ 底座中命中率 > 99%
