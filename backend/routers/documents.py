import os

import fitz  # PyMuPDF
from fastapi import APIRouter, HTTPException, Response

from services import dataset_service, annotation_service

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _open(doc_key: str, dataset_id: int = None):
    path = dataset_service.doc_file_path(doc_key, dataset_id)
    if not os.path.exists(path):
        raise HTTPException(404, f"文档文件不存在: {path}")
    return fitz.open(path)


@router.get("/{doc_key}/meta")
def meta(doc_key: str, dataset_id: int = None):
    doc = _open(doc_key, dataset_id)
    pages = []
    for i in range(doc.page_count):
        r = doc[i].rect
        pages.append({"page": i + 1, "width": r.width, "height": r.height})
    doc.close()
    return {"doc_key": doc_key, "page_count": len(pages), "pages": pages}


@router.get("/{doc_key}/page/{page}.png")
def page_png(doc_key: str, page: int, zoom: float = 2.0, dataset_id: int = None):
    doc = _open(doc_key, dataset_id)
    if page < 1 or page > doc.page_count:
        doc.close()
        raise HTTPException(404, "页码超出范围")
    mat = fitz.Matrix(zoom, zoom)
    pix = doc[page - 1].get_pixmap(matrix=mat, alpha=False)
    data = pix.tobytes("png")
    doc.close()
    return Response(content=data, media_type="image/png",
                    headers={"X-Zoom": str(zoom)})


@router.get("/{doc_key}/nodes")
def nodes(doc_key: str, page: int = 1, dataset_id: int = None):
    return {"doc_key": doc_key, "page": page,
            "nodes": annotation_service.page_nodes(doc_key, page, dataset_id)}


@router.get("/{doc_key}/annotation-grouped")
def annotation_grouped(doc_key: str, dataset_id: int = None):
    """二次标注用：{singles: {字段: 值}, groups: {组合父: [{子字段: 值}...]}}。"""
    vals = dataset_service.annotation_values(doc_key, dataset_id)
    singles = {k: " | ".join(v) for k, v in vals.items()}
    groups = dataset_service.annotation_groups(doc_key, dataset_id)
    return {"doc_key": doc_key, "singles": singles, "groups": groups}


@router.get("/{doc_key}/annotation")
def annotation_boxes(doc_key: str, dataset_id: int = None):
    """返回标注的字段框，用于叠加展示。颜色优先取数据集 labels.json 的字段配色。"""
    anns = dataset_service.read_annotation(doc_key, dataset_id)
    # 字段名→颜色 映射（来自该数据集 labels.json）
    color_map = {}
    try:
        ann_dir, _, _ = dataset_service.dirs_for_doc(doc_key, dataset_id)
        lp = os.path.join(ann_dir, "labels.json")
        if os.path.exists(lp):
            import json as _json
            with open(lp, "r", encoding="utf-8") as f:
                for lb in (_json.load(f).get("labels") or []):
                    if lb.get("labelName"):
                        color_map[lb["labelName"]] = lb.get("labelColor")
    except Exception:  # noqa
        pass
    # 标注坐标在原始页面空间，而存储文档是缩放预览 → 按 doc/ref 比例校正（与预测框共用同一逻辑）
    scale = dataset_service.page_scales(doc_key, dataset_id)

    out = []

    def _emit(node: dict):
        """递归处理一个标注节点：发出自身框，再进入 textTag[].property[] 的子节点。
        组合字段(父)自身 valueTag 常为空，其子字段框嵌套在 property[] 中，用子节点自己的 label/颜色。"""
        field = node.get("label")
        color = color_map.get(field) or node.get("labelColor") or "#2468f2"
        for tt in node.get("textTag", []) or []:
            for vt in tt.get("valueTag", []) or []:
                text = vt.get("editedText") or vt.get("text") or ""
                for det in vt.get("tagDetail", []) or []:
                    loc = det.get("location") or []
                    if len(loc) >= 4:
                        xs = [p["x"] for p in loc]
                        ys = [p["y"] for p in loc]
                        page = det.get("pageNum", 1)
                        sx, sy = scale(page)
                        out.append({
                            "field": field, "color": color, "text": text,
                            "page": page,
                            "box": [min(xs) * sx, min(ys) * sy,
                                    (max(xs) - min(xs)) * sx, (max(ys) - min(ys)) * sy],
                        })
            for sub in tt.get("property", []) or []:
                if isinstance(sub, dict):
                    _emit(sub)

    for a in anns:
        _emit(a)
    return {"doc_key": doc_key, "boxes": out}
