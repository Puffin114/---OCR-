"""配置中心：云平台凭证(AK/SK) + 模型服务 CRUD。均需登录（由全局中间件保护）。"""
from fastapi import APIRouter, HTTPException

from config import get_config, update_cloud_config
from db import get_conn

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _mask(s: str) -> str:
    if not s:
        return ""
    return (s[:4] + "****") if len(s) > 4 else "****"


def _is_masked(v: str) -> bool:
    """前端回传的掩码值（含 ****）视为未修改。"""
    return v is None or v == "" or "****" in v


# ---------- 云平台凭证 ----------
@router.get("/credentials")
def get_credentials():
    cfg = get_config()
    return {
        "api_key": cfg.api_key or "",
        "secret_key": _mask(cfg.secret_key or ""),
        "has_secret": bool(cfg.secret_key),
        "token_url": cfg.token_url or "",
        "submit_url": cfg.submit_url or "",
        "result_url": cfg.result_url or "",
        "ocr_url": cfg.ocr_url or "",
    }


@router.post("/credentials")
def save_credentials(body: dict):
    body = body or {}
    updates = {}
    for k in ("api_key", "token_url", "submit_url", "result_url", "ocr_url"):
        if k in body and body[k] is not None:
            updates[k] = body[k]
    # secret_key：掩码/空则不改
    if "secret_key" in body and not _is_masked(body.get("secret_key")):
        updates["secret_key"] = body["secret_key"]
    update_cloud_config(updates)
    return {"ok": True}


# ---------- 模型服务 ----------
_FIELDS = ("name", "model", "model_type", "api_key", "api_url",
           "context_len", "max_input", "max_output")


def _row_out(r):
    d = dict(r)
    d["api_key"] = _mask(d.get("api_key") or "")
    d["has_key"] = bool(r["api_key"])
    return d


@router.get("/models")
def list_models():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM model_service ORDER BY id DESC").fetchall()
    return [_row_out(r) for r in rows]


@router.post("/models")
def create_model(body: dict):
    body = body or {}
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "服务名称不能为空")
    cols = [f for f in _FIELDS]
    vals = [body.get(f) for f in cols]
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in cols)
        conn.execute(f"INSERT INTO model_service({','.join(cols)}) VALUES({placeholders})", vals)
        conn.commit()
    return {"ok": True}


@router.put("/models/{model_id}")
def update_model(model_id: int, body: dict):
    body = body or {}
    with get_conn() as conn:
        cur = conn.execute("SELECT * FROM model_service WHERE id=?", (model_id,)).fetchone()
        if not cur:
            raise HTTPException(404, "模型服务不存在")
        sets, vals = [], []
        for f in _FIELDS:
            if f == "api_key":
                if _is_masked(body.get("api_key")):
                    continue  # 掩码/空 → 保留原值
                sets.append("api_key=?"); vals.append(body["api_key"])
            elif f in body and body[f] is not None:
                sets.append(f"{f}=?"); vals.append(body[f])
        sets.append("updated_at=datetime('now','localtime')")
        vals.append(model_id)
        conn.execute(f"UPDATE model_service SET {','.join(sets)} WHERE id=?", vals)
        conn.commit()
    return {"ok": True}


@router.delete("/models/{model_id}")
def delete_model(model_id: int):
    with get_conn() as conn:
        conn.execute("DELETE FROM model_service WHERE id=?", (model_id,))
        conn.commit()
    return {"ok": True}
