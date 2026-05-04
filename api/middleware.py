"""配置加载 + IP 白名单中间件"""

import os
import ipaddress
from pathlib import Path as FilePath
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from dotenv import load_dotenv

# ─── 加载 .env ──────────────────────────────────────────────
load_dotenv(FilePath(__file__).resolve().parent.parent / ".env")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8900"))
DEBUG = os.getenv("DEBUG", "false").lower() == "true"

# ─── IP 白名单 ─────────────────────────────────────────────
_raw_ips = os.getenv("ALLOWED_IPS", "").strip()
ALLOWED_NETWORKS: list = []
WHITELIST_ENABLED = False

if _raw_ips:
    WHITELIST_ENABLED = True
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


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if not WHITELIST_ENABLED:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        try:
            ip_obj = ipaddress.ip_address(client_ip)
            allowed = any(ip_obj in net for net in ALLOWED_NETWORKS)
        except ValueError:
            allowed = False

        if not allowed:
            return JSONResponse(
                {"error": "Forbidden", "ip": client_ip},
                status_code=403,
            )

        return await call_next(request)


def setup_middleware(app):
    """统一注册中间件"""
    app.add_middleware(IPWhitelistMiddleware)

    cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
