"""词库路由 — packs / words / stats / categories"""

from fastapi import APIRouter, Query, Path
from fastapi.responses import JSONResponse
from .data import get_index, get_pack

router = APIRouter(prefix="/api", tags=["词库"])

# 分类元数据 — label 和排序由数据端统一定义，消费端动态拉取
CATEGORIES = [
    {"id": "basic", "label": "基础英语", "sort_order": 0},
    {"id": "cefr", "label": "CEFR 等级", "sort_order": 1},
    {"id": "exam", "label": "考试考纲", "sort_order": 2},
    {"id": "frequency", "label": "词频", "sort_order": 3},
]


@router.get("/health")
def health():
    return {"status": "ok", "packs": len(get_index())}


@router.get("/categories")
def list_categories():
    """获取分类元数据列表（含显示名称和排序）"""
    return CATEGORIES


@router.get("/packs")
def list_packs():
    """获取所有可用词库列表"""
    return get_index()


@router.get("/packs/{pack_id}")
def get_pack_detail(pack_id: str = Path(..., description="词库ID")):
    """获取词库详情（含完整词单）"""
    pack = get_pack(pack_id)
    if not pack:
        return JSONResponse({"error": "Pack not found"}, status_code=404)
    return pack


@router.get("/packs/{pack_id}/words")
def get_pack_words(
    pack_id: str = Path(..., description="词库ID"),
    offset: int = Query(0, ge=0, description="偏移量"),
    limit: int = Query(100, ge=1, le=1000, description="每页数量"),
):
    """分页获取词库单词"""
    pack = get_pack(pack_id)
    if not pack:
        return JSONResponse({"error": "Pack not found"}, status_code=404)
    words = pack.get("words", [])[offset:offset + limit]
    return {
        "pack_id": pack_id,
        "offset": offset,
        "limit": limit,
        "total": len(pack.get("words", [])),
        "words": words,
    }


@router.get("/stats")
def stats():
    """词库统计"""
    index = get_index()
    total_words = sum(p.get("word_count", 0) for p in index)
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
