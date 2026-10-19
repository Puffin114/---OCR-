"""数据集加载与解析：读取 labels.json、对齐 annotations/parser/doc 三类文件。"""
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from typing import Dict, List

from config import get_config
from db import get_conn

_DEFAULT_COLORS = ['#2468f2', '#36c361', '#ff9326', '#ff908c', '#57d9d4', '#9b5cf6', '#fad000', '#7bd964']

_PREFIX_RE = re.compile(r"^(row\d+)_")


def _dirs(base_dir: str = None):
    """返回 (annotations_dir, parser_dir, doc_dir)。base_dir 为空则用全局配置目录。"""
    cfg = get_config()
    if base_dir:
        return (os.path.join(base_dir, "annotations"),
                os.path.join(base_dir, "parser"),
                os.path.join(base_dir, "doc"))
    return (cfg.annotations_dir, cfg.parser_dir, cfg.doc_dir)


def _base_dir_for_doc(doc_key: str, dataset_id: int = None):
    with get_conn() as conn:
        if dataset_id is not None:
            row = conn.execute("SELECT base_dir FROM dataset WHERE id=?", (dataset_id,)).fetchone()
            return row["base_dir"] if row and row["base_dir"] else None
        row = conn.execute(
            "SELECT d.base_dir AS base_dir FROM document doc "
            "JOIN dataset d ON doc.dataset_id = d.id "
            "WHERE doc.key=? ORDER BY d.id DESC LIMIT 1", (doc_key,)).fetchone()
    return row["base_dir"] if row and row["base_dir"] else None


def dirs_for_doc(doc_key: str, dataset_id: int = None):
    """按 doc_key 所属数据集解析其三类目录（给定 dataset_id 时精确定位，避免同名文件串台）。"""
    return _dirs(_base_dir_for_doc(doc_key, dataset_id))


def _doc_key(filename: str) -> str:
    """从文件名提取对齐用的 key。标注/解析为 '<name>.json'，doc 为 '<name>'。"""
    name = filename
    if name.endswith(".json"):
        name = name[:-5]
    return name


def _list(dirpath: str, suffix: str = "") -> Dict[str, str]:
    out = {}
    if not os.path.isdir(dirpath):
        return out
    for f in os.listdir(dirpath):
        if f.startswith("."):
            continue
        if suffix and not f.endswith(suffix):
            continue
        out[_doc_key(f)] = f
    return out


def name_exists(name: str, exclude_id: int = None) -> bool:
    """数据集名称是否已存在（strip 后精确比较，区分大小写）。exclude_id 用于重命名排除自身。"""
    name = (name or "").strip()
    if not name:
        return False
    with get_conn() as conn:
        if exclude_id is None:
            row = conn.execute("SELECT 1 FROM dataset WHERE name=? LIMIT 1", (name,)).fetchone()
        else:
            row = conn.execute("SELECT 1 FROM dataset WHERE name=? AND id!=? LIMIT 1",
                               (name, exclude_id)).fetchone()
    return row is not None


def load_dataset(name: str = "default", base_dir: str = None, source: str = None) -> dict:
    name = (name or "").strip()
    if name_exists(name):
        raise ValueError("数据集名称已存在，请换一个名称")
    ann_dir, par_dir, doc_dir = _dirs(base_dir)
    labels_path = os.path.join(ann_dir, "labels.json")
    if not os.path.exists(labels_path):
        raise FileNotFoundError(f"未找到字段清单 {labels_path}")
    with open(labels_path, "r", encoding="utf-8") as f:
        labels_doc = json.load(f)
    labels = labels_doc.get("labels", [])

    ann = {k: v for k, v in _list(ann_dir, ".json").items() if k != "labels"}
    par = _list(par_dir, ".json")
    doc = _list(doc_dir)

    keys = sorted(set(ann) | set(par) | set(doc))

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO dataset(name, doc_total, base_dir, source) VALUES(?,?,?,?)",
                    (name, len(keys), base_dir, source))
        dataset_id = cur.lastrowid
        for lb in labels:
            pid = lb.get("parentId")
            if pid == "root":
                pid = None
            modes = lb.get("evalModes")
            cur.execute(
                "INSERT INTO label(dataset_id,label_id,label_name,label_color,display_order,label_extend,parent_id,eval_modes) VALUES(?,?,?,?,?,?,?,?)",
                (dataset_id, lb.get("labelId"), lb.get("labelName"), lb.get("labelColor"),
                 lb.get("displayOrder", 0), lb.get("labelExtend", ""), pid,
                 json.dumps(modes, ensure_ascii=False) if modes else None),
            )
        for k in keys:
            has_a = 1 if k in ann else 0
            has_p = 1 if k in par else 0
            has_d = 1 if k in doc else 0
            complete = 1 if (has_a and has_p and has_d) else 0
            cur.execute(
                "INSERT INTO document(dataset_id,key,doc_file,has_annotation,has_parser,has_doc,complete) VALUES(?,?,?,?,?,?,?)",
                (dataset_id, k, doc.get(k), has_a, has_p, has_d, complete),
            )
        conn.commit()

    return get_dataset(dataset_id)


def list_datasets(source: str = None) -> List[dict]:
    with get_conn() as conn:
        if source == "backflow":
            rows = conn.execute(
                "SELECT * FROM dataset WHERE source='backflow' ORDER BY id DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM dataset WHERE source IS NULL OR source!='backflow' ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]


def rename_dataset(dataset_id: int, name: str) -> dict:
    """重命名数据集（仅改展示名，不动目录与文件）。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("名称不能为空")
    if name_exists(name, exclude_id=dataset_id):
        raise ValueError("数据集名称已存在，请换一个名称")
    with get_conn() as conn:
        cur = conn.execute("UPDATE dataset SET name=? WHERE id=?", (name, dataset_id))
        conn.commit()
        if cur.rowcount == 0:
            raise ValueError("数据集不存在")
    return {"ok": True, "dataset_id": dataset_id, "name": name}


def delete_dataset(dataset_id: int) -> dict:
    """删除数据集及其标签/文档/评测任务（连带 prediction/metric/criteria/override）；上传集删除其目录。"""
    with get_conn() as conn:
        ds = conn.execute("SELECT base_dir FROM dataset WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise ValueError("数据集不存在")
        base_dir = ds["base_dir"]
        task_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM eval_task WHERE dataset_id=?", (dataset_id,)).fetchall()]
        for tid in task_ids:
            for tbl in ("prediction", "metric", "eval_criteria", "review_override"):
                conn.execute(f"DELETE FROM {tbl} WHERE task_id=?", (tid,))
        conn.execute("DELETE FROM eval_task WHERE dataset_id=?", (dataset_id,))
        conn.execute("DELETE FROM label WHERE dataset_id=?", (dataset_id,))
        conn.execute("DELETE FROM document WHERE dataset_id=?", (dataset_id,))
        conn.execute("DELETE FROM dataset WHERE id=?", (dataset_id,))
        conn.commit()
    # 删除上传数据集的物理目录（仅限 uploads 下，避免误删工作区数据集）
    if base_dir:
        cfg = get_config()
        uploads = os.path.realpath(os.path.join(cfg.storage_dir, "uploads"))
        real_base = os.path.realpath(base_dir)
        if real_base.startswith(uploads + os.sep):
            # base_dir 可能是 uploads/{ts_name}/{子目录}，删到 uploads 下的顶层那一层
            top = real_base
            while os.path.dirname(top) != uploads and os.path.dirname(top) != top:
                top = os.path.dirname(top)
            shutil.rmtree(top, ignore_errors=True)
    return {"ok": True, "dataset_id": dataset_id}


def delete_document(dataset_id: int, doc_key: str) -> dict:
    """从数据集删除单个文件：删 doc/annotations/parser 对应文件 + document 行 +
    doc_total-1 + 清理该数据集各任务引用此 doc_key 的 prediction/review_override。不可逆。"""
    if not doc_key or doc_key != os.path.basename(doc_key):
        raise ValueError("非法的文件标识")
    with get_conn() as conn:
        ds = conn.execute("SELECT base_dir FROM dataset WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise ValueError("数据集不存在")
        row = conn.execute("SELECT id FROM document WHERE dataset_id=? AND key=?",
                           (dataset_id, doc_key)).fetchone()
        if not row:
            raise ValueError("文件不存在于该数据集")
        base_dir = ds["base_dir"]
        task_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM eval_task WHERE dataset_id=?", (dataset_id,)).fetchall()]
        for tid in task_ids:
            conn.execute("DELETE FROM prediction WHERE task_id=? AND doc_key=?", (tid, doc_key))
            conn.execute("DELETE FROM review_override WHERE task_id=? AND doc_key=?", (tid, doc_key))
        conn.execute("DELETE FROM document WHERE dataset_id=? AND key=?", (dataset_id, doc_key))
        conn.execute("UPDATE dataset SET doc_total=MAX(doc_total-1,0) WHERE id=?", (dataset_id,))
        conn.commit()
    # 删物理文件（限定在该数据集解析出的三类目录内）
    ann_dir, par_dir, doc_dir = _dirs(base_dir)
    for d, fname in ((doc_dir, doc_key), (ann_dir, f"{doc_key}.json"), (par_dir, f"{doc_key}.json")):
        if not d:
            continue
        tgt = os.path.realpath(os.path.join(d, fname))
        if tgt.startswith(os.path.realpath(d) + os.sep) and os.path.isfile(tgt):
            try:
                os.remove(tgt)
            except OSError:
                pass
    return {"ok": True, "dataset_id": dataset_id, "doc_key": doc_key}


def backfill_label_parents():
    """为历史数据集回填 label.parent_id（从各自 labels.json 读 parentId），使组合字段分组生效。"""
    with get_conn() as conn:
        dsets = conn.execute("SELECT id, base_dir FROM dataset").fetchall()
        for ds in dsets:
            ann_dir = os.path.join(ds["base_dir"], "annotations") if ds["base_dir"] else get_config().annotations_dir
            lp = os.path.join(ann_dir, "labels.json")
            if not os.path.exists(lp):
                continue
            try:
                with open(lp, "r", encoding="utf-8") as f:
                    labs = json.load(f).get("labels", [])
            except Exception:  # noqa
                continue
            for lb in labs:
                pid = lb.get("parentId")
                if pid == "root":
                    pid = None
                if pid:
                    conn.execute(
                        "UPDATE label SET parent_id=? WHERE dataset_id=? AND label_id=? "
                        "AND (parent_id IS NULL OR parent_id='')",
                        (pid, ds["id"], lb.get("labelId")))
        conn.commit()


def _safe_name(s: str) -> str:
    return (re.sub(r"[^\w.\-]", "_", s or "uploaded") or "uploaded")[:40]


def _find_base_dir(root: str):
    """定位含 annotations/labels.json 的目录，返回其父目录作为 base_dir。"""
    for dirpath, _dirnames, filenames in os.walk(root):
        if os.path.basename(dirpath) == "annotations" and "labels.json" in filenames:
            return os.path.dirname(dirpath)
    return None


def import_zip(zip_path: str, name: str = "uploaded") -> dict:
    """解压上传的 zip 并导入为数据集。期望含 annotations/parser/doc，且 annotations/labels.json 存在。"""
    if name_exists(name):
        raise ValueError("数据集名称已存在，请换一个名称")
    cfg = get_config()
    dest = os.path.join(cfg.storage_dir, "uploads", f"{time.strftime('%Y%m%d%H%M%S')}_{_safe_name(name)}")
    os.makedirs(dest, exist_ok=True)
    real_dest = os.path.realpath(dest)
    try:
        with zipfile.ZipFile(zip_path) as zf:
            for member in zf.namelist():
                target = os.path.realpath(os.path.join(dest, member))
                if target != real_dest and not target.startswith(real_dest + os.sep):
                    raise ValueError(f"非法压缩包路径（疑似 zip-slip）：{member}")
            zf.extractall(dest)
    except zipfile.BadZipFile:
        raise ValueError("无效的 zip 文件")
    base = _find_base_dir(dest)
    if not base:
        raise FileNotFoundError("压缩包内未找到 annotations/labels.json，请确认包含 annotations/parser/doc 目录结构")
    return load_dataset(name, base_dir=base)


def _make_labels_json(fields: List[dict]) -> dict:
    """由用户编辑的字段生成 labels.json（含 parentId 与 evalModes）。
    field: {name, description?, color?, modes?[], parent?(字段名)}"""
    name2id = {}
    for f in fields:
        name2id[f["name"]] = f.get("labelId") or f"label-{uuid.uuid4().hex[:12]}"
    labels = []
    for i, f in enumerate(fields):
        parent = f.get("parent")
        pid = name2id.get(parent) if parent else "root"
        labels.append({
            "labelId": name2id[f["name"]],
            "labelName": f["name"],
            "labelColor": f.get("color") or _DEFAULT_COLORS[i % len(_DEFAULT_COLORS)],
            "displayOrder": i + 1,
            "labelExtend": f.get("description") or "",
            "parentId": pid,
            "evalModes": f.get("modes") or [],
        })
    return {"labels": labels, "classifyLabels": [], "extendLabels": []}


def parse_fields_from_file(path: str) -> List[dict]:
    """从上传文件解析字段，供前端编辑。支持：
    - labels.json / 含 labels.json 的 zip（原逻辑）
    - .xlsx：数据集导出(结构化标签 sheet) 或 应用中心导出(单个字段/组合字段 sheet)
    - .csv：按表头识别上述两种结构
    统一输出 [{name, description, color, modes, parent, is_group}]。"""
    lower = path.lower()
    if lower.endswith(".xlsx"):
        return _parse_fields_from_xlsx(path)
    if lower.endswith(".csv"):
        return _parse_fields_from_csv(path)
    return _parse_fields_from_labels_json(path)


def _parse_fields_from_labels_json(path: str) -> List[dict]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            cand = [n for n in zf.namelist() if n.endswith("labels.json")]
            if not cand:
                raise ValueError("压缩包内未找到 labels.json")
            data = json.loads(zf.read(cand[0]).decode("utf-8"))
    else:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    labels = data.get("labels", [])
    id2name = {l.get("labelId"): l.get("labelName") for l in labels}
    out = []
    for l in labels:
        pid = l.get("parentId")
        parent = id2name.get(pid) if (pid and pid != "root") else None
        out.append({
            "name": l.get("labelName"), "description": l.get("labelExtend") or "",
            "color": l.get("labelColor") or "", "modes": l.get("evalModes") or [],
            "parent": parent,
        })
    return out


def _norm_header(s) -> str:
    return str(s or "").strip()


def _parse_rows_structured(rows: List[List]) -> List[dict]:
    """格式A（数据集导出·结构化标签）：
    表头 标签名称|子标签|标签类型|标签颜色|标签扩展|分类结果。
    标签名称有值=顶层(单字段或组合父)；标签名称空且子标签有值=归属上方最近父的子字段。"""
    header = [_norm_header(c) for c in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    ci_name = idx.get("标签名称")
    ci_sub = idx.get("子标签")
    ci_color = idx.get("标签颜色")
    ci_ext = idx.get("标签扩展")

    def cell(r, i):
        return _norm_header(r[i]) if (i is not None and i < len(r)) else ""

    out: List[dict] = []
    children_of: Dict[str, List[dict]] = {}
    cur_top = None
    for r in rows[1:]:
        name = cell(r, ci_name)
        sub = cell(r, ci_sub)
        color = cell(r, ci_color)
        ext = cell(r, ci_ext)
        if name:
            cur_top = {"name": name, "description": ext, "color": color,
                       "modes": [], "parent": None, "is_group": False}
            out.append(cur_top)
            children_of[name] = []
        elif sub and cur_top is not None:
            cur_top["is_group"] = True
            out.append({"name": sub, "description": ext, "color": color,
                        "modes": [], "parent": cur_top["name"], "is_group": False})
    return out


def _parse_fields_from_xlsx(path: str) -> List[dict]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=False, data_only=True)
    sheets = {ws.title: ws for ws in wb.worksheets}

    def sheet_rows(ws):
        return [[c for c in row] for row in ws.iter_rows(values_only=True)]

    # 格式B（应用中心导出）：含「单个字段」或「组合字段」sheet
    if "单个字段" in sheets or "组合字段" in sheets:
        out: List[dict] = []
        if "单个字段" in sheets:
            rows = sheet_rows(sheets["单个字段"])
            for r in rows[1:]:
                nm = _norm_header(r[0]) if r else ""
                if nm:
                    desc = _norm_header(r[1]) if len(r) > 1 else ""
                    out.append({"name": nm, "description": desc, "color": "",
                                "modes": [], "parent": None, "is_group": False})
        if "组合字段" in sheets:
            rows = sheet_rows(sheets["组合字段"])
            seen_parent = set()
            cur_parent = None
            for r in rows[1:]:
                pname = _norm_header(r[0]) if r else ""
                cname = _norm_header(r[1]) if len(r) > 1 else ""
                desc = _norm_header(r[2]) if len(r) > 2 else ""
                if pname:  # 合并单元格时仅首行有组合名，向下沿用
                    cur_parent = pname
                if not cur_parent or not cname:
                    continue
                if cur_parent not in seen_parent:
                    out.append({"name": cur_parent, "description": "", "color": "",
                                "modes": [], "parent": None, "is_group": True})
                    seen_parent.add(cur_parent)
                out.append({"name": cname, "description": desc, "color": "",
                            "modes": [], "parent": cur_parent, "is_group": False})
        if out:
            return out

    # 格式A（数据集导出）：某 sheet 表头含「标签名称」且含「子标签」
    for ws in wb.worksheets:
        rows = sheet_rows(ws)
        if not rows:
            continue
        header = [_norm_header(c) for c in rows[0]]
        if "标签名称" in header and "子标签" in header:
            parsed = _parse_rows_structured(rows)
            if parsed:
                return parsed
    raise ValueError("无法识别的字段表格式（需为数据集导出或应用中心导出的字段清单）")


def _parse_fields_from_csv(path: str) -> List[dict]:
    import csv
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rows = [list(r) for r in csv.reader(f)]
    if not rows:
        raise ValueError("CSV 为空")
    header = [_norm_header(c) for c in rows[0]]
    if "标签名称" in header and "子标签" in header:
        return _parse_rows_structured(rows)
    if "组合名称" in header and "组合字段" in header:
        idx = {h: i for i, h in enumerate(header)}
        ci_p, ci_c = idx["组合名称"], idx["组合字段"]
        ci_d = idx.get("说明")
        out: List[dict] = []
        seen = set()
        cur_parent = None
        for r in rows[1:]:
            pname = _norm_header(r[ci_p]) if ci_p < len(r) else ""
            cname = _norm_header(r[ci_c]) if ci_c < len(r) else ""
            desc = _norm_header(r[ci_d]) if (ci_d is not None and ci_d < len(r)) else ""
            if pname:
                cur_parent = pname
            if not cur_parent or not cname:
                continue
            if cur_parent not in seen:
                out.append({"name": cur_parent, "description": "", "color": "",
                            "modes": [], "parent": None, "is_group": True})
                seen.add(cur_parent)
            out.append({"name": cname, "description": desc, "color": "",
                        "modes": [], "parent": cur_parent, "is_group": False})
        return out
    if "单个字段" in header:
        idx = {h: i for i, h in enumerate(header)}
        ci_n = idx["单个字段"]
        ci_d = idx.get("说明")
        out = []
        for r in rows[1:]:
            nm = _norm_header(r[ci_n]) if ci_n < len(r) else ""
            if nm:
                desc = _norm_header(r[ci_d]) if (ci_d is not None and ci_d < len(r)) else ""
                out.append({"name": nm, "description": desc, "color": "",
                            "modes": [], "parent": None, "is_group": False})
        return out
    raise ValueError("无法识别的 CSV 字段表（表头需含 标签名称/子标签 或 组合名称/组合字段 或 单个字段）")


def create_unannotated(name: str, description: str, fields: List[dict], file_paths: List[str],
                       orig_names: List[str] = None) -> dict:
    """未标注导入：用字段生成 labels.json，原文件放入 doc/，建未标注数据集。
    仅对真正的 .zip 解包；.docx/.xlsx 等 OOXML 本质是 zip，不可按 zip 解包，整文件保留。"""
    if name_exists(name):
        raise ValueError("数据集名称已存在，请换一个名称")
    cfg = get_config()
    dest = os.path.join(cfg.storage_dir, "uploads", f"{time.strftime('%Y%m%d%H%M%S')}_{_safe_name(name)}")
    for sub in ("doc", "annotations", "parser"):
        os.makedirs(os.path.join(dest, sub), exist_ok=True)
    with open(os.path.join(dest, "annotations", "labels.json"), "w", encoding="utf-8") as f:
        json.dump(_make_labels_json(fields), f, ensure_ascii=False)
    doc_dir = os.path.join(dest, "doc")
    real_doc = os.path.realpath(doc_dir)
    names = orig_names or [None] * len(file_paths)
    for p, oname in zip(file_paths, names):
        if (oname or p).lower().endswith(".zip"):
            with zipfile.ZipFile(p) as zf:
                for m in zf.namelist():
                    if m.endswith("/"):
                        continue
                    tgt = os.path.realpath(os.path.join(doc_dir, os.path.basename(m)))
                    if not tgt.startswith(real_doc + os.sep):
                        continue
                    with zf.open(m) as src, open(tgt, "wb") as dst:
                        dst.write(src.read())
        else:
            base = os.path.basename(oname) if oname else os.path.basename(p)
            shutil.copy(p, os.path.join(doc_dir, base))
    return load_dataset(name, base_dir=dest)


def apply_field_overrides(dataset_id: int, fields: List[dict]):
    """用用户调整后的字段覆盖 label 的颜色/说明/评测逻辑/父子（按字段名匹配）。"""
    if not fields:
        return
    with get_conn() as conn:
        name2id = {r["label_name"]: r["label_id"] for r in conn.execute(
            "SELECT label_name,label_id FROM label WHERE dataset_id=?", (dataset_id,))}
        for f in fields:
            pid = name2id.get(f.get("parent")) if f.get("parent") else None
            conn.execute(
                "UPDATE label SET label_color=COALESCE(?,label_color), label_extend=?, "
                "eval_modes=?, parent_id=? WHERE dataset_id=? AND label_name=?",
                (f.get("color") or None, f.get("description") or "",
                 json.dumps(f.get("modes") or [], ensure_ascii=False), pid,
                 dataset_id, f.get("name")))
        conn.commit()


def get_dataset(dataset_id: int) -> dict:
    with get_conn() as conn:
        ds = conn.execute("SELECT * FROM dataset WHERE id=?", (dataset_id,)).fetchone()
        if not ds:
            raise ValueError("数据集不存在")
        labels = [dict(r) for r in conn.execute(
            "SELECT * FROM label WHERE dataset_id=? ORDER BY display_order", (dataset_id,)).fetchall()]
        docs = [dict(r) for r in conn.execute(
            "SELECT * FROM document WHERE dataset_id=? ORDER BY id", (dataset_id,)).fetchall()]
    # 组合字段(容器)：labelId 被其它 label 作为 parent_id 引用
    group_ids = {lb.get("parent_id") for lb in labels if lb.get("parent_id")}
    for lb in labels:
        lb["is_group"] = lb.get("label_id") in group_ids
    # 每字段标注数量（递归组合子字段，按 dataset_id 精确定位避免同名串台）
    field_counts = {lb["label_name"]: 0 for lb in labels}
    for d in docs:
        if not d["has_annotation"]:
            continue
        for fn, vals in annotation_values(d["key"], dataset_id).items():
            if fn in field_counts and vals:
                field_counts[fn] += 1
    return {
        "dataset": dict(ds),
        "labels": labels,
        "documents": docs,
        "field_counts": field_counts,
    }


def read_annotation(doc_key: str, dataset_id: int = None) -> List[dict]:
    """读取某文档的人工标注，返回 annotations 列表。"""
    ann_dir, _, _ = dirs_for_doc(doc_key, dataset_id)
    path = os.path.join(ann_dir, doc_key + ".json")
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("annotations", [])


def annotation_values(doc_key: str, dataset_id: int = None) -> Dict[str, List[str]]:
    """{字段名: [标注值...]}。递归进入组合字段 textTag[].property[]，按每个节点自身 label 聚合值
    （组合父自身无直接值不计），使组合子字段真值不丢失。"""
    out: Dict[str, List[str]] = {}

    def walk(node: dict):
        fn = node.get("label")
        vals = []
        for tt in node.get("textTag", []) or []:
            for vt in tt.get("valueTag", []) or []:
                t = (vt.get("editedText") or vt.get("text") or "").strip()
                if t:
                    vals.append(t)
            for sub in tt.get("property", []) or []:
                if isinstance(sub, dict):
                    walk(sub)
        if vals:
            out.setdefault(fn, []).extend(vals)

    for a in read_annotation(doc_key, dataset_id):
        walk(a)
    return out


def annotation_groups(doc_key: str, dataset_id: int = None) -> Dict[str, List[Dict[str, str]]]:
    """组合字段按“组(行)”还原标注值：{父字段名: [ {子字段名: 值}, ... ]}。
    组合父标注的 textTag[].property[] 下每个子字段 valueTag 按行有序，第 i 个 valueTag 组成第 i 组。"""
    out: Dict[str, List[Dict[str, str]]] = {}
    for a in read_annotation(doc_key, dataset_id):
        parent = a.get("label")
        # 收集该父下各子字段的按序值列表
        sub_vals: Dict[str, List[str]] = {}
        sub_order: List[str] = []
        for tt in a.get("textTag", []) or []:
            for sub in tt.get("property", []) or []:
                if not isinstance(sub, dict):
                    continue
                sname = sub.get("label")
                if not sname:
                    continue
                vals: List[str] = []
                for stt in sub.get("textTag", []) or []:
                    for vt in stt.get("valueTag", []) or []:
                        vals.append((vt.get("editedText") or vt.get("text") or "").strip())
                if sname not in sub_vals:
                    sub_vals[sname] = []
                    sub_order.append(sname)
                sub_vals[sname].extend(vals)
        if not sub_order:
            continue
        n = max(len(v) for v in sub_vals.values())
        groups: List[Dict[str, str]] = []
        for i in range(n):
            groups.append({s: (sub_vals[s][i] if i < len(sub_vals[s]) else "") for s in sub_order})
        out[parent] = groups
    return out


def doc_file_path(doc_key: str, dataset_id: int = None) -> str:
    _, _, doc_dir = dirs_for_doc(doc_key, dataset_id)
    with get_conn() as conn:
        if dataset_id is not None:
            row = conn.execute("SELECT doc_file FROM document WHERE key=? AND dataset_id=?",
                               (doc_key, dataset_id)).fetchone()
        else:
            row = conn.execute("SELECT doc_file FROM document WHERE key=? ORDER BY id DESC LIMIT 1",
                               (doc_key,)).fetchone()
    fname = row["doc_file"] if row and row["doc_file"] else doc_key
    return os.path.join(doc_dir, fname)


_size_cache: Dict[str, list] = {}


def doc_page_sizes(doc_key: str, dataset_id: int = None):
    """存储文档各页尺寸 [(w,h)...]（1-based 顺序），fitz 读取，带缓存。失败返回 []。"""
    ck = f"doc:{dataset_id}:{doc_key}"
    if ck in _size_cache:
        return _size_cache[ck]
    import fitz
    sizes = []
    try:
        p = doc_file_path(doc_key, dataset_id)
        d = fitz.open(p)
        sizes = [(d[i].rect.width, d[i].rect.height) for i in range(d.page_count)]
        d.close()
    except Exception:  # noqa
        sizes = []
    _size_cache[ck] = sizes
    return sizes


def page_scales(doc_key: str, dataset_id: int = None):
    """返回 scale(page)->(sx,sy)：把“标注/预测的原始页面空间”坐标换算到“存储文档空间”。
    标注与云端预测坐标同处 parser pdf_data 的 MediaBox 参考空间，而存储文档(doc/)是缩放预览，
    前端按存储文档尺寸做百分比定位，故所有框都需按 doc/ref 比例校正。无参考尺寸时回退 1.0 不缩放。"""
    doc_sizes = doc_page_sizes(doc_key, dataset_id)
    ref_sizes = annotation_ref_sizes(doc_key, dataset_id)

    def scale(page: int):
        i = page - 1
        if 0 <= i < len(doc_sizes) and 0 <= i < len(ref_sizes):
            rw, rh = ref_sizes[i]
            dw, dh = doc_sizes[i]
            if rw and rh and (abs(rw - dw) > 0.5 or abs(rh - dh) > 0.5):
                return dw / rw, dh / rh
        return 1.0, 1.0

    return scale


def annotation_ref_sizes(doc_key: str, dataset_id: int = None):
    """标注/预测坐标所在的参考页尺寸 [(w,h)...]（1-based 顺序）。
    来源优先级（图片与 PDF 通用，稳定）：
      1) parser doctree.file_content[].page_size（每页都带，图片类数据集也有）；
      2) 回退 doctree.pdf_data（base64 PDF）的 MediaBox（兼容老逻辑/无 file_content）；
      3) 都没有 → 返回 []（调用方不缩放）。带缓存。"""
    ck = f"ref:{dataset_id}:{doc_key}"
    if ck in _size_cache:
        return _size_cache[ck]
    import base64
    import fitz
    sizes = []
    try:
        _, par_dir, _ = dirs_for_doc(doc_key, dataset_id)
        pp = os.path.join(par_dir, doc_key + ".json")
        if os.path.exists(pp):
            with open(pp, "r", encoding="utf-8") as f:
                pj = json.load(f)
            doctree = pj.get("doctree") or {}
            # 1) file_content[].page_size（按 page_num 升序）
            fc = doctree.get("file_content") or []
            pages = []
            for c in fc:
                ps = (c or {}).get("page_size") or {}
                w, h = ps.get("width"), ps.get("height")
                if w and h:
                    pages.append((c.get("page_num", 0), float(w), float(h)))
            if pages:
                pages.sort(key=lambda t: t[0])
                sizes = [(w, h) for _n, w, h in pages]
            # 2) 回退 pdf_data MediaBox
            if not sizes:
                pdfb = doctree.get("pdf_data")
                if pdfb:
                    d = fitz.open(stream=base64.b64decode(pdfb), filetype="pdf")
                    sizes = [(d[i].rect.width, d[i].rect.height) for i in range(d.page_count)]
                    d.close()
    except Exception:  # noqa
        sizes = []
    _size_cache[ck] = sizes
    return sizes
