# 背单词引擎 — Moread-Content 数据架构

> **状态**: 🟡 草案 — 待用户确认
> **创建**: 2026-05-04
> **范围**: 仅 moread-content 仓库的词库数据变更
> **配对文档**: Moread 主项目 `docs/01-specs/01_12_Memorize_Engine_Spec.md`

---

## 1. 背景

Moread 从纯精读扩展为精读+背单词双引擎。moread-content 需要提供标准化的词库包（Pack），供 Moread 主项目消费。

**moread-content 的职责边界**：
- ✅ 提供标准化词库包数据（packs/）
- ✅ 提供词库包索引（packs/index.json）
- ✅ 从原始数据构建词库包的工具（tools/build-packs.py）
- ✅ 补全缺失的翻译/音标（从 dictionary/ 交叉）
- ❌ 不管数据库表、API、前端交互（那是 Moread 主项目的事）

---

## 2. 目录结构变更

```
vocabulary/
├── README.md
├── SPEC.md                  ← 本文件
├── TODO.json
├── cefr/                    ← 原始数据不动
│   ├── a1.json ~ c2.json
├── exam/                    ← 原始数据不动
│   ├── gaokao.json
│   └── zhongkao.json
├── packs/                   ← 🆕 消费端词库包
│   ├── index.json           ← 词库包索引
│   ├── cefr-a1.json
│   ├── cefr-a2.json
│   ├── cefr-b1.json
│   ├── cefr-b2.json
│   ├── cefr-c1.json
│   ├── cefr-c2.json
│   ├── exam-gaokao.json
│   └── exam-zhongkao.json
└── (教材词库包，教材提取后追加)
```

---

## 3. 词库包索引格式 `packs/index.json`

```json
[
  {
    "id": "cefr-a1",
    "name": "CEFR A1 入门",
    "description": "欧洲语言共同框架入门级，日常生活基础词汇",
    "word_count": 600,
    "category": "cefr",
    "difficulty": "A1",
    "sort_order": 1
  },
  {
    "id": "cefr-a2",
    "name": "CEFR A2 基础",
    "description": "日常交流和简单话题所需词汇",
    "word_count": 600,
    "category": "cefr",
    "difficulty": "A2",
    "sort_order": 2
  },
  {
    "id": "cefr-b1",
    "name": "CEFR B1 中级",
    "description": "独立应对日常沟通和话题讨论",
    "word_count": 1300,
    "category": "cefr",
    "difficulty": "B1",
    "sort_order": 3
  },
  {
    "id": "cefr-b2",
    "name": "CEFR B2 中高级",
    "description": "流利沟通，理解复杂文本主旨",
    "word_count": 2500,
    "category": "cefr",
    "difficulty": "B2",
    "sort_order": 4
  },
  {
    "id": "cefr-c1",
    "name": "CEFR C1 高级",
    "description": "灵活运用语言进行学术和专业表达",
    "word_count": 1129,
    "category": "cefr",
    "difficulty": "C1",
    "sort_order": 5
  },
  {
    "id": "cefr-c2",
    "name": "CEFR C2 精通",
    "description": "接近母语水平，理解几乎所有文本",
    "word_count": 1053,
    "category": "cefr",
    "difficulty": "C2",
    "sort_order": 6
  },
  {
    "id": "exam-zhongkao",
    "name": "中考考纲",
    "description": "中考英语核心词汇",
    "word_count": 1600,
    "category": "exam",
    "difficulty": "A2-B1",
    "sort_order": 10
  },
  {
    "id": "exam-gaokao",
    "name": "高考考纲",
    "description": "高考英语核心词汇",
    "word_count": 2288,
    "category": "exam",
    "difficulty": "B1-B2",
    "sort_order": 11
  }
]
```

**字段说明**：
- `id`：全局唯一标识，同时作为文件名（`packs/{id}.json`）
- `category`：`cefr` / `exam` / `textbook`（三类来源）
- `sort_order`：前端展示排序权重，越小越靠前
- `word_count`：必须和实际 packs/{id}.json 的 words 数组长度一致

---

## 4. 词库包文件格式 `packs/*.json`

从原始数据转换的标准化格式，Moread 后端消费端直接可用：

```json
{
  "id": "cefr-a1",
  "name": "CEFR A1 入门",
  "word_count": 600,
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

**与原始数据的区别**：
- 原始数据（cefr/a1.json）含 source、level 等元数据 → 词库包去掉，只留消费端需要的字段
- 原始数据部分词缺 zh/phonetic → 构建时从 dictionary/ 补全（ECDICT 70万词条）
- words 按字母序排列
- 每个词只有4个字段：`word`、`pos`、`phonetic`、`zh`，不放大段释义

---

## 5. 构建工具 `tools/build-packs.py`

### 输入

```
vocabulary/cefr/a1.json ~ c2.json
vocabulary/exam/gaokao.json, zhongkao.json
dictionary/a.json ~ z.json（补全翻译/音标用）
```

### 输出

```
vocabulary/packs/index.json
vocabulary/packs/cefr-a1.json ~ cefr-c2.json
vocabulary/packs/exam-gaokao.json, exam-zhongkao.json
```

### 逻辑

```
1. 读取原始词表（cefr/*.json, exam/*.json）
2. 对每个词：
   a. 如果原始数据已有 pos + phonetic + zh → 直接用
   b. 如果缺失 → 查 dictionary/（ECDICT JSON）补全
   c. 如果 dictionary 也找不到 → 保留空值，不编造
3. 写入 packs/{id}.json（标准化格式）
4. 汇总生成 packs/index.json
5. 校验：index.json 的 word_count 和实际 words 数量一致
```

### 运行方式

```bash
cd ~/projects/moread-content
python3 tools/build-packs.py
# 输出到 vocabulary/packs/
```

---

## 6. 数据流

```
moread-content                               Moread 主项目
═════════════                               ═════════════

cefr/*.json  ─┐
exam/*.json  ─┤── build-packs.py
dictionary/  ─┘
       │
       ▼
vocabulary/packs/
  ├── index.json     ──── sync-to-db.ts ────→  word_packs 表（系统词库）
  ├── cefr-a1.json   ──── sync-to-db.ts ────→  word_pack_words 表（词库单词）
  └── ...
                                                  │
                                                  ▼
                                               Moread 后端 API
                                                  │
                                                  ▼
                                               Moread 前端
                                            （词库选择/背单词/词汇本）
```

**sync-to-db.ts**（moread-content 的 tools/）负责把 packs/ 数据生成 SQL 种子文件，Moread 主项目安装时导入。

---

## 7. 后续追加：教材词库包

教材数据从 PDF 提取完成后（textbook/ 目录），追加教材词库包：

```
vocabulary/packs/
  ├── ...
  ├── fltrp-junior-sun-grade7-up.json    ← 从 textbook/ 的 key_vocabulary 提取
  ├── fltrp-junior-sun-grade7-down.json
  ├── fltrp-junior-chen-grade8-up.json
  └── ...
```

index.json 追加对应条目，category = "textbook"。

提取逻辑在 build-packs.py 中追加一个 textbook 分支：遍历 textbook/ 下所有 JSON 的 `units[].key_vocabulary[]`，按册汇总成词库包。
