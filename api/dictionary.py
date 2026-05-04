"""词典路由 — lookup / batch / search"""

from fastapi import APIRouter, Query, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from .data import lookup_word, lookup_words_batch, search_prefix

router = APIRouter(prefix="/api", tags=["词典"])


class BatchRequest(BaseModel):
    words: list[str]


@router.get("/dictionary/{word}")
def lookup(word: str = Path(..., description="单词")):
    """查询单个单词的完整释义（ECDICT 底座）"""
    entry = lookup_word(word)
    if not entry:
        return JSONResponse({"error": "Word not found", "word": word}, status_code=404)
    return {"word": word.lower(), **entry}


@router.post("/dictionary/batch")
def batch_lookup(req: BatchRequest):
    """批量查询单词释义"""
    return lookup_words_batch(req.words)


@router.get("/search")
def search_words(
    q: str = Query(..., min_length=1, description="搜索关键词（前缀匹配）"),
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
):
    """前缀搜索单词"""
    results = search_prefix(q, limit)
    return {"query": q.lower(), "count": len(results), "words": results}
