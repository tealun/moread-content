# 04 内容质量审计（离线、只读）

`tools/audit_content.py` 对 **词库 `vocabulary/`、词典 `dictionary/overlay.db`、教材词表 `textbook/`** 做规则审计。

- **只读**：overlay.db 以 SQLite `mode=ro&immutable=1` 打开，不产生 `-wal/-shm`，不修改任何数据文件。
- **离线**：不联网、不调用 AI。可选依赖 `cmudict`（`requirements.txt` 已包含）用于音节数和拼写交叉校验。
- **基线**：`tools/audit_baseline.json` 记录每项问题计数和字段覆盖率。

## 运行

```bash
pip install cmudict            # 或 pip install -r requirements.txt
python tools/audit_content.py                                   # 与基线比对
python tools/audit_content.py --report /tmp/audit.md --issues-csv /tmp/issues.csv   # 输出报告/逐条问题
python tools/audit_content.py --update-baseline                 # 修复后下调基线
```

退出码：`0` = 不劣于基线；`1` = 有任一问题计数 **高于** 基线，或任一字段覆盖率 **低于** 基线（输出 `REGRESSION ...` 行）。

## 规则

1. **计数只能降，不能升。** 任何改动 `dictionary/`、`vocabulary/`、`textbook/` 的 PR 都必须通过审计。
2. 修复类 PR 在同一个 PR 里运行 `--update-baseline`，把基线下调到新的更低计数，并在 PR 描述里贴前后对比。
3. 如果确实需要接受某项计数上升（例如新增词库带来新的“overlay 缺失”），必须在 PR 描述中单独说明原因后再更新基线。
4. 所有数据改动走 PR，由维护者审核后合并；**main 分支推送会自动部署到生产**（见 `.github/workflows/deploy-content.yml`）。
5. 需要 AI 的修复（义项重配、补中文、CEFR 重分级等）不在本脚本范围内，且不得自动 commit/push。

## 检查项

| 类别 | 检查 |
|---|---|
| 结构 | 各 JSON 字段可解析；`index.json` 计数 = 文件实际词数；README 词库数/总词数同步；无未登记的词库文件 |
| 词典 | 字段覆盖率；词性格式（ECDICT 比例 `n:40/v:60`、字母码 `j./r./i.`）；英文释义 WordNet 词性前缀泄漏；Webster 1913 原文；空中文义项；例句缺词头/中英颠倒/疑似截断；同义=反义、自指、占位词；词形垃圾值（ECDICT exchange 代码残留、`…ss` 复数）；IPA 非标准字符、送气符、单音节重音、eSpeak 风格重音；音节与拼写/CMU 不一致；audit_pass≠2 的隐藏条目 |
| 词库 | 重复、大小写、空白、非词垃圾、不在 CMU 的疑似拼写错误、overlay 缺失、少儿敏感词 |
| 教材 | 疑似 OCR 首字母丢失、音标污染、平行文章数量 |

`info_*` 开头的计数是信息项（例如未解决的音标冲突），同样受基线约束。

## CI（可选，需手动添加）

建议新增 `.github/workflows/content-audit.yml`，在 `pull_request` 时运行审计（只读、无 secrets、不部署），报告写入 Job Summary。该文件未随本 PR 提交（自动化账号的 token 没有 `workflow` 权限），维护者可直接复制以下内容创建：

```yaml
# 内容质量审计：仅在 PR 上运行，只读、离线、无 secrets、不部署
name: Content Audit

on:
  pull_request:
    paths:
      - "dictionary/**"
      - "vocabulary/**"
      - "textbook/**"
      - "tools/audit_content.py"
      - "tools/audit_baseline.json"
      - "README.md"
      - ".github/workflows/content-audit.yml"

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: 安装依赖
        run: pip install cmudict
      - name: 审计（计数不得高于基线）
        run: python tools/audit_content.py --report "$RUNNER_TEMP/audit.md"
      - name: 写入 Job Summary
        if: always()
        run: test -f "$RUNNER_TEMP/audit.md" && head -c 900000 "$RUNNER_TEMP/audit.md" >> "$GITHUB_STEP_SUMMARY" || true
```

## 规则修复 `tools/fix_rules.py`

确定性、幂等、无网络、无 AI、不 commit/push。只做格式修复（词性规范化、去 WordNet 词性前缀、词形垃圾值清理与结构化、IPA 送气符/单音节重音、音标来源去重、README 计数），不改 CEFR、不重配义项、不删词条、不动词库词表。

```bash
pip install cmudict
python tools/fix_rules.py --dry-run                                   # 只统计
python tools/fix_rules.py --log /tmp/fix.jsonl \
       --summary tools/fix_logs/fix_rules-YYYYMMDD.summary.json       # 写库 + 变更日志
python tools/audit_content.py --update-baseline                       # 计数下降后更新基线
```

完整逐条变更日志（JSONL，约 9MB）不入库；摘要（规则计数 + 每条规则前 20 例）提交在 `tools/fix_logs/`。
