from fastapi import APIRouter, HTTPException

from services import eval_service

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/{task_id}")
def get(task_id: int):
    try:
        return eval_service.get_metrics(task_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/{task_id}/compare")
def compare(task_id: int):
    try:
        return eval_service.compare_table(task_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.get("/{task_id}/performance")
def performance(task_id: int):
    try:
        return eval_service.get_performance(task_id)
    except Exception as e:
        raise HTTPException(400, str(e))
