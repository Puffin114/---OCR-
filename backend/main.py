"""FastAPI 入口。启动： uvicorn main:app --port 8000 （工作目录在 backend/）。"""
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import get_config
from db import init_db
from routers import datasets, documents, annotations, eval_tasks, metrics, review, auth, settings, backflow
from routers.auth import is_authed
from services import dataset_service

app = FastAPI(title="文档抽取评测平台")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 登录鉴权：除放行名单外的 /api/* 需有效登录 Cookie
_AUTH_PUBLIC = {"/api/auth/login", "/api/auth/logout", "/api/auth/me", "/api/health"}


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in _AUTH_PUBLIC:
        return await call_next(request)
    if not is_authed(request):
        return JSONResponse({"detail": "未登录或登录已过期"}, status_code=401)
    return await call_next(request)


app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(datasets.router)
app.include_router(documents.router)
app.include_router(annotations.router)
app.include_router(eval_tasks.router)
app.include_router(metrics.router)
app.include_router(review.router)
app.include_router(backflow.router)


@app.on_event("startup")
def _startup():
    get_config()
    init_db()
    dataset_service.backfill_label_parents()


@app.get("/api/health")
def health():
    get_config()
    return {"ok": True}


# 生产：若已构建前端，挂载静态资源并提供 SPA 回退
# 前端是单页应用(React Router)，刷新/直达子路由(如 /tasks、/tasks/10)时后端需回退到 index.html，
# 否则 StaticFiles 找不到对应文件会返回 404。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIST = os.path.join(_ROOT, "frontend", "dist")
if os.path.isdir(_DIST):
    _ASSETS = os.path.join(_DIST, "assets")
    if os.path.isdir(_ASSETS):
        app.mount("/assets", StaticFiles(directory=_ASSETS), name="assets")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        # 未匹配的 /api 路径仍返回 404（不吞成 index.html）
        if full_path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = os.path.join(_DIST, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_DIST, "index.html"))
