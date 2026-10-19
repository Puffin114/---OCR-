from fastapi import APIRouter, HTTPException

from models import BoxRecognizeReq, SaveAnnotationReq, DeleteGroupReq
from services import annotation_service

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


@router.post("/recognize")
def recognize(req: BoxRecognizeReq):
    try:
        text = annotation_service.recognize_box(req.doc_key, req.page_num, req.box, req.dataset_id)
        return {"text": text}
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/save")
def save(req: SaveAnnotationReq):
    try:
        return annotation_service.save_annotation(
            req.doc_key, req.field, req.label_id, req.value, req.page_num, req.box, req.dataset_id,
            req.parent_field, req.parent_label_id, req.group_index)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/delete-group")
def delete_group(req: DeleteGroupReq):
    try:
        return annotation_service.delete_annotation_group(
            req.doc_key, req.parent_field, req.group_index, req.dataset_id)
    except Exception as e:
        raise HTTPException(400, str(e))
