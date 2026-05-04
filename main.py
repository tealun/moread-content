"""
Moread Content API — 词库底座服务

启动: uvicorn main:app --host 0.0.0.0 --port 8900
测试: curl http://localhost:8900/api/packs

配置: 根目录 .env 文件
"""

from fastapi import FastAPI, Query, Path, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv
import orjson
import os
import ipaddress
from pathlib import Path as FilePath
from typing import Optional

# ─── 加载 .env ──────────────────────────────────────────────

load_dotenv(FilePath(__file__).resolve().parent / ".env")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8900"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# IP 白名单：
#   不配置或留空 → 放行所有请求
#   配置具体 IP/CIDR → 只放行匹配的来源，其余拒绝
#   示例：127.0.0.1,::1 → 仅本地
#   示例：127.0.0.1,10.0.0.5,172.16.0.0/12 → 本地 + 指定 IP + 内网段
_raw_ips = os.getenv("ALLOWED_IPS", "").strip()
ALLOWED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
_WHITELIST_ENABLED = False

if _raw_ips:
    _WHITELIST_ENABLED = True
    for entry in _raw_ips.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            if "/" in entry:
                ALLOWED_NETWORKS.append(ipaddress.ip_network(entry, strict=False))
            elif ":" in entry:
                ALLOWED_NETWORKS.append(ipaddress.ip_network(f"{entry}/128", strict=False))
            else:
                ALLOWED_NETWORKS.append(ipaddress.ip_network(f"{entry}/32", strict=False))
        except ValueError:
            print(f"⚠️  忽略无效 IP 配置: {entry}")

# ─── IP 白名单中间件 ─────────────────────────────────────────

class IPWhitelistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 未配置白名单 → 放行所有
        if not _WHITELIST_ENABLED:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"

        try:
            ip_obj = ipaddress.ip_address(client_ip)
            allowed = any(ip_obj in net for net in ALLOWED_NETWORKS)
        except ValueError:
            allowed = False

        if not allowed:
            return Response(
                content=orjson.dumps({"error": "Forbidden", "ip": client_ip}),
                status_code=403,
                media_type="application/json",
            )

        return await call_next(request)


# ─── App 初始化 ─────────────────────────────────────────────

app = FastAPI(
    title="Moread Content API",
    description="英语教学内容资源库 API — 词库管理 + 词典查询",
    version="1.0.0",
    debug=DEBUG,
)

# IP 白名单（最先执行）
app.add_middleware(IPWhitelistMiddleware)

# CORS
cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── 数据加载 ────────────────────────────────────────────────

BASE_DIR = FilePath(__file__).resolve().parent
VOCAB_DIR = BASE_DIR / "vocabulary"
DICT_DIR = BASE_DIR / "dictionary"


def _load_json(path):
    with open(path, "rb") as f:
        return orjson.loads(f.read())


def _load_index():
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
    for entry in get_index():
        if entry["id"] == pack_id:
            return _load_json(VOCAB_DIR / entry["file"])
    return None


def lookup_word(word: str):
    if not word:
        return None
    initial = word[0].lower()
    if initial not in _dict_cache:
        dict_file = DICT_DIR / f"{initial}.json"
        if not dict_file.exists():
            return None
        data = _load_json(dict_file)
        _dict_cache[initial] = data
    return _dict_cache.get(initial, {}).get(word.lower())


def lookup_words_batch(words: list[str]):
    results = {}
    for word in words:
        entry = lookup_word(word)
        if entry:
            results[word] = entry
    return results


# ─── API 路由 ────────────────────────────────────────────────

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
        return JSONResponse({"error": "Pack not found"}, status_code=404)
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
        return JSONResponse({"error": "Pack not found"}, status_code=404)
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
        return JSONResponse({"error": "Word not found", "word": word}, status_code=404)
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
    print(f"🚀 Moread Content API")
    print(f"   Host: {HOST}:{PORT}")
    print(f"   Debug: {DEBUG}")
    if _WHITELIST_ENABLED:
        print(f"   IP Whitelist: {[str(n) for n in ALLOWED_NETWORKS]}")
    else:
        print(f"   IP Whitelist: disabled (all allowed)")
    uvicorn.run(app, host=HOST, port=PORT)
