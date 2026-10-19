import json

from fastapi import APIRouter, HTTPException

from db import get_conn
from models import SaveCriteriaReq, OverrideReq, RecomputeReq
from services import eval_service

router = APIRouter(prefix="/api/review", tags=["review"])


@router.get("/{task_id}/criteria")
def get_criteria(task_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM eval_criteria WHERE task_id=?", (task_id,)).fetchall()
    return [{"field": r["field"], "modes": json.loads(r["modes"] or "[]"),
             "regex": r["regex"]} for r in rows]


@router.post("/criteria")
def save_criteria(req: SaveCriteriaReq):
    with get_conn() as conn:
        for it in req.items:
            conn.execute(
                "INSERT INTO eval_criteria(task_id,field,modes,regex) VALUES(?,?,?,?)"
                " ON CONFLICT(task_id,field) DO UPDATE SET modes=excluded.modes, regex=excluded.regex",
                (req.task_id, it.field, json.dumps(it.modes, ensure_ascii=False), it.regex))
        conn.commit()
    return {"ok": True}


@router.get("/{task_id}/overrides")
def get_overrides(task_id: int):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM review_override WHERE task_id=?", (task_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/override")
def set_override(req: OverrideReq):
    if req.verdict not in ("success", "fail"):
        raise HTTPException(400, "verdict 必须是 success 或 fail")
    with get_conn() as conn:
        old = conn.execute(
            "SELECT verdict FROM review_override WHERE task_id=? AND doc_key=? AND field=?",
            (req.task_id, req.doc_key, req.field)).fetchone()
        old_v = old["verdict"] if old else None
        conn.execute(
            "INSERT INTO review_override(task_id,doc_key,field,verdict,old_verdict)"
            " VALUES(?,?,?,?,?)"
            " ON CONFLICT(task_id,doc_key,field) DO UPDATE SET"
            " old_verdict=review_override.verdict, verdict=excluded.verdict,"
            " updated_at=datetime('now','localtime')",
            (req.task_id, req.doc_key, req.field, req.verdict, old_v))
        conn.commit()
    return {"ok": True}


@router.delete("/override")
def clear_override(task_id: int, doc_key: str, field: str):
    with get_conn() as conn:
        conn.execute("DELETE FROM review_override WHERE task_id=? AND doc_key=? AND field=?",
                     (task_id, doc_key, field))
        conn.commit()
    return {"ok": True}


@router.post("/recompute")
def recompute(req: RecomputeReq):
    try:
        return eval_service.compute(req.task_id, review=True)
    except Exception as e:
        raise HTTPException(400, str(e))
