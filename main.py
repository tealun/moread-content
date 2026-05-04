"""
Moread Content API — 词库底座服务

启动: uvicorn main:app --host 0.0.0.0 --port 8900
测试: curl http://localhost:8900/api/packs
"""

from fastapi import FastAPI, Query, Path
from fastapi.middleware.cors import CORSMiddleware
import orjson
import os
from pathlib import Path as FilePath
from typing import Optional

app = FastAPI(
    title="Moread Content API",
    description="英语教学内容资源库 API — 词库管理 + 词典查询",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── 数据加载 ─────────────────────────────────────────────

BASE_DIR = FilePath(__file__).resolve().parent.parent
VOCAB_DIR = BASE_DIR / "vocabulary"
DICT_DIR = BASE_DIR / "dictionary"


def _load_json(path):
    """Load JSON with fallback to orjson"""
    with open(path, "rb") as f:
        return orjson.loads(f.read())


def _load_index():
    """Load vocabulary index"""
    return _load_json(VOCAB_DIR / "index.json")


# Lazy loaders
_index_cache = None
_dict_cache = {}


def get_index():
    global _index_cache
    if _index_cache is None:
        _index_cache = _load_index()
    return _index_cache


def get_pack(pack_id: str):
    """Load a specific pack by ID"""
    for entry in get_index():
        if entry["id"] == pack_id:
            return _load_json(VOCAB_DIR / entry["file"])
    return None


def lookup_word(word: str):
    """Lookup a word in ECDICT dictionary"""
    if not word:
        return None
    initial = word[0].lower()
    if initial not in _dict_cache:
        dict_file = DICT_DIR / f"{initial}.json"
        if not dict_file.exists():
            return None
        data = _load_json(dict_file)
        # Build lookup table
        _dict_cache[initial] = data
    return _dict_cache.get(initial, {}).get(word.lower())


def lookup_words_batch(words: list[str]):
    """Batch lookup words from ECDICT"""
    results = {}
    for word in words:
        entry = lookup_word(word)
        if entry:
            results[word] = entry
    return results


# ─── API 路由 ─────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "packs": len(get_index())}


@app.get("/api/packs")
def list_packs():
    """获取所有可用词库列表"""
    return get_index()


@app.get("/api/packs/{pack_id}")
def get_pack_detail(pack_id: str = Path(..., description="词库ID")):
    """获取词库详情（包含完整词单）"""
    pack = get_pack(pack_id)
    if not pack:
        return {"error": "Pack not found"}
    return pack


@app.get("/api/packs/{pack_id}/words")
def get_pack_words(
    pack_id: str = Path(..., description="词库ID"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(100, ge=1, le=1000, description="每页数量"),
):
    """分页获取词库单词"""
    pack = get_pack(pack_id)
    if not pack:
        return {"error": "Pack not found"}
    words = pack["words"][offset:offset + limit]
    return {
        "pack_id": pack_id,
        "offset": offset,
        "limit": limit,
        "total": len(pack["words"]),
        "words": words,
    }


@app.get("/api/dictionary/{word}")
def lookup(word: str = Path(..., description="单词")):
    """查询单个单词的完整释义（ECDICT 底座）"""
    entry = lookup_word(word)
    if not entry:
        return {"error": "Word not found", "word": word}
    return {"word": word.lower(), **entry}


@app.post("/api/dictionary/batch")
def batch_lookup(words: list[str] = Query(..., description="单词列表")):
    """批量查询单词释义"""
    return lookup_words_batch(words)


@app.get("/api/search")
def search_words(
    q: str = Query(..., min_length=1, description="搜索关键词（前缀匹配）"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
):
    """前缀搜索单词"""
    q = q.lower()
    initial = q[0]
    results = []

    dict_data = _dict_cache.get(initial)
    if dict_data is None:
        dict_file = DICT_DIR / f"{initial}.json"
        if dict_file.exists():
            dict_data = _load_json(dict_file)
            _dict_cache[initial] = dict_data
        else:
            dict_data = {}

    for key in dict_data:
        if key.startswith(q):
            results.append(key)
            if len(results) >= limit:
                break

    return {"query": q, "count": len(results), "words": results}


@app.get("/api/stats")
def stats():
    """词库统计"""
    index = get_index()
    total_words = sum(p["word_count"] for p in index)
    categories = {}
    for p in index:
        cat = p["category"]
        categories[cat] = categories.get(cat, 0) + 1
    return {
        "total_packs": len(index),
        "total_words": total_words,
        "categories": categories,
        "packs": index,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8900)
