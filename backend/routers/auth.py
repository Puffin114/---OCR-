"""轻量登录鉴权：单账号 + HttpOnly Cookie + 服务端内存 token。

说明：面向内部使用的最小鉴权。token 存内存，后端重启后失效需重新登录。
"""
import secrets

from fastapi import APIRouter, Request, Response, HTTPException

from config import get_config

router = APIRouter(prefix="/api/auth", tags=["auth"])

COOKIE_NAME = "auth_token"
_TOKENS: set = set()


def is_authed(request: Request) -> bool:
    tok = request.cookies.get(COOKIE_NAME)
    return bool(tok) and tok in _TOKENS


@router.post("/login")
def login(body: dict, response: Response):
    cfg = get_config()
    username = (body or {}).get("username", "")
    password = (body or {}).get("password", "")
    if username != cfg.auth_username or password != cfg.auth_password:
        raise HTTPException(401, "账号或密码错误")
    token = secrets.token_urlsafe(32)
    _TOKENS.add(token)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", path="/")
    return {"ok": True, "username": username}


@router.post("/logout")
def logout(request: Request, response: Response):
    tok = request.cookies.get(COOKIE_NAME)
    if tok:
        _TOKENS.discard(tok)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    if is_authed(request):
        return {"authed": True, "username": get_config().auth_username}
    return {"authed": False}
