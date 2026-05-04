"""Moread Content API — 模块化启动入口"""

from fastapi import FastAPI
from api.middleware import setup_middleware, HOST, PORT, DEBUG, WHITELIST_ENABLED, ALLOWED_NETWORKS
from api.vocabulary import router as vocab_router
from api.dictionary import router as dict_router

app = FastAPI(
    title="Moread Content API",
    description="英语教学内容资源库 API — 词库管理 + 词典查询",
    version="1.0.0",
    debug=DEBUG,
)

setup_middleware(app)

app.include_router(vocab_router)
app.include_router(dict_router)


if __name__ == "__main__":
    import uvicorn
    print("🚀 Moread Content API")
    print(f"   Host: {HOST}:{PORT}")
    print(f"   Debug: {DEBUG}")
    if WHITELIST_ENABLED:
        print(f"   IP Whitelist: {[str(n) for n in ALLOWED_NETWORKS]}")
    else:
        print("   IP Whitelist: disabled (all allowed)")
    uvicorn.run(app, host=HOST, port=PORT)
