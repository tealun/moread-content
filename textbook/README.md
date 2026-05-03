# Textbook Content

教材同步库 —— 按教材每单元的**主题和知识点**自创平行文章（不使用教材原文，避免版权问题）。

## 目录结构

```
textbook/
├── README.md
├── pep/                    ← 人教版（PEP）
│   ├── junior/             ← 初中
│   │   ├── grade7_up.json  ← 七年级上
│   │   ├── grade7_down.json
│   │   ├── grade8_up.json
│   │   ├── grade8_down.json
│   │   └── grade9.json
│   └── senior/             ← 高中
│       ├── required1.json  ← 必修第一册
│       ├── required2.json
│       ├── required3.json
│       ├── selective1.json ← 选择性必修第一册
│       ├── selective2.json
│       ├── selective3.json
│       └── selective4.json
├── fltrp/                  ← 外研版（FLTRP）
│   ├── junior/             ← 初中
│   │   ├── grade7_up.json
│   │   ├── grade7_down.json
│   │   ├── grade8_up.json
│   │   ├── grade8_down.json
│   │   └── grade9_down.json
│   └── senior/             ← 高中
│       ├── required1.json  ← 必修第一册
│       ├── required2.json
│       ├── required3.json
│       ├── selective1.json ← 选择性必修第一册
│       ├── selective2.json
│       ├── selective3.json
│       └── selective4.json
└── textbook.sql            ← PostgreSQL 导入脚本
```

## 教材版本说明

| 版本 | 出版社 | 代码 | 覆盖范围 |
|------|--------|------|----------|
| 人教版 | 人民教育出版社（PEP） | `pep` | 初中 7-9 年级 + 高中必修/选必 |
| 外研版 | 外语教学与研究出版社（FLTRP） | `fltrp` | 初中 7-9 年级 + 高中必修/选必 |

## JSON 格式

每个 JSON 文件对应一本教材（一个学期），包含多个单元：

```json
{
  "publisher": "人教版（PEP）",
  "publisher_code": "pep",
  "level": "senior",
  "grade": 11,
  "semester": "selective1",
  "title": "选择性必修第一册",
  "units": [
    {
      "unit": 1,
      "title": "People of Achievement",
      "topic": "杰出人物、科学成就",
      "topic_en": "People of achievement, scientific discoveries",
      "grammar": ["非限制性定语从句复习"],
      "grammar_en": ["non-restrictive relative clauses review"],
      "key_vocabulary": ["crucial", "vital", ...],
      "cefr_level": "B1",
      "skills": [],
      "parallel_articles": []
    }
  ]
}
```

### 字段说明

- **publisher**: 中文出版社名称
- **publisher_code**: 代码（`pep` / `fltrp`）
- **level**: `junior`（初中）或 `senior`（高中）
- **grade**: 年级数字
- **semester**: 学期标识（`grade7_up`, `required1`, `selective1` 等）
- **title**: 中文书名
- **confidence** *(可选)*: 内容置信度（`estimated` 表示基于公开信息推测）
- **units**: 单元数组
  - **unit**: 单元序号
  - **title**: 单元英文标题
  - **topic**: 主题（中文）
  - **topic_en**: 主题（英文）
  - **grammar**: 语法点（中文）数组
  - **grammar_en**: 语法点（英文）数组
  - **key_vocabulary**: 核心词汇数组
  - **cefr_level**: 单元对应的 CEFR 级别
  - **skills**: 技能训练（预留字段）
  - **parallel_articles**: 平行文章（预留字段，后续 AI 生成填充）

## 使用方法

### 直接使用 JSON

```javascript
import required1 from 'moread-content/textbook/fltrp/senior/required1.json'

for (const unit of required1.units) {
  console.log(`Unit ${unit.unit}: ${unit.title} (${unit.cefr_level})`)
}
```

### 导入 PostgreSQL

```bash
# 使用 tools/sync-to-db.ts 或手动导入
npx ts-node tools/sync-to-db.ts --only textbook
```

## 内容状态

- ✅ PEP 初中 7-9 年级：已有框架数据
- ✅ PEP 高中必修 1-3 + 选必 1-4：已有框架数据
- ✅ FLTRP 初中 7-9 年级：已有框架数据
- ✅ FLTRP 高中必修 1-3 + 选必 1-4：已有框架数据
- ⬜ 平行文章（parallel_articles）：待 AI 生成 + 人工审核
