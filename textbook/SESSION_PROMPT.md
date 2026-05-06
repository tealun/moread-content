# 教材数据提取 — 单册独立会话提示词

## 1. 任务目标

从**单一册教材**的 PDF 文件（或多页图片）中提取全部结构化数据，输出为符合项目规范的 JSON 文件。

**只处理一册，不多不少。** 完成后立即结束本会话。

---

## 2. 项目背景

- 项目根目录：`F:\Github\moread-content`
- 教材数据目录：`textbook/`
- 设计规格：`textbook/SPEC.md`（了解完整 JSON Schema）
- 提取脚本参考：`tools/extract_pep.py`, `tools/extract_pep_v2.py`, `tools/extract_chenlin.py`, `tools/extract_textbook.py`

---

## 3. 用户指令格式

用户只需提供一句话：

> **"请处理 `<目录路径>` 下的教材文件。"**

例如：
- `请处理 textbook/pdfs/pep_grade7_up/ 下的教材文件。`
- `请处理 temp/fltrp_sun_grade8_down/ 下的教材文件。`

目录中可以是：
- 一个完整的 PDF 文件（如 `教材.pdf`）
- 多页 PDF 文件（按页码命名，如 `page_001.pdf`, `page_002.pdf`）
- 图片文件（如 `001.png`, `002.png`）

---

## 4. 自动推断规则

根据目录名称自动推断教材信息：

| 目录名特征 | 推断规则 |
|-----------|---------|
| 含 `pep` | publisher="人教版（PEP）", publisher_code="pep", editor="pep", editor_name=null |
| 含 `fltrp` 或 `外研` | publisher="外研版（FLTRP）", publisher_code="fltrp" |
| 含 `sun` 或 `孙有中` | editor="sun", editor_name="孙有中", standard="2022年版课程标准" |
| 含 `chen` 或 `陈琳` | editor="chen", editor_name="陈琳" |
| 含 `grade7` 或 `七年级` | grade=7 |
| 含 `grade8` 或 `八年级` | grade=8 |
| 含 `grade9` 或 `九年级` | grade=9 |
| 含 `up` 或 `上册` | semester="up" |
| 含 `down` 或 `下册` | semester="down" |
| 含 `full` 或 `全一册` | semester="full" |
| 含 `required` 或 `必修` | level="senior" |
| 含 `junior` 或 `初中` | level="junior" |
| 含 `senior` 或 `高中` | level="senior" |

**输出 JSON 路径规则**：根据推断结果自动确定，如 `textbook/pep/junior/grade7_up.json`

如果目录名信息不足或推断有歧义，向用户确认后再继续。

---

## 5. 输出 JSON 结构

### 5.1 顶层结构

```json
{
  "meta": { ... },
  "toc": [ ... ],
  "units": [ ... ],
  "appendix": { ... }
}
```

### 5.2 meta（元数据）

```json
{
  "publisher": "人教版（PEP）",
  "publisher_code": "pep",
  "editor": "pep",
  "editor_name": null,
  "standard": "2022年版课程标准",
  "level": "junior",
  "grade": 7,
  "semester": "up",
  "title": "七年级上册",
  "pages": 178,
  "source_pdf": "xxx.pdf",
  "extracted_at": "2026-05-05",
  "confidence": "verified"
}
```

### 5.3 toc（目录概览）

```json
[
  {
    "id": "starter",
    "type": "starter",
    "title": "Welcome to junior high!",
    "page": 2,
    "grammar_preview": ["nouns", "numbers"]
  },
  {
    "id": "unit-1",
    "type": "unit",
    "number": 1,
    "title": "A new start",
    "page": 14,
    "topic": "初中生活、第一课",
    "topic_en": "Junior high life",
    "grammar_preview": ["Pronouns"],
    "cefr_level": "A1"
  }
]
```

### 5.4 units（详细单元数据）

```json
[
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
        "name": "人称代词",
        "name_en": "Personal pronouns",
        "details": "主格与宾格的区分"
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
]
```

### 5.5 版本差异（关键！）

| 版本 | 顶层组织 | 特殊结构 |
|------|---------|---------|
| **人教版 (pep)** | Unit + Starter Unit | `sections[]` 含 `section_a`, `section_b`, `grammar_focus`, `project` |
| **外研·孙有中 (sun)** | Unit + Starter | `sections[]` 含 `starting_out`, `understanding_ideas`, `developing_ideas`, `presenting_ideas`, `reflection` |
| **外研·陈琳·初中 (chen)** | **Module** → 3个Unit | `units[]` 中每个元素含 `type: "module"` 和 **`sub_units[]`** 嵌套 |
| **外研·陈琳·高中 (chen)** | Unit | `sections[]` 同孙有中版 |

### 5.6 sections type 受控词汇

| type | 含义 | 出现版本 |
|------|------|---------|
| `starting_out` | 背景激活 | 外研·孙有中 / 外研·陈琳(高中) |
| `understanding_ideas` | 主题理解（主阅读） | 外研·孙有中 / 外研·陈琳(高中) |
| `using_language` | 功能运用 | 外研·陈琳(高中) |
| `developing_ideas` | 思维拓展 | 外研·孙有中 / 外研·陈琳(高中) |
| `presenting_ideas` | 观点表达 | 外研·孙有中 / 外研·陈琳(高中) |
| `reflection` | 自我评价 | 外研·孙有中(初中) |
| `self_assessment` | 自我评估 | 外研·陈琳(高中) |
| `listening_vocabulary` | 听力+词汇 | 外研·陈琳(初中) |
| `pronunciation_speaking` | 发音+口语 | 外研·陈琳(初中) |
| `reading_vocabulary` | 阅读+词汇 | 外研·陈琳(初中) |
| `language_in_use` | 语言运用 | 外研·陈琳(初中) |
| `module_task` | 模块任务 | 外研·陈琳(初中) |
| `section_a` | Section A（听说） | 人教版 |
| `section_b` | Section B（读写） | 人教版 |
| `grammar_focus` | 语法重点 | 人教版 |
| `reading_thinking` | 阅读与思考 | 人教·高中 |
| `discovering_structures` | 发现有用结构 | 人教·高中 |
| `reading_writing` | 读写结合 | 人教·高中 / 外研·孙有中 |
| `project` | 项目活动 | 人教版 / 外研·孙有中 |
| `listening_speaking` | 听说活动 | 人教·高中 |
| `workbook` | 练习册 | 人教·高中 |
| `starter` | 衔接单元 | 人教·初中 / 外研·孙有中 |
| `revision` | 复习模块 | 外研·陈琳 |

### 5.7 appendix 结构

```json
{
  "appendix": {
    "communication_bank": { "page_start": null, "page_end": null, "description": "交际用语汇总" },
    "language_notes": { "page_start": 121, "page_end": 134, "description": "各单元语言注释" },
    "grammar_guide": { "page_start": 135, "page_end": 154, "title": "Guide to the language use", "topics": ["可数名词", "基数词"] },
    "words_by_unit": { "page_start": 155, "page_end": 162, "description": "按单元排列的单词表" },
    "vocabulary_az": { "page_start": 165, "page_end": 173, "description": "A-Z 字母序总词汇表" },
    "proper_nouns": { "page_start": 163, "page_end": 164, "description": "专有名词" },
    "pronunciation_guide": { "page_start": 174, "page_end": 176, "description": "发音指南" }
  }
}
```

---

## 6. 工作流程（按顺序执行）

### Step 1：读取目录并推断信息
- 列出目录下所有文件
- 根据目录名推断教材版本、年级、学期
- 确定输出 JSON 路径
- 向用户确认推断结果，然后开始

### Step 2：分析文件类型
- 如果是完整 PDF → 用 `pdfplumber`/`pymupdf` 处理
- 如果是多页 PDF/图片 → 按文件名排序后逐页处理
- 判断是否为扫描版（尝试提取文字，无文字则为扫描版）
- **如果遇到大量文字乱码（中文无法正确解码）→ 立即转为图片渲染方式处理**

### Step 3：提取目录（toc）
- 找到目录页/CONTENTS/Scope and sequence
- 提取所有单元/模块的标题、页码、主题、语法预览

### Step 4：逐单元提取详细内容
对每个单元：
1. **定位单元范围**：根据 toc 页码找到单元首页和结束页
2. **提取标题和主题**：title、topic、topic_en
3. **提取语法点**：grammar[]（含 name、name_en、details）
4. **提取词汇表**：
   - 找到 "Words and expressions" / "Vocabulary" 页面
   - 注意分栏排版，分别提取左右栏
   - 每个词条：`word`, `pos`, `phonetic`, `cn`, `page`
   - **修正常见 OCR 错误**（如 raser→eraser, hing→thing）
   - **修正中文乱码**（`�?` 等截断字符）
5. **提取重点短语**：key_phrases
6. **提取重点句型**：sentence_patterns
7. **提取板块结构**：sections[]（type、title、page、content）
8. **提取语言注释**：language_notes（如有）

### Step 5：提取附录
- 定位附录区域（PDF 末尾）
- 提取各附录的页码范围、标题、主题列表

### Step 6：核对与修正
- 核对现有 JSON（如有），修正差异
- 检查编码问题（UTF-8 乱码）
- 检查 OCR 错误（缺字母、错字母）
- 检查页码一致性
- 检查单词拼写

### Step 7：生成并写入 JSON
- 组装完整 JSON
- 验证 JSON 有效性
- 使用 UTF-8 编码写入文件
- 汇报统计信息（单元数、词汇数、文件路径）

---

## 7. 常见问题修正清单

核对时重点检查：

| 问题类型 | 示例 |
|---------|------|
| 编码乱码 | `铃（声）；钟（声�?` → `铃（声）；钟（声）` |
| OCR 缺字母 | `raser` → `eraser`, `hing` → `thing`, `arrot` → `carrot`, `oose` → `goose` |
| 中文释义截断 | `准备好（做某事）�?` → `准备好（做某事）的` |
| 元数据缺失 | 补全 `standard`, `pages`, `confidence` 等字段 |

---

## 8. 输出文件路径规则

根据推断的教材信息，自动确定输出路径：

```
textbook/pep/junior/grade7_up.json
textbook/pep/junior/grade7_down.json
textbook/pep/junior/grade8_up.json
textbook/pep/junior/grade8_down.json
textbook/pep/junior/grade9_full.json
textbook/fltrp/junior/sun/grade7_up.json
textbook/fltrp/junior/sun/grade7_down.json
textbook/fltrp/junior/sun/grade8_up.json
textbook/fltrp/junior/sun/grade8_down.json
textbook/fltrp/junior/chen/grade8_up.json
textbook/fltrp/junior/chen/grade8_down.json
textbook/fltrp/junior/chen/grade9_up.json
textbook/fltrp/junior/chen/grade9_down.json
textbook/fltrp/senior/chen/required1.json
textbook/fltrp/senior/chen/required2.json
textbook/fltrp/senior/chen/required3.json
textbook/pep/senior/required1.json
textbook/pep/senior/required2.json
textbook/pep/senior/required3.json
```

---

## 9. 重要原则

1. **结构化数据必须来自真实教材** —— 禁止编造任何内容
2. **宁可多留字段也不要遗漏** —— 先完整提取，后续再瘦身
3. **使用 UTF-8 编码** —— 确保所有中文字符正确存储，无乱码
4. **每处理完一个单元，简要汇报进度**
5. **发现不确定的内容时，停下来询问用户** —— 不要猜测
6. **如果推断信息有误，立即停止并让用户确认**

---

## 10. 开发工作约定

### 10.1 辅助文件管理

- **所有协助创建的临时脚本、调试文件、中间数据，必须统一存放在 `tools/temp/` 目录下**，禁止散落在项目根目录或其他业务目录中。
- 脚本命名应具有描述性，完成后如不再使用可保留在 `tools/temp/` 中作为历史记录，或主动清理。

### 10.2 审计报告管理

- **审计结果必须写入唯一的主审计报告**（如 `tools/temp/audit_report_final.json`），**禁止另外创建独立的审计报告文件**。
- 每次执行修复或补充操作后，应在主审计报告的对应教材条目下的 `execution_log` 数组中**逐条追加执行结果**，包含：
  - `timestamp`：执行时间
  - `action`：执行的操作描述
  - `result`：执行后的状态结果
- 同时更新主报告中的当前状态字段（`missing_*`、`confidence` 等），确保主报告始终反映最新数据质量。

### 10.3 任务结束后清理

- **任务执行完成后，必须对临时文件进行回顾清理**。
- **可复用脚本**（如通用提取器、解析器、审计脚本）保留在 `tools/temp/` 中，供后续任务复用。
- **一次性文件必须及时销毁**：
  - 以 `check_`、`debug_`、`test_`、`dump_` 开头的调试脚本和输出
  - 运行后确认无误的中间文本、JSON、图片
  - 已合并到主报告的旧版审计报告
  - 单页测试提取的文本片段
- **判断标准**：如果该文件只对当前单次任务有用、且任务已验证完成，则立即删除；如果该脚本/数据可能在处理其他册教材时复用，则保留。

### 10.4 PDF 处理工具策略

处理 PDF 时遵循以下原则，**优先使用最优工具提取最准确的内容**：

1. **工具检测与自动安装**：
   - 开始处理前，先检测环境中是否已安装所需的 PDF 处理库（`pdfplumber`、`pymupdf` 等）。
   - **如未安装，立即执行安装**（`pip install pdfplumber pymupdf` 等），不要假设环境已就绪。

2. **文本层 vs 扫描版判断**：
   - 先用 `pdfplumber` 或 `pymupdf` 尝试提取文字。
   - 如果页面返回的文本极少（<50 字符）或完全为空，判定该页为**扫描版/图片版 PDF**。

3. **扫描版处理 —— 图片渲染 + OCR**：
   - 对扫描版页面，使用 `pymupdf` 将页面渲染为高清 PNG 图片。
   - 然后使用 OCR 工具识别文字。推荐工具链：
     - 首选：`paddleocr`（中文识别效果最佳）
     - 次选：`easyocr`
     - 备选：调用系统 `tesseract`
   - **如 OCR 工具未安装，立即执行安装**，不要跳过扫描版页面。
   - 图片渲染参数建议：DPI ≥ 200，确保中文小字清晰可辨。

4. **中文乱码处理**：
   - 如果文本层能提取文字，但中文显示为乱码（如 `�?`、`����` 等截断字符），说明 PDF 内嵌字体编码有问题。
   - **此时应放弃文本层提取，转为图片渲染 + OCR 方式处理**，不要依赖损坏的文本层。

5. **双栏/复杂排版**：
   - 遇到词汇表等双栏排版页面，提取时需按 x 坐标分栏（如 x<240 为左栏，x>240 为右栏），分别处理后再按阅读顺序合并。

---

## 11. 开始工作

用户指令：

> **"请处理 `<目录路径>` 下的教材文件。"**

收到指令后：
1. 列出目录文件
2. 推断教材信息并确认
3. 按 Step 1~7 执行
4. 最终汇报结果
