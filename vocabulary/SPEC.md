# 背单词引擎 — Moread-Content 词汇模块规格

> **状态**: 🟡 草案 — 待用户确认
> **创建**: 2026-05-04
> **范围**: 仅 moread-content 仓库的词汇数据变更
> **配对文档**: Moread 主项目 `docs/01-specs/01_12_Memorize_Engine_Spec.md`

---

## 1. 背景

Moread 从纯精读扩展为精读+背单词双引擎。moread-content 作为英语教学内容资源库，需要让消费端（Moread 及其他产品）能直接以词库为单位选用词汇数据。

**moread-content 的职责**：
- 分门别类存好词库数据，格式统一，拿来即用
- 缺失字段（phonetic、zh）从 dictionary/ 补全
- 提供 index.json 索引，告诉消费端有哪些词库可用

**不需要做的事**：
- ❌ 另存一份"词库包副本"（packs/）
- ❌ 构建工具从原始数据生成新文件
- ❌ 管数据库表、API、前端（那是 Moread 主项目的事）

---

## 2. 现有词库现状

```
vocabulary/
├── cefr/
│   ├── a1.json   (600词, 部分缺 zh/phonetic)
│   ├── a2.json   (600词, 同上)
│   ├── b1.json   (1300词, 同上)
│   ├── b2.json   (2500词, 同上)
│   ├── c1.json   (1129词, 同上)
│   └── c2.json   (1053词, 同上)
├── exam/
│   ├── zhongkao.json (1600词, 有 zh)
│   └── gaokao.json   (2288词, 有 zh, 有 frequency_rank)
└── combined/          ← 交叉索引（待建）
```

**问题**：
1. cefr/ 和 exam/ 的 JSON 顶层格式不一致（一个用 `level`，一个用 `exam`/`year`）
2. cefr/ 大量词缺 phonetic 和 zh
3. 没有一个统一的索引文件告诉消费端有哪些词库可用
4. 教材单元词汇（textbook/ 的 key_vocabulary）提取完后需要汇总为独立词库文件

---

## 3. 变更方案

### 3.1 统一 JSON 格式

所有词库文件统一为相同格式：

```json
{
  "id": "cefr-a1",
  "name": "CEFR A1 入门",
  "category": "cefr",
  "difficulty": "A1",
  "word_count": 600,
  "source": "数据来源说明",
  "words": [
    {
      "word": "about",
      "pos": "prep./adv.",
      "phonetic": "/əˈbaʊt/",
      "zh": "关于；大约"
    }
  ]
}
```

各词库保留各自的特有字段（如 gaokao 的 `frequency_rank`），但顶层 `words[]` 结构统一。

### 3.2 补全缺失字段

cefr/ 中缺 phonetic/zh 的词，从 `dictionary/`（ECDICT 70万词条）查补：
- 补全脚本：`tools/fix-vocabulary.py`（一次性运行）
- 直接修改原文件，不生成副本
- dictionary 也查不到的保留空值，不编造

### 3.3 新增词库索引 `vocabulary/index.json`

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

消费端读 `index.json` 获取词库列表，按 `file` 字段读取具体词库数据。

### 3.4 教材词库（教材提取后追加）

textbook/ 提取完成后，在 `vocabulary/` 下新增教材词库：

```
vocabulary/
├── cefr/
├── exam/
├── textbook/              ← 🆕 教材单元词汇汇总
│   ├── fltrp-junior-sun-grade7-up.json
│   ├── fltrp-junior-sun-grade7-down.json
│   ├── fltrp-junior-chen-grade8-up.json
│   └── ...
├── combined/
└── index.json             ← 追加 textbook 类词条目
```

教材词库 JSON 格式与 cefr/exam 统一。数据来源是 textbook/ 下各 JSON 的 `units[].key_vocabulary[]`，按册汇总。

### 3.5 交叉索引 `vocabulary/combined/word-levels.json`

（原有计划，与背单词功能相关但独立）

```json
{
  "abandon": { "cefr": "B1", "zhongkao": false, "gaokao": true },
  "ability": { "cefr": "A2", "zhongkao": true, "gaokao": true }
}
```

用于消费端跨词库查询某个词的归属关系。

---

## 4. 目录结构（变更后）

```
vocabulary/
├── README.md              ← 更新说明
├── SPEC.md                ← 本文件
├── TODO.json
├── index.json             ← 🆕 词库索引
├── cefr/                  ← 格式统一 + 字段补全
│   ├── a1.json ~ c2.json
├── exam/                  ← 格式统一
│   ├── zhongkao.json
│   └── gaokao.json
├── textbook/              ← 🆕 教材词库（提取后追加）
│   └── ...
└── combined/              ← 交叉索引
    └── word-levels.json
```

---

## 5. 消费端集成方式

Moread 后端通过 `sync-to-db.ts` 将词库数据导入 PostgreSQL：

```
vocabulary/index.json  → word_packs 表（词库元信息）
vocabulary/cefr/*.json → word_pack_words 表（词库单词）
vocabulary/exam/*.json → word_pack_words 表
```

或直接读 JSON 文件，不需要数据库中间层（取决于消费端架构选择）。

---

## 6. 实施步骤

1. **统一格式**：改 cefr/*.json 和 exam/*.json 的顶层结构为统一格式
2. **补全字段**：运行 `tools/fix-vocabulary.py` 从 dictionary/ 补齐 phonetic/zh
3. **创建索引**：写 `vocabulary/index.json`
4. **更新 README**：同步更新 vocabulary/README.md
5. **教材词库**（依赖 textbook 提取）：汇总 key_vocabulary → vocabulary/textbook/*.json → index.json 追加条目
