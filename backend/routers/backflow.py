"""回流数据接口（Extract 场景）。凭证仅随请求透传给内存任务，不持久化。"""
from fastapi import APIRouter, HTTPException

from services import backflow_service, dataset_service

router = APIRouter(prefix="/api/backflow", tags=["backflow"])


@router.get("/scene")
def scene():
    """返回场景的非敏感预置信息，供前端表单回显（不含任何密钥）。"""
    s = backflow_service.EXTRACT_SCENE
    return {"label": s["label"], "db_host": s["db_host"], "db_port": s["db_port"],
            "db_name": s["db_name"], "db_user": s["db_user"], "bos_bucket": s["bos_bucket"]}


@router.post("/extract/start")
def start_extract(body: dict):
    body = body or {}
    try:
        job_id = backflow_service.start_extract_backflow(
            name=body.get("name", ""),
            db_password=body.get("db_password", ""),
            ak=body.get("ak", ""),
            sk=body.get("sk", ""),
            user_id=body.get("user_id") or None,
            date_from=body.get("date_from") or None,
            date_to=body.get("date_to") or None,
            limit=body.get("limit", 20),
            fields=body.get("fields") or [],
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def job(job_id: str):
    j = backflow_service.get_job(job_id)
    if not j:
        raise HTTPException(404, "任务不存在或已过期")
    return j


@router.post("/extract/probe")
def probe(body: dict):
    body = body or {}
    if not body.get("db_password") or not body.get("ak") or not body.get("sk"):
        raise HTTPException(400, "数据库密码、AK、SK 均为必填")
    try:
        return backflow_service.probe_extract(
            db_password=body.get("db_password", ""),
            ak=body.get("ak", ""), sk=body.get("sk", ""),
            user_id=body.get("user_id") or None,
            sample=body.get("sample", 5))
    except Exception as e:  # noqa
        raise HTTPException(400, str(e))


@router.get("/datasets")
def datasets():
    return dataset_service.list_datasets(source="backflow")
