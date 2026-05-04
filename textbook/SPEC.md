# Textbook JSON Schema 设计规格

> **状态**: 🟡 草案 — 待用户确认
> **创建**: 2026-05-04
> **背景**: 从 19 本教材 PDF 提取真实数据前，统一 JSON 架构设计

---

## 1. 设计原则

1. **能容纳所有版本差异** — 外研版孙有中/陈琳/人教初高中四种编排模式
2. **宁可多留字段也不要遗漏** — 先从 PDF 提取完再瘦身
3. **一本教材 = 一个 JSON 文件** — 粒度不变
4. **保持与旧字段兼容** — 已有的 publisher_code / level / grade 等字段保留
5. **结构化数据必须来自真实教材** — 禁止 AI 编造

---

## 2. 目录结构（修订版）

```
textbook/
├── README.md
├── SPEC.md                          ← 本文件
├── pep/                             ← 人教版（PEP）
│   ├── junior/
│   │   ├── grade7_up.json
│   │   ├── grade7_down.json
│   │   ├── grade8_up.json
│   │   ├── grade8_down.json
│   │   └── grade9.json
│   └── senior/
│       ├── required1.json
│       ├── required2.json
│       └── required3.json
├── fltrp/                           ← 外研版（FLTRP）
│   ├── junior/                      ← 初中
│   │   ├── sun/                     ← 孙有中主编（2022课标修订）
│   │   │   ├── grade7_up.json
│   │   │   ├── grade7_down.json
│   │   │   ├── grade8_up.json
│   │   │   └── grade8_down.json
│   │   └── chen/                    ← 陈琳主编
│   │       ├── grade8_up.json
│   │       ├── grade8_down.json
│   │       ├── grade9_up.json
│   │       └── grade9_down.json
│   └── senior/                      ← 高中
│       └── chen/                    ← 陈琳主编
│           ├── required1.json
│           ├── required2.json
│           └── required3.json
└── textbook.sql
```

### 目录变更说明

| 旧结构 | 新结构 | 原因 |
|--------|--------|------|
| `fltrp/junior/` | `fltrp/junior/sun/` + `fltrp/junior/chen/` | 初中两个主编版本混在一起，需拆分 |
| `fltrp/senior/` | `fltrp/senior/chen/` | 高中也是陈琳主编，统一归入 chen/ |
| 无 | `SPEC.md` | 架构设计文档 |

### 实际收到的教材清单（19本）

**外研·孙有中（4册，仅初中）**
- 七年级上册 / 七年级下册 / 八年级上册 / 八年级下册
- ⚠️ 缺九年级上下册（平台无此资源）

**外研·陈琳（7册，初中+高中）**
- 初中 4 册：八年级上册 / 八年级下册 / 九年级上册 / 九年级下册
- 高中 3 册：必修1 / 必修2 / 必修3
- ⚠️ 缺七年级上下册（平台无此资源）
- ⚠️ 选择性必修4~7暂不收录

**人教版（8册）**
- 初中 5 册：七上 / 七下 / 八上 / 八下 / 九全
- 高中 3 册：必修1 / 必修2 / 必修3
- ⚠️ 选择性必修1~4 暂不收录

**合计：19 本**

---

## 3. JSON Schema

### 3.1 顶层结构

```json
{
  "meta": { ... },
  "toc": [ ... ],
  "units": [ ... ],
  "appendix": { ... }
}
```

### 3.2 meta（元数据）

```json
{
  "meta": {
    "publisher": "外研版（FLTRP）",
    "publisher_code": "fltrp",
    "editor": "sun",
    "editor_name": "孙有中",
    "standard": "2022年版课程标准",
    "level": "junior",
    "grade": 7,
    "semester": "up",
    "title": "七年级上册",
    "pages": 178,
    "source_pdf": "(FLTRP孙有中根据2022年版课程标准修订)义务教育教科书·英语 七年级上册.pdf",
    "extracted_at": "2026-05-04",
    "confidence": "verified"
  }
}
```

**字段说明：**

- `editor` / `editor_name`：主编代码/姓名。人教版为 `"editor": "pep", "editor_name": null`
- `standard`：课标版本。孙有中版为 `"2022年版课程标准"`，陈琳版可能为 `"2011年版课程标准"`
- `pages`：PDF 总页数（用于定位参考）
- `source_pdf`：原始文件名（溯源用，不入库）
- `confidence`：`"verified"` = 从真实教材提取 | `"estimated"` = 推测数据

### 3.3 toc（目录概览）

从教材目录页提取的**扁平化概览**，用于快速展示和导航：

```json
{
  "toc": [
    {
      "id": "starter",
      "type": "starter",
      "title": "Welcome to junior high!",
      "page": 2,
      "grammar_preview": ["nouns", "numbers", "articles", "simple future tense"]
    },
    {
      "id": "unit-1",
      "type": "unit",
      "number": 1,
      "title": "A new start",
      "page": 14,
      "topic": "初中生活、第一课",
      "topic_en": "Junior high life, the first lesson",
      "grammar_preview": ["Pronouns"],
      "cefr_level": "A1"
    }
  ]
}
```

**说明：** `toc` 是目录页的镜像，每条记录对应目录页上的一行。详细内容在 `units` 中。

### 3.4 units（详细单元数据）

#### 3.4.1 通用 Unit 结构

所有版本的 unit 共享这些字段，有则填、无则 `null`：

```json
{
  "id": "unit-1",
  "number": 1,
  "title": "A new start",
  "page_start": 14,
  "page_end": 28,
  "topic": "初中生活、第一课",
  "topic_en": "Junior high life, the first lesson",
  "cefr_level": "A1",
  "grammar": [
    {
      "name": "人称代词和物主代词",
      "name_en": "Personal pronouns and possessive pronouns",
      "details": "主格与宾格的区分，形容词性物主代词和名词性物主代词"
    }
  ],
  "key_vocabulary": [
    { "word": "polite", "pos": "adj.", "phonetic": "/pəˈlaɪt/", "cn": "有礼貌的", "page": 17 }
  ],
  "key_phrases": [
    { "phrase": "point out", "cn": "指出", "page": 17 }
  ],
  "sentence_patterns": [
    "It's important to think and learn."
  ],
  "sections": [ ... ],
  "language_notes": [ ... ],
  "parallel_articles": []
}
```

**字段说明：**

- `grammar[]`：语法点数组。`details` 存放从"Guide to the language use"提取的详细说明
- `key_vocabulary[]`：单词表数据，包含音标、词性、中文、页码（从 Words and expressions 页提取）
- `key_phrases[]`：重点短语
- `sentence_patterns[]`：重点句型
- `sections[]`：单元内板块结构（见 3.4.2）
- `language_notes[]`：语言注释（见 3.4.3）

#### 3.4.2 sections（板块结构）

不同版本的板块名称不同，用 `type` 做受控词汇：

**受控 type 值：**

| type | 含义 | 出现版本 |
|------|------|----------|
| `starting_out` | 背景激活/导入 | 外研·孙有中(初中) / 外研·陈琳(高中) |
| `understanding_ideas` | 主题理解（主阅读） | 外研·孙有中(初中) / 外研·陈琳(高中) |
| `using_language` | 功能运用（语法+词汇） | 外研·陈琳(高中) |
| `developing_ideas` | 思维拓展（听说+读写） | 外研·孙有中(初中) / 外研·陈琳(高中) |
| `presenting_ideas` | 观点表达/主题实践 | 外研·孙有中(初中) / 外研·陈琳(高中) |
| `reflection` | 自我评价 | 外研·孙有中(初中) |
| `self_assessment` | 自我评估 | 外研·陈琳(高中) |
| `listening_vocabulary` | 听力+词汇 | 外研·陈琳 |
| `pronunciation_speaking` | 发音+口语 | 外研·陈琳 |
| `reading_vocabulary` | 阅读+词汇 | 外研·陈琳 |
| `language_in_use` | 语言运用 | 外研·陈琳 |
| `module_task` | 模块任务 | 外研·陈琳 |
| `section_a` | Section A（听说） | 人教版 |
| `section_b` | Section B（读写） | 人教版 |
| `grammar_focus` | 语法重点 | 人教版 |
| `reading_thinking` | 阅读与思考 | 人教·高中 |
| `discovering_structures` | 发现有用结构 | 人教·高中 |
| `reading_writing` | 读写结合 | 人教·高中 / 外研·孙有中(初中) |
| `project` | 项目活动 | 人教版 / 外研·孙有中 |
| `listening_speaking` | 听说活动 | 人教·高中 |
| `self_assessment` | 自我评估 | 外研·孙有中(高中) |
| `workbook` | 练习册 | 人教·高中 |
| `starter` | 衔接单元 | 人教·初中 / 外研·孙有中 |
| `revision` | 复习模块 | 外研·陈琳 |

**示例——外研·孙有中七上 Unit 1：**

```json
{
  "sections": [
    { "type": "starting_out", "title": "Starting out", "page": 15 },
    { "type": "understanding_ideas", "title": "Understanding ideas", "page": 17,
      "content": {
        "reading": { "title": "The first lesson", "genre": "记叙文" }
      }
    },
    { "type": "developing_ideas", "title": "Developing ideas", "page": 22,
      "content": {
        "listening": { "topic": "New student problems" },
        "reading_for_writing": { "title": "Dad and Mum's letter", "genre": "书信" }
      }
    },
    { "type": "presenting_ideas", "title": "Presenting ideas", "page": 27,
      "content": { "task": "Make a poster about your first week" }
    },
    { "type": "reflection", "title": "Reflection", "page": 28 }
  ]
}
```

**示例——外研·陈琳八上 Module 1：**

```json
{
  "sections": [
    { "type": "listening_vocabulary", "title": "Unit 1 Listening and vocabulary", "page": 2 },
    { "type": "pronunciation_speaking", "title": "Pronunciation and speaking", "page": 3 },
    { "type": "reading_vocabulary", "title": "Unit 2 Reading and vocabulary", "page": 4 },
    { "type": "language_in_use", "title": "Unit 3 Language in use", "page": 6 },
    { "type": "module_task", "title": "Module task", "page": 7 }
  ]
}
```

**说明：** `content` 是自由结构，存放板块特有信息（阅读课文标题、听力主题、写作任务等）。

#### 3.4.3 language_notes（语言注释）

从教材 "Language notes" 板块提取的重点用法说明：

```json
{
  "language_notes": [
    {
      "phrase": "cut in",
      "meaning": "插嘴，打断别人说话",
      "example_en": "She cut in when we were talking.",
      "example_cn": "我们聊天时，她插了进来。",
      "page": 121
    }
  ]
}
```

### 3.5 陈琳版的特殊处理：Module → Unit 嵌套

陈琳版的顶层是 Module，每个 Module 包含 3 个 Unit。用嵌套结构表示：

```json
{
  "id": "module-1",
  "type": "module",
  "number": 1,
  "title": "How to learn English",
  "page_start": 2,
  "page_end": 9,
  "topic": "学习方法",
  "topic_en": "Learning methods",
  "grammar": [
    { "name": "提建议的表达方式", "name_en": "Ways of giving advice" }
  ],
  "key_vocabulary": [ ... ],
  "sub_units": [
    {
      "number": 1,
      "title": "Unit 1",
      "sections": [
        { "type": "listening_vocabulary", ... },
        { "type": "pronunciation_speaking", ... }
      ]
    },
    {
      "number": 2,
      "title": "Unit 2",
      "sections": [
        { "type": "reading_vocabulary", ... }
      ]
    },
    {
      "number": 3,
      "title": "Unit 3",
      "sections": [
        { "type": "language_in_use", ... },
        { "type": "module_task", ... }
      ]
    }
  ],
  "parallel_articles": []
}
```

**说明：** `sub_units` 只在陈琳版出现。孙有中版和人教版的 `units[]` 直接是扁平列表。消费端根据 `meta.editor` 判断是否需要处理 `sub_units`。

### 3.6 appendix（附录）

```json
{
  "appendix": {
    "communication_bank": {
      "page_start": null,
      "page_end": null,
      "description": "交际用语汇总"
    },
    "language_notes": {
      "page_start": 121,
      "page_end": 134,
      "description": "各单元语言注释"
    },
    "grammar_guide": {
      "page_start": 135,
      "page_end": 154,
      "title": "Guide to the language use",
      "topics": [
        "可数名词和不可数名词",
        "基数词和冠词",
        "一般现在时",
        "人称代词和物主代词",
        "there be 句型",
        "名词所有格",
        "一般过去时",
        "现在进行时",
        "一般将来时"
      ]
    },
    "words_by_unit": {
      "page_start": 155,
      "page_end": 162,
      "description": "按单元排列的单词表"
    },
    "vocabulary_az": {
      "page_start": 165,
      "page_end": 173,
      "description": "A-Z 字母序总词汇表"
    },
    "proper_nouns": {
      "page_start": 163,
      "page_end": 164,
      "description": "专有名词（人名、地名）"
    },
    "pronunciation_guide": {
      "page_start": 174,
      "page_end": 176,
      "description": "发音指南"
    }
  }
}
```

**说明：** `appendix` 记录附录的页码范围和主题列表。不重复存储已在 `units[].grammar` 中提取的内容。这部分主要用于：
- 知道哪些内容已经提取、哪些还没有
- 生成辅助学习材料时定位参考

---

## 4. 版本差异速查表

| 特征 | 外研·孙有中(初中) | 外研·陈琳(初中) | 外研·陈琳(高中) | 人教·初中 | 人教·高中 |
|------|-------------|-----------|-----------|-----------|-----------|
| 顶层组织 | Unit (6+Starter) | Module (12+2 Revision) | Unit (6) | Unit + Starter | Unit + Welcome |
| 子结构 | 5阶段循环 | 3个Unit/Module | 5阶段循环 | Section A/B | 多板块混合 |
| 语法位置 | 附录+课内嵌入 | 附录+课内 | 课内 Using language | 课内 Grammar Focus + 附录 | 课内 Discovering Structures + 附录 |
| 单词表格式 | 按Unit + A-Z | 按Module + A-Z | 按Unit + A-Z | 按Unit + A-Z + 小学复习 | 按Unit + A-Z |
| 目录页 | 扁平列表 | Scope & sequence 表 | Scope & sequence 表 | CONTENTS 页 | CONTENTS 页 |
| JSON nesting | `units[]` 扁平 | `units[]` 含 `sub_units[]` | `units[]` 扁平 | `units[]` 扁平 | `units[]` 扁平 |
| 需要特殊字段 | `sections[]` 5阶段 | `sub_units[]` + `type: "module"` | `sections[]` 5阶段 | `sections[]` A/B | `sections[]` 多板块 |

---

## 5. 提取工作流

### Phase 1: 全量提取（当前阶段）

对 19 本 PDF 逐本运行提取脚本：

1. **目录页提取** → 填充 `toc[]`
2. **单元结构提取** → 填充 `units[].sections[]`
3. **语法点提取** → 填充 `units[].grammar[]`
4. **单词表提取** → 填充 `units[].key_vocabulary[]` + `units[].key_phrases[]`
5. **语言注释提取** → 填充 `units[].language_notes[]`
6. **附录页码提取** → 填充 `appendix`

### Phase 2: 数据清洗

- 音标格式标准化
- CEFR 级别标注（结合 vocabulary/cefr/ 词表交叉比对）
- 语法点中英文对齐

### Phase 3: 平行文章生成

- 基于 `units[]` 的 topic + grammar + key_vocabulary
- AI 生成平行阅读文章（不使用教材原文）
- 填入 `parallel_articles[]`

---

## 6. 与旧格式的迁移

旧 JSON 格式（flat）→ 新格式（带 sections/language_notes）的字段映射：

| 旧字段 | 新字段 | 说明 |
|--------|--------|------|
| `unit` | `number` | 数字序号 |
| `title` | `title` | 不变 |
| `topic` | `topic` | 不变 |
| `topic_en` | `topic_en` | 不变 |
| `grammar[]` (string) | `grammar[]` (object) | 升级为 `{name, name_en, details}` |
| `grammar_en[]` | 合入 `grammar[].name_en` | 不再单独字段 |
| `key_vocabulary[]` (string) | `key_vocabulary[]` (object) | 升级为 `{word, pos, phonetic, cn, page}` |
| `cefr_level` | `cefr_level` | 不变 |
| `skills[]` | `sections[].type` | 从扁平字段变为结构化板块 |
| `parallel_articles[]` | `parallel_articles[]` | 不变 |
| _(无)_ | `key_phrases[]` | **新增** |
| _(无)_ | `sentence_patterns[]` | **新增** |
| _(无)_ | `language_notes[]` | **新增** |
| _(无)_ | `sections[]` | **新增** |
| _(无)_ | `meta.editor` | **新增**（区分陈琳/孙有中） |

旧文件将全部删除并用真实数据替换，无需做格式迁移。
