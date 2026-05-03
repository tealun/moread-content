# moread-content

> 开源的英语教学内容资源库，面向中国初高中学习者。
> 提供词典、分级词表、考纲词库、教材同步文章、分级阅读素材。
> 所有内容同时提供 JSON 和 SQL（PostgreSQL）两种格式。
> MIT 许可证，可商用。

---

## 目录结构

```
moread-content/
├── dictionary/                ← 英语词典（源自 ECDICT + 自行补充）
│   ├── README.md              ← 字段说明、数据来源
│   ├── dictionary.json/       ← JSON 版本（按首字母分文件：a.json, b.json, ...）
│   └── dictionary.sql         ← PostgreSQL 导入脚本
│
├── vocabulary/                ← 分级词表 + 考纲词库
│   ├── README.md
│   ├── cefr/                  ← CEFR 官方分级
│   │   ├── a1.json
│   │   ├── a2.json
│   │   ├── b1.json
│   │   ├── b2.json
│   │   ├── c1.json
│   │   └── c2.json
│   ├── exam/                  ← 中国考试考纲
│   │   ├── zhongkao.json      ← 中考考纲词汇（~1600词）
│   │   └── gaokao.json        ← 高考考纲词汇（~3500词）
│   └── combined/              ← 交叉索引（词 → CEFR等级 + 是否考纲）
│       └── word-levels.json
│
├── textbook/                  ← 教材同步库（按课文主题自创平行文章）
│   ├── README.md              ← 教材版本说明、使用方法
│   ├── renjiao/               ← 人教版（PEP）
│   │   ├── README.md          ← 覆盖范围说明
│   │   ├── grade7/
│   │   │   ├── unit01.json    ← 每单元一个文件
│   │   │   └── ...
│   │   ├── grade8/
│   │   └── grade9/
│   ├── waiyan/                ← 外研版（未来扩展）
│   └── textbook.sql           ← 全量 PostgreSQL 导入脚本
│
├── reading/                   ← 分级阅读素材库
│   ├── README.md              ← 素材来源、难度标注说明
│   ├── a2/
│   ├── b1/
│   └── b2/
│
└── tools/                     ← 构建/导入工具
    ├── import-ecdict.ts       ← ECDICT CSV → JSON + SQL
    ├── build-indexes.ts       ← 构建交叉索引
    ├── sync-to-db.ts          ← 一键同步到 PostgreSQL
    └── generate-textbook.ts   ← AI 生成教材平行文章的 prompt + 流程
```

---

## 各模块详细设计

### 1. 词典 dictionary/

**数据来源**：ECDICT（skywind3000/ECDICT，MIT 许可）+ 自行补充的例句和用法

**JSON 格式**（按首字母分文件，避免单文件过大）：

```json
// dictionary/a.json
{
  "abandon": {
    "phonetic": "/əˈbændən/",
    "pos": ["v.", "n."],
    "definitions": [
      { "pos": "v.", "en": "to leave completely and forever", "zh": "放弃；抛弃" },
      { "pos": "n.", "en": "a feeling of being wild or out of control", "zh": "放纵" }
    ],
    "examples": [
      { "en": "They had to abandon the car in the snow.", "zh": "他们不得不把车丢在雪地里。" }
    ],
    "frequency": 3000,
    "cefr": "B1",
    "forms": ["abandoned", "abandoning", "abandonment"]
  }
}
```

**SQL 版本**：`dictionary.sql`，单表 `dictionary`，字段同上。

---

### 2. 分级词表 vocabulary/

**数据来源**：
- CEFR 词表：vocabulary.englishprofile.org
- 中考考纲：教育部《义务教育英语课程标准》
- 高考考纲：教育部《普通高中英语课程标准》

**JSON 格式**：

```json
// vocabulary/cefr/a2.json
{
  "level": "A2",
  "word_count": 1500,
  "words": [
    { "word": "accident", "pos": "n.", "zh": "事故" },
    { "word": "advice", "pos": "n.", "zh": "建议" }
  ]
}

// vocabulary/exam/gaokao.json
{
  "exam": "高考",
  "year": 2024,
  "word_count": 3500,
  "words": [
    { "word": "abandon", "zh": "放弃", "frequency_rank": 1234 }
  ]
}

// vocabulary/combined/word-levels.json（交叉索引）
{
  "abandon": { "cefr": "B1", "zhongkao": false, "gaokao": true },
  "ability": { "cefr": "A2", "zhongkao": true, "gaokao": true }
}
```

**不提供 SQL 版本**。词表数据量小（几千条），内存加载即可。

---

### 3. 教材同步库 textbook/

**核心思路**：不使用教材原文（版权问题），按教材每单元的**主题和知识点**自创平行文章。

**JSON 格式**：

```json
// textbook/renjiao/grade7/unit01.json
{
  "publisher": "人教版",
  "grade": 7,
  "unit": 1,
  "title": "My name's Gina",
  "theme": "自我介绍与个人信息",
  "grammar_points": ["be动词", "物主代词", "一般现在时"],
  "key_vocabulary": ["name", "nice", "meet", "too", "your", "phone", "number"],
  "articles": [
    {
      "id": "r7u1-01",
      "title": "A Letter to a Pen Pal",
      "level": "A1",
      "word_count": 120,
      "content": "Dear pen pal, My name is Li Ming...",
      "vocabulary": ["name", "year", "old", "live", "like"],
      "grammar_focus": "be动词 + 物主代词",
      "exercises": [
        {
          "type": "fill_blank",
          "question": "My name ___ Li Ming.",
          "answer": "is",
          "grammar": "be动词"
        }
      ]
    }
  ]
}
```

**SQL 版本**：`textbook.sql`，表 `textbook_units` + `textbook_articles` + `textbook_exercises`。

**生成方式**：AI 根据教材每单元的主题 + 语法点 + 生词表 → 生成 2-3 篇平行文章 + 练习题 → 人工审核后入库。

---

### 4. 阅读素材库 reading/

**只提供 JSON 版本**。阅读素材是按需取用的，不需要入库。

```json
// reading/a2/001-family-dinner.json
{
  "id": "a2-001",
  "title": "The Family Dinner",
  "level": "A2",
  "tags": ["family", "daily-life", "food"],
  "source": "original",
  "word_count": 180,
  "content": "Every Sunday, our whole family has dinner together...",
  "vocabulary": [
    { "word": "recipe", "zh": "食谱" },
    { "word": "delicious", "zh": "美味的" }
  ],
  "questions": [
    {
      "type": "choice",
      "question": "Who usually cooks the dinner?",
      "options": ["Mom", "Dad", "Grandma", "The writer"],
      "answer": 2
    }
  ]
}
```

---

## 格式策略总结

| 内容 | JSON | SQL | 理由 |
|------|------|-----|------|
| 词典 | ✅ | ✅ | 77万条，需要索引查询 |
| 分级词表 | ✅ | ❌ | 几千条，内存加载 |
| 考纲词库 | ✅ | ❌ | 同上 |
| 教材同步库 | ✅ | ✅ | 需要按教材+年级+单元关联查询 |
| 阅读素材 | ✅ | ❌ | 按需取用，不需要入库 |

---

## 集成方式

### 直接使用 JSON

```javascript
import a2Words from 'moread-content/vocabulary/cefr/a2.json'
import unit01 from 'moread-content/textbook/renjiao/grade7/unit01.json'
```

### 导入 PostgreSQL

```bash
# 通过 DATABASE_URL 环境变量指定目标库
npx ts-node tools/sync-to-db.ts --only dictionary   # 只同步词典
npx ts-node tools/sync-to-db.ts --only textbook      # 只同步教材
npx ts-node tools/sync-to-db.ts --all                # 全量同步
```

sync 脚本使用标准 `pg` 客户端，兼容任何 PostgreSQL 实例。

---

## 内容格式约定

- 所有文本文件使用 **UTF-8** 编码
- JSON 使用 **2 空格缩进**，便于 Git diff
- 时间字段统一 **ISO 8601** 格式
- 等级标签统一使用 **CEFR 标准**（A1/A2/B1/B2/C1/C2）
- 中国考试等级映射：中考 ≈ A2-B1，高考 ≈ B1-B2

---

## 开源策略

- **MIT 许可证**，可商用
- 词典部分基于 ECDICT（MIT），允许商用
- 教材同步库是**自创内容**（按主题平行创作），不涉及教材原文版权
- 欢迎社区贡献（补充其他教材版本、更多阅读素材、其他语言版本）

---

## 建设优先级

| 阶段 | 内容 | 工作量 | 依赖 |
|------|------|-------|------|
| **阶段 1** | 词典导入 + CEFR/考纲词表 | 2-3 天 | ECDICT + englishprofile.org |
| **阶段 2** | 教材同步库（七年级起） | 5-7 天 | 阶段 1 的词表 + AI 生成管道 |
| **阶段 3** | 阅读素材库 + 定期更新管道 | 3-5 天 | 阶段 1 的分级标准 |

---

## 数据来源与版权声明

| 数据 | 来源 | 许可证 |
|------|------|--------|
| 词典基础数据 | [ECDICT](https://github.com/skywind3000/ECDICT) | MIT |
| CEFR 词表 | [English Profile](https://vocabulary.englishprofile.org/) | 整理加工 |
| 中考/高考考纲 | 教育部课程标准文档 | 公开信息整理 |
| 教材同步文章 | AI 自创 + 人工审核 | MIT（本仓库） |
| 阅读素材 | AI 生成 + 改写 | MIT（本仓库） |
