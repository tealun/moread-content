"""数据加载层 — 索引、词库、词典的 SQLite 查询层

查询优先级：overlay.db（主力）→ ecdict.db（兜底）
"""

import sqlite3
import re
import json
from pathlib import Path
import pyphen

_hyphen_dic = pyphen.Pyphen(lang='en_US')

BASE_DIR = Path(__file__).resolve().parent.parent
VOCAB_DIR = BASE_DIR / "vocabulary"
DICT_DB = BASE_DIR / "dictionary" / "ecdict.db"
OVERLAY_DB = BASE_DIR / "dictionary" / "overlay.db"

_index_cache = None
_pack_cache: dict = {}
_db_conn = None
_overlay_conn = None


def _get_db() -> sqlite3.Connection:
    """获取 ECDICT SQLite 数据库连接（单例）"""
    global _db_conn
    if _db_conn is None:
        _db_conn = sqlite3.connect(str(DICT_DB), check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
    return _db_conn


def _get_overlay() -> sqlite3.Connection | None:
    """获取 overlay 数据库连接（单例），文件不存在返回 None"""
    global _overlay_conn
    if _overlay_conn is None:
        if OVERLAY_DB.exists():
            _overlay_conn = sqlite3.connect(str(OVERLAY_DB), check_same_thread=False)
            _overlay_conn.row_factory = sqlite3.Row
    return _overlay_conn


def _load_json(path: Path):
    import orjson
    with open(path, "rb") as f:
        return orjson.loads(f.read())


def get_index() -> list:
    global _index_cache
    if _index_cache is None:
        _index_cache = _load_json(VOCAB_DIR / "index.json")
    return _index_cache


def get_pack(pack_id: str) -> dict | None:
    if pack_id in _pack_cache:
        return _pack_cache[pack_id]
    for entry in get_index():
        if entry["id"] == pack_id:
            data = _load_json(VOCAB_DIR / entry["file"])
            _pack_cache[pack_id] = data
            return data
    return None


def _parse_pos_prefix(line: str) -> tuple[str, str]:
    """从行首提取词性前缀，如 'n. content' -> ('n.', 'content')"""
    line = line.strip()
    if not line:
        return ("", "")
    # 匹配词性前缀：a-z 字母 + . + 可选空格
    m = re.match(r'^([a-z]+\.\s*)(.*)$', line, re.IGNORECASE)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return ("", line)


# 词性别名映射：不同来源可能使用不同的词性缩写
_POS_ALIASES = {
    "a": ["s"],        # adjective / substantive
    "s": ["a"],
    "r": ["adv"],      # adverb
    "adv": ["r"],
    "v": ["vt", "vi"], # verb
    "vt": ["v", "vi"],
    "vi": ["v", "vt"],
    "n": ["nn"],       # noun
    "nn": ["n"],
}


def _build_definitions(definition_text: str | None, translation_text: str | None) -> list[dict]:
    """将 ECDICT 的多行 definition 和 translation 解析为 definitions 数组"""
    def_lines = []
    if definition_text:
        for line in definition_text.strip().split('\\n'):
            pos, content = _parse_pos_prefix(line)
            if content:
                def_lines.append((pos, content))

    trans_lines = []
    if translation_text:
        for line in translation_text.strip().split('\\n'):
            pos, content = _parse_pos_prefix(line)
            if content:
                trans_lines.append((pos, content))

    definitions = []
    used_trans = set()

    # 先按词性匹配英文释义和中文释义
    for pos, en in def_lines:
        best_idx = -1
        for i, (tpos, zh) in enumerate(trans_lines):
            if i in used_trans:
                continue
            # 词性匹配规则：去掉末尾的 '.' 后比较，支持别名映射
            pos_base = pos.rstrip('.')
            tpos_base = tpos.rstrip('.')
            if not tpos_base or not pos_base:
                continue
            # 直接匹配、前缀匹配、别名匹配
            matched = (
                tpos_base == pos_base
                or tpos_base.startswith(pos_base)
                or pos_base.startswith(tpos_base)
                or tpos_base in _POS_ALIASES.get(pos_base, [])
                or pos_base in _POS_ALIASES.get(tpos_base, [])
            )
            if matched:
                best_idx = i
                break
        if best_idx >= 0:
            definitions.append({"pos": pos, "en": en, "zh": trans_lines[best_idx][1]})
            used_trans.add(best_idx)
        else:
            definitions.append({"pos": pos, "en": en, "zh": ""})

    # 第二轮：为缺失 zh 的 definition 补充同词性的 translation（共享 translation）
    for idx, d in enumerate(definitions):
        if d["zh"]:
            continue
        # 找同词性且已匹配的 translation，复制过来
        for i, (tpos, zh) in enumerate(trans_lines):
            if i not in used_trans:
                continue
            pos_base = d["pos"].rstrip('.')
            tpos_base = tpos.rstrip('.')
            if not tpos_base or not pos_base:
                continue
            matched = (
                tpos_base == pos_base
                or tpos_base.startswith(pos_base)
                or pos_base.startswith(tpos_base)
                or tpos_base in _POS_ALIASES.get(pos_base, [])
                or pos_base in _POS_ALIASES.get(tpos_base, [])
            )
            if matched:
                d["zh"] = zh
                break

    # 剩余未匹配的中文释义
    for i, (tpos, zh) in enumerate(trans_lines):
        if i not in used_trans:
            definitions.append({"pos": tpos, "en": "", "zh": zh})

    return definitions


def _parse_pos(pos_text: str | None) -> list[str]:
    """解析 pos 字段为数组，如 'art./n.' -> ['art.', 'n.']"""
    if not pos_text:
        return []
    # ECDICT 的 pos 通常用 / 或 , 分隔
    return [p.strip() for p in re.split(r'[/,]', pos_text) if p.strip()]


def _parse_exchange(exchange_text: str | None) -> list[str]:
    """解析 exchange 字段为 forms 数组"""
    if not exchange_text:
        return []
    forms = []
    code_map = {
        "p": "过去分词",
        "d": "过去式",
        "i": "现在分词",
        "3": "第三人称单数",
        "s": "复数",
        "r": "比较级",
        "t": "最高级",
        "0": "原型",
        "1": "原型变形",
    }
    for part in exchange_text.split("/"):
        if ":" in part:
            code, form = part.split(":", 1)
            label = code_map.get(code, code)
            forms.append(f"{label}:{form}")
        else:
            forms.append(part)
    return forms


def _jl(raw: str | None, empty_sentinel: str, default):
    """安全的 json.loads：raw 为空或等于哨兵值时返回 default，解析失败也返回 default。"""
    if not raw or raw == empty_sentinel:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return default


_IPA_VOWELS = "aeiouæɑɒɔəɜɪiʊuɛɐɚɝeøœɶɘɵɞɤɯyɨ"


def _normalize_ipa_stress(phonetic: str | None) -> str:
    """Fix stress marks placed after an initial consonant cluster."""
    if not phonetic:
        return ""

    text = phonetic.strip()
    prefix = ""
    suffix = ""
    body = text
    if body and body[0] in "/[":
        prefix = body[0]
        body = body[1:]
    if body and body[-1] in "/]":
        suffix = body[-1]
        body = body[:-1]

    stress_idx = body.find("ˈ")
    if stress_idx <= 0:
        return text

    before_stress = body[:stress_idx]
    if (
        len(before_stress) <= 4
        and not any(ch in _IPA_VOWELS for ch in before_stress)
    ):
        body = "ˈ" + before_stress + body[stress_idx + 1:]
        return f"{prefix}{body}{suffix}"

    return text


def _overlay_row_to_entry(row: sqlite3.Row) -> dict:
    """将 overlay.db 的行转换为 API 兼容的 entry 字典"""
    definitions  = _jl(row["definitions"],  "[]", [])
    examples     = _jl(row["examples"],     "[]", [])
    forms_raw    = _jl(row["forms"],        "[]", [])
    pos_raw      = _jl(row["pos"],          "[]", [])

    # forms: [{type, form}] → ["type:form"]
    forms = [f"{f.get('type', '?')}:{f['form']}" for f in forms_raw if isinstance(f, dict)]

    # AI-enriched fields (v3 schema)
    synonyms     = _jl(row["synonyms"],     "[]", [])
    antonyms     = _jl(row["antonyms"],     "[]", [])
    collocations = _jl(row["collocations"], "[]", [])
    associations = _jl(row["associations"], "[]", [])
    etym_parsed  = _jl(row["etymology"],    "{}", {})
    etymology    = etym_parsed if isinstance(etym_parsed, dict) else {}

    result = {
        "phonetic": _normalize_ipa_stress(row["phonetic"]),
        "syllables": row["syllables"] or "",
        "pos": pos_raw,
        "definitions": definitions,
        "examples": examples,
        "frequency": row["frequency"] or 0,
        "cefr": row["cefr"] or "",
        "forms": forms,
        "source": row["source"] or "overlay",
    }

    # Only include enriched fields if they have data
    if synonyms:
        result["synonyms"] = synonyms
    if antonyms:
        result["antonyms"] = antonyms
    if collocations:
        result["collocations"] = collocations
    if associations:
        result["associations"] = associations
    if etymology:
        result["etymology"] = etymology

    # field_meta: per-field repair status ("filled" | "confirmed_empty" | "pending")
    # allows consumers to distinguish legitimately-empty fields from unrepaired ones
    keys = row.keys() if hasattr(row, "keys") else []
    if "field_meta" in keys:
        raw = row["field_meta"]
        if raw and raw != "{}":
            result["_field_coverage"] = json.loads(raw)

    return result


def _lookup_overlay(word: str) -> dict | None:
    """从 overlay.db 查词，返回 entry 或 None"""
    odb = _get_overlay()
    if odb is None:
        return None
    cursor = odb.execute(
        'SELECT * FROM overlay WHERE word = ? COLLATE NOCASE AND audit_pass = 2',
        (word,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    return _overlay_row_to_entry(row)


def _lookup_overlay_batch(words: list[str]) -> dict:
    """从 overlay.db 批量查词"""
    odb = _get_overlay()
    if odb is None:
        return {}
    lower_map = {w.lower(): w for w in words}
    results = {}
    BATCH_SIZE = 500
    for i in range(0, len(words), BATCH_SIZE):
        batch = words[i:i + BATCH_SIZE]
        placeholders = ','.join('?' * len(batch))
        cursor = odb.execute(
            f'SELECT * FROM overlay WHERE word IN ({placeholders}) AND audit_pass = 2',
            tuple(w.lower() for w in batch)
        )
        for row in cursor.fetchall():
            entry = _overlay_row_to_entry(row)
            original_key = lower_map.get(row["word"].lower(), row["word"])
            results[original_key] = entry
    return results


def _row_to_entry(row: sqlite3.Row) -> dict:
    """将 ECDICT 的 SQLite 行转换为当前 API 兼容的 entry 字典"""
    definitions = _build_definitions(row["definition"], row["translation"])

    # 从 definitions 中收集 pos（如果数据库 pos 为空）
    pos_set = set()
    if row["pos"]:
        pos_set.update(_parse_pos(row["pos"]))
    for d in definitions:
        if d["pos"]:
            pos_set.add(d["pos"])

    word_str = row["word"] or ""
    return {
        "phonetic": row["phonetic"] or "",
        "syllables": _hyphen_dic.inserted(word_str.lower(), hyphen='-') if word_str else "",
        "pos": sorted(pos_set),
        "definitions": definitions,
        "examples": [],  # ECDICT detail 字段含例句，暂不解析
        "frequency": row["frq"] or 0,
        "cefr": "",  # ECDICT 无直接 CEFR 字段，可用 collins/oxford 推断
        "forms": _parse_exchange(row["exchange"]),
        # 扩展字段（ECDICT 新增）
        "collins": row["collins"] or 0,
        "oxford": row["oxford"] or 0,
        "tag": row["tag"] or "",
        "bnc": row["bnc"] or 0,
    }


def lookup_word(word: str) -> dict | None:
    """查词：overlay 优先 → ECDICT 兜底"""
    if not word:
        return None
    # 优先查 overlay
    entry = _lookup_overlay(word)
    if entry:
        return entry
    # fallback ECDICT
    db = _get_db()
    cursor = db.execute(
        'SELECT * FROM stardict WHERE word = ? COLLATE NOCASE',
        (word,)
    )
    row = cursor.fetchone()
    if not row:
        return None
    return _row_to_entry(row)


def lookup_words_batch(words: list[str]) -> dict:
    """批量查词：overlay 优先 → ECDICT 兜底"""
    if not words:
        return {}
    # 先从 overlay 批量查
    overlay_results = _lookup_overlay_batch(words)
    # 找出 overlay 没覆盖的词
    overlay_words = {k.lower() for k in overlay_results}
    missing = [w for w in words if w.lower() not in overlay_words]
    if not missing:
        return overlay_results
    # fallback ECDICT
    db = _get_db()
    BATCH_SIZE = 500
    lower_map = {w.lower(): w for w in missing}
    ecdict_results = {}
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i:i + BATCH_SIZE]
        placeholders = ','.join('?' * len(batch))
        cursor = db.execute(
            f'SELECT * FROM stardict WHERE word IN ({placeholders}) COLLATE NOCASE',
            tuple(batch)
        )
        for row in cursor.fetchall():
            entry = _row_to_entry(row)
            original_key = lower_map.get(row["word"].lower(), row["word"])
            ecdict_results[original_key] = entry
    # 合并：overlay 覆盖 ECDICT
    ecdict_results.update(overlay_results)
    return ecdict_results


def search_prefix(q: str, limit: int) -> list[str]:
    q = q.lower()
    if not q:
        return []
    # 转义 LIKE 通配符 % 和 _，防止被当作通配符
    q_escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    db = _get_db()
    cursor = db.execute(
        '''SELECT word FROM stardict
           WHERE word LIKE ? ESCAPE '\\'
           ORDER BY CASE WHEN word = ? THEN 0 ELSE 1 END,
                    CASE WHEN frq IS NULL THEN 999999 ELSE frq END ASC
           LIMIT ?''',
        (q_escaped + '%', q, limit)
    )
    return [row["word"] for row in cursor.fetchall()]
