"""数据加载层 — 索引、词库、词典的懒加载缓存"""

import orjson
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
VOCAB_DIR = BASE_DIR / "vocabulary"
DICT_DIR = BASE_DIR / "dictionary"

_index_cache = None
_pack_cache: dict = {}
_dict_cache: dict = {}


def _load_json(path: Path):
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


def lookup_word(word: str) -> dict | None:
    if not word:
        return None
    initial = word[0].lower()
    if initial not in _dict_cache:
        dict_file = DICT_DIR / f"{initial}.json"
        if not dict_file.exists():
            _dict_cache[initial] = {}
            return None
        _dict_cache[initial] = _load_json(dict_file)
    return _dict_cache.get(initial, {}).get(word.lower())


def lookup_words_batch(words: list[str]) -> dict:
    results = {}
    for word in words:
        entry = lookup_word(word)
        if entry:
            results[word] = entry
    return results


def search_prefix(q: str, limit: int) -> list[str]:
    q = q.lower()
    initial = q[0]
    if initial not in _dict_cache:
        dict_file = DICT_DIR / f"{initial}.json"
        if dict_file.exists():
            _dict_cache[initial] = _load_json(dict_file)
        else:
            _dict_cache[initial] = {}

    results = []
    for key in _dict_cache.get(initial, {}):
        if key.startswith(q):
            results.append(key)
            if len(results) >= limit:
                break
    return results
