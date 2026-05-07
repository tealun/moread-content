# Dictionary Architecture Migration: JSON → SQLite

- **Date**: 2026-05-07
- **Type**: Architecture Change (Breaking data format, API compatible)

## Summary
将词典底座从 a-z 分片的 JSON 文件迁移到 ECDICT SQLite 数据库，彻底解决中文释义缺失问题，同时大幅提升查询性能和降低内存占用。

## Problems with Old JSON Approach
1. **中文释义大量缺失**：约 18.2 万条 definition 的 `zh` 字段为空
2. **数据转换质量差**：从 ECDICT CSV 转换到 JSON 时，`definition`（英文）和 `translation`（中文）未正确配对
3. **查询性能低**：每次查词需要加载整个字母 JSON 文件到内存（如 a.json 10MB+）
4. **维护困难**：按字母分片的 JSON 不利于批量更新

## New SQLite Approach

### Data Source
- **Source**: ECDICT (skywind3000) — `ecdict.csv` (770,611 词条)
- **File**: `dictionary/ecdict.db` (SQLite)
- **Coverage**: 768,739 / 770,611 (99.8%) 词条有中文释义

### Schema
```sql
CREATE TABLE stardict (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    word VARCHAR(64) COLLATE NOCASE NOT NULL UNIQUE,
    sw VARCHAR(64) COLLATE NOCASE NOT NULL,
    phonetic VARCHAR(64),
    definition TEXT,
    translation TEXT,
    pos VARCHAR(16),
    collins INTEGER DEFAULT 0,
    oxford INTEGER DEFAULT 0,
    tag VARCHAR(64),
    bnc INTEGER DEFAULT NULL,
    frq INTEGER DEFAULT NULL,
    exchange TEXT,
    detail TEXT,
    audio TEXT
);
```

### Indexes
- `idx_word` — word COLLATE NOCASE（精确查询）
- `idx_sw` — sw COLLATE NOCASE（模糊匹配）
- `idx_frq` — frq ASC（词频排序）

## Changes Made

### Files Modified
- `api/data.py` — 完全重写：
  - 移除 `orjson` JSON 文件加载逻辑和 `_dict_cache`
  - 新增 `sqlite3` 数据库连接和查询逻辑
  - `lookup_word()` — 单条 SQL 查询 + 字段转换
  - `lookup_words_batch()` — 分批 IN 查询
  - `search_prefix()` — LIKE 前缀匹配 + 按词频排序
  - 新增 `_build_definitions()` — 将 ECDICT 多行 definition/translation 解析为 `definitions` 数组
  - 新增 `_parse_exchange()` — 将 exchange 字段解析为中文标签的 forms 数组

### Files Removed
- `dictionary/a.json` ~ `dictionary/z.json`（共 26 个文件，约 133MB）
- `dictionary/*.sql`（共 27 个 SQL 文件，已在前期清理中删除）

### Files Added
- `dictionary/ecdict.db` — SQLite 词典数据库（约 300MB）

### Files Updated
- `dictionary/_meta.json` — 更新为 SQLite 格式元数据

## API Compatibility
✅ **100% 向后兼容**
- `api/dictionary.py` **未做任何修改**
- 返回格式保持不变：
  ```json
  {
    "word": "hello",
    "phonetic": "hə'ləu",
    "pos": ["interj.", "n."],
    "definitions": [
      {"pos": "n.", "en": "an expression of greeting", "zh": ""},
      {"pos": "interj.", "en": "", "zh": "喂, 嘿"}
    ],
    "examples": [],
    "frequency": 2238,
    "cefr": "",
    "forms": ["复数:hellos"],
    "collins": 3,
    "oxford": 1,
    "tag": "zk gk",
    "bnc": 2319
  }
  ```

## Performance Comparison

| Metric | JSON (Old) | SQLite (New) |
|--------|-----------|-------------|
| Single lookup | ~10-50ms (first load) + ~0.1ms (cached) | ~0.19ms |
| Batch (5 words) | ~50-200ms (first load) | ~0.29ms |
| Prefix search | ~10-100ms (遍历内存) | ~0.63ms |
| Memory (dict cache) | ~133MB (全部加载后) | ~0MB (按需查询) |
| Chinese coverage | ~70% | **99.8%** |

## Validation Results
- ✅ `GET /api/dictionary/{word}` — 200 OK, data complete
- ✅ `POST /api/dictionary/batch` — 200 OK, batch lookup works
- ✅ `GET /api/search?q={prefix}` — 200 OK, prefix search works
- ✅ `GET /api/dictionary/nonexistent` — 404 Not Found
- ✅ 99.8% 词条包含中文释义

## Notes
- `cefr` 字段目前为空，因为 ECDICT 无直接 CEFR 标注。未来可通过 `collins` + `oxford` + `tag` 推断或映射。
- `examples` 字段目前为空，ECDICT 的 `detail` 字段含例句 JSON，可后续解析扩展。
- `orjson` 仍在 `requirements.txt` 中保留，因为 `vocabulary/` 模块的 JSON 加载仍需使用。
