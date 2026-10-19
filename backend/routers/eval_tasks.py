import json
import threading

from fastapi import APIRouter, HTTPException

from config import get_config
from db import get_conn
from models import CreateEvalTaskReq, RenameTaskReq
from services import dataset_service, eval_service
from services.cloud_service import run_extract, QuotaGuardError

router = APIRouter(prefix="/api/eval-tasks", tags=["eval-tasks"])


def _task_name_exists(name: str, exclude_id: int = None) -> bool:
    """评测任务名称是否已存在（strip 后精确比较，区分大小写）。exclude_id 用于重命名排除自身。"""
    name = (name or "").strip()
    if not name:
        return False
    with get_conn() as conn:
        if exclude_id is None:
            row = conn.execute("SELECT 1 FROM eval_task WHERE name=? LIMIT 1", (name,)).fetchone()
        else:
            row = conn.execute("SELECT 1 FROM eval_task WHERE name=? AND id!=? LIMIT 1",
                               (name, exclude_id)).fetchone()
    return row is not None


def _pick_doc_keys(dataset_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT key FROM document WHERE dataset_id=? AND has_doc=1 ORDER BY id",
            (dataset_id,)).fetchall()
    # 需有实际标注值才可评测；不再限制数量，返回全部可评测样本
    return [r["key"] for r in rows if dataset_service.annotation_values(r["key"], dataset_id)]


def _run_task(task_id: int, dataset_id: int, doc_keys, fields=None, field_defs=None):
    cfg = get_config()
    engine = f"百度智能云 文档抽取 OpenAPI ({cfg.submit_url})"
    with get_conn() as conn:
        conn.execute("UPDATE eval_task SET engine=?, started_at=datetime('now','localtime') WHERE id=?",
                     (engine, task_id))
        conn.commit()
    with get_conn() as conn:
        labels = [dict(r) for r in conn.execute(
            "SELECT label_id,label_name,label_extend,parent_id FROM label WHERE dataset_id=? ORDER BY display_order",
            (dataset_id,)).fetchall()]
    doc_paths = [dataset_service.doc_file_path(k, dataset_id) for k in doc_keys]
    manifest_override = None
    if field_defs:
        from services.cloud_service import manifest_from_defs
        manifest_override = manifest_from_defs(field_defs)
    try:
        results = run_extract(doc_paths, labels, doc_keys=doc_keys, fields=fields,
                              manifest_override=manifest_override)
        # results key 是 basename；映射回 doc_key
        name_to_key = {dataset_service.doc_file_path(k, dataset_id).split("/")[-1]: k for k in doc_keys}
        with get_conn() as conn:
            for basename, res in results.items():
                dk = name_to_key.get(basename, basename)
                conn.execute(
                    "INSERT INTO prediction(task_id,doc_key,raw_json,parsed_json,elapsed_ms,slice_count)"
                    " VALUES(?,?,?,?,?,?)",
                    (task_id, dk, json.dumps(res.get("raw", {}), ensure_ascii=False),
                     json.dumps(res.get("parsed", {}), ensure_ascii=False),
                     res.get("elapsed_ms", 0), res.get("slice_count", 0)))
            conn.commit()
        eval_service.compute(task_id, review=False)
        _set_status(task_id, "success", "评测完成")
    except QuotaGuardError as e:
        _set_status(task_id, "failed", f"额度保护：{e}")
    except Exception as e:  # noqa
        _set_status(task_id, "failed", str(e))


def _set_status(task_id: int, status: str, message: str = ""):
    with get_conn() as conn:
        if status in ("success", "failed"):
            conn.execute(
                "UPDATE eval_task SET status=?, message=?, finished_at=datetime('now','localtime') WHERE id=?",
                (status, message, task_id))
        else:
            conn.execute("UPDATE eval_task SET status=?, message=? WHERE id=?",
                         (status, message, task_id))
        conn.commit()


@router.post("")
def create(req: CreateEvalTaskReq):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "任务名称不能为空")
    if _task_name_exists(name):
        raise HTTPException(409, "评测任务名称已存在，请换一个名称")
    doc_keys = req.doc_keys or _pick_doc_keys(req.dataset_id)
    if not doc_keys:
        raise HTTPException(400, "没有可评测的样本（需有原文件且已标注）")
    # 字段与预设标准：优先用预览页的完整字段定义 field_defs，否则用 fields/criteria
    field_defs = req.field_defs or None
    if field_defs:
        parent_names = {d.get("parent") for d in field_defs if d.get("parent")}
        incl = [d for d in field_defs if d.get("name") and d.get("include", True)]
        # 评测字段仅取叶子字段（组合字段容器只用于 manifest 层级，自身无值不计指标）
        leaves = [d for d in incl if d["name"] not in parent_names]
        fields = [d["name"] for d in leaves]
        criteria_items = [(d["name"], d.get("modes") or ["exact"], d.get("regex")) for d in leaves]
    else:
        fields = req.fields or []
        criteria_items = [(it.field, it.modes, it.regex) for it in (req.criteria or [])]
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO eval_task(dataset_id,name,status,version,doc_keys,fields,field_defs)"
            " VALUES(?,?,?,?,?,?,?)",
            (req.dataset_id, name, "running", req.version or "V1",
             json.dumps(doc_keys, ensure_ascii=False),
             json.dumps(fields, ensure_ascii=False),
             json.dumps(field_defs, ensure_ascii=False) if field_defs else None))
        task_id = cur.lastrowid
        for field, modes, regex in criteria_items:
            cur.execute(
                "INSERT OR REPLACE INTO eval_criteria(task_id,field,modes,regex) VALUES(?,?,?,?)",
                (task_id, field, json.dumps(modes, ensure_ascii=False), regex))
        conn.commit()
    threading.Thread(target=_run_task, args=(task_id, req.dataset_id, doc_keys, fields, field_defs),
                     daemon=True).start()
    return {"task_id": task_id, "status": "running", "doc_keys": doc_keys}


@router.get("/candidates")
def candidates(dataset_id: int):
    """评测任务预览页数据：可评测文档 + 可选字段（排除组合字段容器）。"""
    with get_conn() as conn:
        docs = [dict(r) for r in conn.execute(
            "SELECT key, has_annotation, has_doc FROM document "
            "WHERE dataset_id=? AND has_doc=1 ORDER BY id", (dataset_id,)).fetchall()]
        labels = [dict(r) for r in conn.execute(
            "SELECT label_id,label_name,label_color,label_extend,parent_id,eval_modes FROM label "
            "WHERE dataset_id=? ORDER BY display_order", (dataset_id,)).fetchall()]
    group_ids = {l["parent_id"] for l in labels if l["parent_id"]}
    id2name = {l["label_id"]: l["label_name"] for l in labels}
    fields = [{"name": l["label_name"], "color": l["label_color"],
               "description": l["label_extend"] or "",
               "parent": (id2name.get(l["parent_id"]) if l["parent_id"] else None),
               "is_group": l["label_id"] in group_ids,
               "modes": (json.loads(l["eval_modes"]) if l["eval_modes"] else [])}
              for l in labels]
    documents = []
    for d in docs:
        has_vals = bool(dataset_service.annotation_values(d["key"], dataset_id))
        documents.append({"key": d["key"], "annotated": has_vals,
                          "evaluable": bool(d["has_doc"]) and has_vals})
    return {"documents": documents, "fields": fields}


@router.get("")
def list_all():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM eval_task ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


@router.get("/name-available")
def name_available(name: str, exclude_id: int = None):
    """校验评测任务名称是否可用（未被占用）。供前端实时查重。"""
    return {"available": not _task_name_exists(name, exclude_id)}


@router.get("/{task_id}")
def detail(task_id: int):
    with get_conn() as conn:
        t = conn.execute("SELECT * FROM eval_task WHERE id=?", (task_id,)).fetchone()
        if not t:
            raise HTTPException(404, "任务不存在")
        preds = conn.execute("SELECT COUNT(*) c FROM prediction WHERE task_id=?",
                             (task_id,)).fetchone()["c"]
        ds = conn.execute("SELECT name, doc_total FROM dataset WHERE id=?",
                          (t["dataset_id"],)).fetchone()
    d = dict(t)
    d["doc_keys"] = json.loads(d.get("doc_keys") or "[]")
    d["prediction_count"] = preds
    d["dataset_name"] = ds["name"] if ds else None
    d["dataset_total"] = ds["doc_total"] if ds else None
    return d


@router.post("/{task_id}/rename")
def rename(task_id: int, req: RenameTaskReq):
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(400, "任务名称不能为空")
    if _task_name_exists(name, exclude_id=task_id):
        raise HTTPException(409, "评测任务名称已存在，请换一个名称")
    with get_conn() as conn:
        cur = conn.execute("UPDATE eval_task SET name=? WHERE id=?", (name, task_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(404, "任务不存在")
    return {"ok": True, "task_id": task_id, "name": name}


@router.get("/{task_id}/predictions")
def predictions(task_id: int):
    """每篇文档抽取状态与错误原因，用于界面暴露失败。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_key,raw_json,parsed_json,elapsed_ms,slice_count"
            " FROM prediction WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    items = []
    err_count = 0
    empty_count = 0
    for r in rows:
        raw = json.loads(r["raw_json"] or "{}")
        parsed = json.loads(r["parsed_json"] or "{}")
        error = raw.get("error") if isinstance(raw, dict) else None
        field_count = sum(len(v) for v in parsed.values()) if isinstance(parsed, dict) else 0
        if error:
            status = "failed"
            err_count += 1
        elif field_count == 0:
            status = "empty"
            empty_count += 1
        else:
            status = "ok"
        items.append({
            "doc_key": r["doc_key"], "status": status, "error": error,
            "field_count": field_count,
            "elapsed_ms": r["elapsed_ms"], "slice_count": r["slice_count"],
        })
    return {"total": len(items), "error_count": err_count, "empty_count": empty_count,
            "items": items}


@router.get("/{task_id}/predictions/{doc_key}/boxes")
def prediction_boxes(task_id: int, doc_key: str):
    """返回某文档云端预测字段的位置框（读 raw_json 的 valuePositions.cbox），
    形状与标注框接口一致：{field,color,text,page,box[x,y,w,h]}。"""
    import os
    with get_conn() as conn:
        row = conn.execute(
            "SELECT raw_json FROM prediction WHERE task_id=? AND doc_key=?",
            (task_id, doc_key)).fetchone()
        trow = conn.execute("SELECT dataset_id FROM eval_task WHERE id=?", (task_id,)).fetchone()
    ds_id = trow["dataset_id"] if trow else None
    boxes: list = []
    if not row:
        return {"doc_key": doc_key, "boxes": boxes}

    # 字段配色：复用数据集 labels.json
    color_map = {}
    try:
        ann_dir, _, _ = dataset_service.dirs_for_doc(doc_key, ds_id)
        lp = os.path.join(ann_dir, "labels.json")
        if os.path.exists(lp):
            with open(lp, "r", encoding="utf-8") as f:
                for lb in (json.load(f).get("labels") or []):
                    if lb.get("labelName"):
                        color_map[lb["labelName"]] = lb.get("labelColor")
    except Exception:
        pass

    raw = json.loads(row["raw_json"] or "{}")
    if not isinstance(raw, dict) or raw.get("error"):
        return {"doc_key": doc_key, "boxes": boxes}

    # 预测 cbox 与标注同处原始页面空间 → 按 doc/ref 比例校正到存储文档空间，与标注框共用同一逻辑
    scale = dataset_service.page_scales(doc_key, ds_id)

    def _cbox(vp: dict):
        cb = vp.get("cbox")
        if isinstance(cb, list) and len(cb) >= 4:
            return [cb[0], cb[1], cb[2], cb[3]]
        pts = vp.get("box")
        if isinstance(pts, list) and pts:
            xs = [p[0] for p in pts if isinstance(p, list)]
            ys = [p[1] for p in pts if isinstance(p, list)]
            if xs and ys:
                return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]
        return None

    def _emit(field: str, cell: dict):
        text = cell.get("value") or cell.get("word") or ""
        for vp in cell.get("valuePositions") or []:
            box = _cbox(vp)
            if box:
                page = vp.get("pageNo", 1)
                sx, sy = scale(page)
                boxes.append({"field": field, "color": color_map.get(field) or "#2468f2",
                              "text": text, "page": page,
                              "box": [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]})

    for doc in (raw.get("result") or {}).get("extractResult") or []:
        data = (doc or {}).get("data") or {}
        for name, items in (data.get("singleKey") or {}).items():
            for it in (items if isinstance(items, list) else [items]):
                if isinstance(it, dict):
                    _emit(name, it)
        for _parent, groups in (data.get("comboKey") or {}).items():
            for grp in (groups if isinstance(groups, list) else [groups]):
                if isinstance(grp, dict):
                    for sub_name, sub_cell in grp.items():
                        if isinstance(sub_cell, dict):
                            _emit(sub_name, sub_cell)
    return {"doc_key": doc_key, "boxes": boxes}


@router.delete("/{task_id}")
def delete(task_id: int):
    with get_conn() as conn:
        for tbl in ("prediction", "metric", "eval_criteria", "review_override"):
            conn.execute(f"DELETE FROM {tbl} WHERE task_id=?", (task_id,))
        conn.execute("DELETE FROM eval_task WHERE id=?", (task_id,))
        conn.commit()
    return {"ok": True}
