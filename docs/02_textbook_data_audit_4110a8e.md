# 审计 #02 — moread-content 教材数据 (4110a8e)

**范围**: f9a8414..4110a8e（2个commit）  
**日期**: 2026-05-06  
**验证**: ✅ 所有关键发现已亲自用 Python json.load + grep 验证

---

## 变更概览

| Commit | 说明 | 变更量 |
|--------|------|--------|
| aff6c0b | 七上 language notes/phrases/patterns + SESSION_PROMPT 更新 | +544/-0 (7up) +59(SESSION) |
| 4110a8e | 八上/八下 language_notes/phrases/patterns | +2741/-1399 |

**11 个文件变更，+5,049 / -1,399**

---

## P0 — 严重数据问题（4项）

### P0-1. 八年级 language_notes phrase 字段含中文（12条）
**验证**: ✅ Python 脚本逐条扫描确认  
**详情**:
- **8up** (4条): `句中burn` / `i'$ strange to do sth 这一句型` / `的still 作形容词用` / `此处above all`
- **8down** (8条): `pain 本` / `请注意freeze 作动词时的多重含义` / `mountaineering 是名词` / `此处的 touch 作动词` / `the 24 Solar Terms 表示"二十四节气"。solar作形容词` / `long to do sth 中long 作动词` / `the Flaming Mountains 在此处指的是"火焰山"` / `lie在此处作动词`
**根因**: AI 提取时把教学说明（"此处above all意为…"）混入了 phrase 字段  
**修复**: 需人工逐条修正 phrase 为纯英文短语

### P0-2. 八年级 language_notes meaning 字段尾部引号残留（25条）
**验证**: ✅ 8up 10/32 条 + 8down 15/36 条 meaning 以 `"` 结尾  
**示例**: `'只要"'` / `'到处\n各处;  零散地"'` / `'拒绝做"'`  
**根因**: OCR/AI 提取时中文引号残留  
**修复**: 批量 trim 尾部 `"` 和 `\\"`

### P0-3. 七下全部 270/285 条音标缺斜杠
**验证**: ✅ Python 扫描确认 270/285 条 phonetic 不以 `/` 包裹  
**示例**: `'ɪkˈsaɪtɪŋ'` 应为 `'/ɪkˈsaɪtɪŋ/'`  
**其他册**: 7up/8up/8down 格式正常（有斜杠）  
**修复**: 批量添加 `/` 前后缀

### P0-4. 七上 unit-5 两条 language_notes 数据严重错位
**详情**:
- note#9: phrase=`water（涨潮）` meaning=`非常高兴的，相当满足的` — 完全不匹配，example 全空
- note#10: phrase=`as dead as a dodo也是一个英文习语` — phrase 包含中文说明

---

## P1 — 数据不完整（7项）

### P1-1. grammar.details 18个 unit 全部为空
**范围**: 7down(6/6) + 8up(6/6) + 8down(6/6)，7up 的 starter 也 4 条空  
**影响**: 语法板块无详情说明

### P1-2. key_phrases 八年级覆盖率低
- 8up: 仅 2/6 units 有（unit-2×1, unit-4×5）
- 8down: 仅 3/6 units 有（unit-4×1, unit-5×1, unit-6×2）
- 7up/7down: 100% 覆盖

### P1-3. sentence_patterns 含填空题残片（~11条）
**示例**: 8up `You can't always hide your 3 ___ _` / 8down `Don't let peer pressure 6 ____ you.`  
**根因**: 从练习册直接 OCR 提取，非句型模板

### P1-4. 七上 4 条垃圾词汇 `word='Words'`
**验证**: ✅ unit-2/3/5/6 各一条，cn=`and expressions`  
**根因**: 页眉标题 "Words and expressions" 被误收录

### P1-5. 七上多个词汇缺 pos（词性）
- starter ~10个 / unit-1 ~8个 / unit-2 ~6个 / unit-5 ~11个

### P1-6. 八下 language_notes 19%缺 example_en，28%缺 example_cn

### P1-7. 七上部分 sentence_patterns 过于简短（如 `I have …` / `So…`）

---

## P2 — 轻微问题（4项）

### P2-1. `.claude/settings.local.json` 包含本地路径
**建议**: 加入 .gitignore

### P2-2. 三份 tasker SKILL.md 重复（.claude/.github/.kimi）
**说明**: 多平台部署，功能正常，但确认是否适合教材数据仓库

### P2-3. SESSION_PROMPT.md 新增开发约定章节
**结论**: ✅ 内容合理

### P2-4. 七上 language_notes 部分用 `…`（中文省略号）
**建议**: 统一为 `...`（英文省略号）

---

## 数据统计（验证后）

| 册 | Units | Vocab | Grammar | Language Notes | Key Phrases | Sentence Patterns | Sections |
|----|-------|-------|---------|----------------|-------------|-------------------|----------|
| 7上 | 7 | 313 | 11 | 43 (6/7 units) | 29 (7/7) | 72 (7/7) | 34 (7/7) |
| 7下 | 6 | 285 | 6 | 12 (6/6) | 35 (6/6) | 36 (6/6) | 30 (6/6) |
| 8上 | 6 | 275 | 6 | 32 (6/6) | 6 (2/6) ⚠️ | 78 (6/6) | 30 (6/6) |
| 8下 | 6 | 183 | 6 | 36 (6/6) | 4 (3/6) ⚠️ | 88 (6/6) | 30 (6/6) |

---

## 总结

| 级别 | 数量 | 关键问题 |
|------|------|----------|
| P0 | 4 | phrase中文混入(12条)、引号残留(25条)、音标缺斜杠(270条)、数据错位(2条) |
| P1 | 7 | grammar空(18unit)、phrases缺失(7unit)、填空残片(11条)、垃圾词(4条) |
| P2 | 4 | 本地路径、skill重复、SESSION OK、省略号格式 |

**修复优先级建议**:
1. 🔴 批量修 7down 音标格式 + 清理 8up/8down phrase 中文混入 + meaning 引号残留
2. 🟡 删除 "Words" 垃圾条目 + 替换填空题句型
3. 🟢 grammar.details 补充（需 AI 二次提取）+ key_phrases 补全
