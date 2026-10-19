"""评测指标计算引擎：原始指标 + 应用自定义标准/人工复核后的重算。"""
import json
import re
from typing import Dict, List, Tuple

from config import get_config
from db import get_conn
from services import dataset_service

_PUNCT_RE = re.compile(r"[\s\u3000,，.。、;；:：!！?？'\"“”‘’()（）\[\]【】<>《》/\\|_\-—~`@#$%^&*+=]")
_CN_NUM = {"〇": "0", "零": "0", "一": "1", "二": "2", "两": "2", "三": "3", "四": "4",
           "五": "5", "六": "6", "七": "7", "八": "8", "九": "9", "十": "10"}


def _normalize(s: str, modes: List[str]) -> str:
    s = (s or "").strip()
    if "ignore_case" in modes:
        s = s.lower()
    if "trim_punct" in modes:
        s = _PUNCT_RE.sub("", s)
    if "date_normalize" in modes:
        digits = re.findall(r"\d+", s)
        if len(digits) >= 3:
            s = f"{int(digits[0]):04d}-{int(digits[1]):02d}-{int(digits[2]):02d}"
        elif digits:
            s = "-".join(str(int(d)) for d in digits)
    if "number_normalize" in modes:
        tmp = "".join(_CN_NUM.get(ch, ch) for ch in s)
        nums = re.findall(r"\d+(?:\.\d+)?", tmp)
        if nums:
            s = nums[0]
    return s


def _match(gt: str, pred: str, modes: List[str], regex: str = None) -> bool:
    if regex:
        try:
            mg = re.search(regex, gt or "")
            mp = re.search(regex, pred or "")
            if mg and mp:
                return mg.group(0) == mp.group(0)
        except re.error:
            pass
    g, p = _normalize(gt, modes), _normalize(pred, modes)
    if not g and not p:
        return True
    if "contains" in modes:
        return bool(g) and bool(p) and (g in p or p in g)
    return g == p


def _greedy_count(gts: List[str], preds: List[str], modes, regex) -> Tuple[int, int, int]:
    """返回 (tp, used_pred, matched_gt)。"""
    used = [False] * len(preds)
    tp = 0
    for g in gts:
        for i, p in enumerate(preds):
            if not used[i] and _match(g, p, modes, regex):
                used[i] = True
                tp += 1
                break
    return tp, sum(used), tp


def _dedup_by_norm(values: List[str], modes) -> Tuple[List[str], List[str]]:
    """按归一化后的值去重，保留首次出现的原始值。返回 (去重后原始值, 去重后归一化值)。"""
    seen = set()
    raw_out: List[str] = []
    norm_out: List[str] = []
    for v in values:
        key = _normalize(v, modes)
        if key in seen:
            continue
        seen.add(key)
        raw_out.append(v)
        norm_out.append(key)
    return raw_out, norm_out


def _load_criteria(task_id: int) -> Dict[str, dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM eval_criteria WHERE task_id=?", (task_id,)).fetchall()
    out = {}
    for r in rows:
        out[r["field"]] = {"modes": json.loads(r["modes"] or "[]"), "regex": r["regex"]}
    return out


def _criteria_for(field: str, crit: Dict[str, dict], default_mode: str) -> Tuple[List[str], str]:
    if field in crit:
        return crit[field]["modes"], crit[field]["regex"]
    if "*" in crit:
        return crit["*"]["modes"], crit["*"]["regex"]
    return [default_mode], None


def _modes_for(field: str, crit: Dict[str, dict], field_defaults: Dict[str, list],
               default_mode: str) -> Tuple[List[str], str]:
    """优先级：任务预设 criteria > 字段 eval_modes > 全局 default。"""
    if field in crit:
        return crit[field]["modes"], crit[field]["regex"]
    if "*" in crit:
        return crit["*"]["modes"], crit["*"]["regex"]
    dm = field_defaults.get(field)
    if dm:
        return dm, None
    return [default_mode], None


def _load_overrides(task_id: int) -> Dict[Tuple[str, str], str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM review_override WHERE task_id=?", (task_id,)).fetchall()
    return {(r["doc_key"], r["field"]): r["verdict"] for r in rows}


def _task_predictions(task_id: int) -> Dict[str, Dict[str, List[str]]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT doc_key, parsed_json FROM prediction WHERE task_id=?",
                            (task_id,)).fetchall()
    return {r["doc_key"]: json.loads(r["parsed_json"] or "{}") for r in rows}


def _prediction_groups(task_id: int) -> Dict[str, Dict[str, List[Dict[str, str]]]]:
    """组合字段预测分组：{doc_key: {父字段名: [ {子字段名: 值}, ... ]}}。
    读 prediction.raw_json 的 result.extractResult[].data.comboKey[父]（本就是分组列表）。"""
    with get_conn() as conn:
        rows = conn.execute("SELECT doc_key, raw_json FROM prediction WHERE task_id=?",
                            (task_id,)).fetchall()
    out: Dict[str, Dict[str, List[Dict[str, str]]]] = {}
    for r in rows:
        raw = json.loads(r["raw_json"] or "{}")
        doc_groups: Dict[str, List[Dict[str, str]]] = {}
        if isinstance(raw, dict) and not raw.get("error"):
            for doc in (raw.get("result") or {}).get("extractResult") or []:
                data = (doc or {}).get("data") or {}
                for parent, groups in (data.get("comboKey") or {}).items():
                    glist = groups if isinstance(groups, list) else [groups]
                    acc = doc_groups.setdefault(parent, [])
                    for grp in glist:
                        if not isinstance(grp, dict):
                            continue
                        rec: Dict[str, str] = {}
                        for sub_name, cell in grp.items():
                            if isinstance(cell, dict):
                                rec[sub_name] = (cell.get("value") or cell.get("word") or "").strip()
                        acc.append(rec)
        out[r["doc_key"]] = doc_groups
    return out


def compute(task_id: int, review: bool = False) -> Dict:
    """计算并落库指标。review=False 原始；review=True 应用标准+复核。"""
    cfg = get_config()
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM eval_task WHERE id=?", (task_id,)).fetchone()
        if not task:
            raise ValueError("评测任务不存在")
        labels = conn.execute(
            "SELECT label_id, label_name, parent_id, eval_modes FROM label WHERE dataset_id=? ORDER BY display_order",
            (task["dataset_id"],)).fetchall()
    group_ids = {l["parent_id"] for l in labels if l["parent_id"]}
    fields = [l["label_name"] for l in labels if l["label_id"] not in group_ids]
    # 任务指定字段集（预览页所选）：与非组合字段取交集
    task_fields = json.loads(task["fields"] or "[]") if "fields" in task.keys() else []
    if task_fields:
        fields = [f for f in fields if f in set(task_fields)]
    # 字段级默认匹配规则（创建数据集时配的评测逻辑）
    field_defaults = {l["label_name"]: (json.loads(l["eval_modes"]) if l["eval_modes"] else None)
                      for l in labels}
    doc_keys = json.loads(task["doc_keys"] or "[]")

    # 原始与复核都加载预设评测标准(criteria)作为基准；人工覆盖仅复核时叠加
    crit = _load_criteria(task_id)
    overrides = _load_overrides(task_id) if review else {}
    preds_all = _task_predictions(task_id)

    agg = {f: {"tp": 0, "fp": 0, "fn": 0, "count": 0} for f in fields}

    for dk in doc_keys:
        gt_map = dataset_service.annotation_values(dk, task["dataset_id"])
        pred_map = preds_all.get(dk, {})
        for f in fields:
            gts = gt_map.get(f, [])
            preds = pred_map.get(f, [])
            if gts:
                agg[f]["count"] += 1
            modes, regex = _modes_for(f, crit, field_defaults, cfg.default_match_mode)
            gts_d, _ = _dedup_by_norm(gts, modes)
            preds_d, _ = _dedup_by_norm(preds, modes)
            ov = overrides.get((dk, f))
            if ov == "success":
                agg[f]["tp"] += max(len(gts_d), 1)
                continue
            if ov == "fail":
                agg[f]["fn"] += max(len(gts_d), 1)
                agg[f]["fp"] += len(preds_d)
                continue
            tp, used_pred, _ = _greedy_count(gts_d, preds_d, modes, regex)
            agg[f]["tp"] += tp
            agg[f]["fp"] += len(preds_d) - used_pred
            agg[f]["fn"] += len(gts_d) - tp

    def _prf(tp, fp, fn):
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        return round(p * 100, 2), round(r * 100, 2), round(f1 * 100, 2)

    # 写库
    rv = 1 if review else 0
    with get_conn() as conn:
        conn.execute("DELETE FROM metric WHERE task_id=? AND review=?", (task_id, rv))
        tot = {"tp": 0, "fp": 0, "fn": 0, "count": 0}
        rows_out = []
        for f in fields:
            a = agg[f]
            for k in tot:
                tot[k] += a[k]
            p, r, f1 = _prf(a["tp"], a["fp"], a["fn"])
            conn.execute(
                "INSERT INTO metric(task_id,review,scope,data_count,tp,fp,fn,precision,recall,f1)"
                " VALUES(?,?,?,?,?,?,?,?,?,?)",
                (task_id, rv, f, a["count"], a["tp"], a["fp"], a["fn"], p, r, f1))
            rows_out.append({"field": f, "data_count": a["count"],
                             "precision": p, "recall": r, "f1": f1})
        op, orr, of1 = _prf(tot["tp"], tot["fp"], tot["fn"])
        conn.execute(
            "INSERT INTO metric(task_id,review,scope,data_count,tp,fp,fn,precision,recall,f1)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (task_id, rv, "overall", tot["count"], tot["tp"], tot["fp"], tot["fn"], op, orr, of1))
        conn.commit()

    return {
        "overall": {"precision": op, "recall": orr, "f1": of1, "data_count": tot["count"]},
        "fields": rows_out,
    }


def _task_field_meta(task) -> Tuple[Dict[str, str], Dict[str, str]]:
    """从任务存的 field_defs 解析 {字段名: 父名} 与 {字段名: 颜色}。
    任务无 field_defs 时返回空 dict（调用方回退 label 表）。"""
    name2parent: Dict[str, str] = {}
    name2color: Dict[str, str] = {}
    try:
        raw = task["field_defs"] if "field_defs" in task.keys() else None
    except Exception:
        raw = None
    if not raw:
        return name2parent, name2color
    try:
        defs = json.loads(raw)
    except Exception:
        return name2parent, name2color
    for d in defs or []:
        nm = (d.get("name") or "").strip()
        if not nm:
            continue
        name2parent[nm] = d.get("parent") or None
        if d.get("color"):
            name2color[nm] = d.get("color")
    return name2parent, name2color


def get_metrics(task_id: int) -> Dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM metric WHERE task_id=? ORDER BY review", (task_id,)).fetchall()
        task = conn.execute("SELECT * FROM eval_task WHERE id=?", (task_id,)).fetchone()
        labels = conn.execute(
            "SELECT label_id,label_name,parent_id FROM label WHERE dataset_id=?",
            (task["dataset_id"],)).fetchall() if task else []
    id2name = {l["label_id"]: l["label_name"] for l in labels}
    name2parent = {l["label_name"]: id2name.get(l["parent_id"]) for l in labels}
    fd_parent, _ = _task_field_meta(task) if task else ({}, {})
    out = {"original": {"overall": None, "fields": []},
           "reviewed": {"overall": None, "fields": []}}
    for r in rows:
        bucket = out["reviewed"] if r["review"] else out["original"]
        parent = fd_parent.get(r["scope"], name2parent.get(r["scope"])) if r["scope"] != "overall" else None
        item = {"field": r["scope"], "data_count": r["data_count"],
                "precision": r["precision"], "recall": r["recall"], "f1": r["f1"],
                "parent": parent}
        if r["scope"] == "overall":
            bucket["overall"] = item
        else:
            bucket["fields"].append(item)
    return out


def get_performance(task_id: int) -> Dict:
    """性能指标：抽取平均耗时（切片/文件）。overall + 每文档明细。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT doc_key,elapsed_ms,slice_count FROM prediction WHERE task_id=? ORDER BY id",
            (task_id,)).fetchall()
    docs = []
    total_ms = 0.0
    total_slices = 0
    for r in rows:
        ms = float(r["elapsed_ms"] or 0)
        sl = int(r["slice_count"] or 0)
        total_ms += ms
        total_slices += sl
        docs.append({
            "doc_key": r["doc_key"], "slice_count": sl, "elapsed_ms": round(ms, 2),
            "avg_per_slice_ms": round(ms / sl, 2) if sl else 0.0,
        })
    n_docs = len(docs)
    overall = {
        "doc_count": n_docs,
        "slice_count": total_slices,
        "total_ms": round(total_ms, 2),
        "avg_per_slice_ms": round(total_ms / total_slices, 2) if total_slices else 0.0,
        "avg_per_file_ms": round(total_ms / n_docs, 2) if n_docs else 0.0,
    }
    return {"overall": overall, "documents": docs}


def compare_table(task_id: int) -> Dict:
    """查看评测结果：逐文档的 字段|标注|预测 对比 + 命中判定。"""
    cfg = get_config()
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM eval_task WHERE id=?", (task_id,)).fetchone()
        labels = conn.execute(
            "SELECT label_id,label_name,label_color,parent_id,eval_modes FROM label WHERE dataset_id=? ORDER BY display_order",
            (task["dataset_id"],)).fetchall()
    group_ids = {l["parent_id"] for l in labels if l["parent_id"]}
    fields = [(l["label_name"], l["label_color"]) for l in labels if l["label_id"] not in group_ids]
    task_fields = json.loads(task["fields"] or "[]") if "fields" in task.keys() else []
    if task_fields:
        fields = [(n, c) for (n, c) in fields if n in set(task_fields)]
    id2name = {l["label_id"]: l["label_name"] for l in labels}
    name2parent = {l["label_name"]: (id2name.get(l["parent_id"]) if l["parent_id"] else None)
                   for l in labels}
    fd_parent, fd_color = _task_field_meta(task)
    field_defaults = {l["label_name"]: (json.loads(l["eval_modes"]) if l["eval_modes"] else None)
                      for l in labels}
    doc_keys = json.loads(task["doc_keys"] or "[]")
    crit = _load_criteria(task_id)
    overrides = _load_overrides(task_id)
    preds_all = _task_predictions(task_id)
    pred_groups_all = _prediction_groups(task_id)

    def _eff_parent(f):
        return fd_parent.get(f, name2parent.get(f))

    # 按父字段聚合组合子字段（保序）；单个字段单独一列
    singles = [(f, c) for (f, c) in fields if not _eff_parent(f)]
    combo_order: List[str] = []
    combo_subs: Dict[str, List[Tuple[str, str]]] = {}
    for f, c in fields:
        p = _eff_parent(f)
        if p:
            if p not in combo_subs:
                combo_subs[p] = []
                combo_order.append(p)
            combo_subs[p].append((f, c))

    def _row(f, color, parent, gt_val, pred_val, dk, group=None):
        modes, regex = _modes_for(f, crit, field_defaults, cfg.default_match_mode)
        if isinstance(gt_val, list):
            gts, preds = list(gt_val), list(pred_val)
        else:
            gts = [gt_val] if gt_val else []
            preds = [pred_val] if pred_val else []
        gts_d, gts_norm = _dedup_by_norm(gts, modes)
        preds_d, preds_norm = _dedup_by_norm(preds, modes)
        if not gts and not preds:
            auto_hit = True                       # 空-空 → 一致
        elif gts:
            tp, _, _ = _greedy_count(gts_d, preds_d, modes, regex)
            auto_hit = tp >= len(gts_d) and tp > 0
        else:
            auto_hit = (len(preds) == 0)          # 标注空、预测有值 → 不一致
        ov = overrides.get((dk, f))
        final_hit = (ov == "success") if ov else auto_hit
        row = {
            "field": f, "color": fd_color.get(f, color), "parent": parent,
            "annotation": " | ".join(gts), "prediction": " | ".join(preds),
            "annotation_norm": " | ".join(gts_norm),
            "prediction_norm": " | ".join(preds_norm),
            "auto_hit": auto_hit, "override": ov, "hit": final_hit,
        }
        if group is not None:
            row["group"] = group
        return row

    docs = []
    for dk in doc_keys:
        gt_map = dataset_service.annotation_values(dk, task["dataset_id"])
        pred_map = preds_all.get(dk, {})
        gt_groups = dataset_service.annotation_groups(dk, task["dataset_id"])
        pred_groups = pred_groups_all.get(dk, {})
        rows = []
        # 单个字段：维持合并展示
        for f, color in singles:
            rows.append(_row(f, color, None, gt_map.get(f, []), pred_map.get(f, []), dk))
        # 组合字段：按组(行)展开，GT 第 g 组对预测第 g 组，缺组置空
        for p in combo_order:
            subs = combo_subs[p]
            g_gt = gt_groups.get(p, [])
            g_pred = pred_groups.get(p, [])
            n = max(len(g_gt), len(g_pred))
            for g in range(n):
                gt_rec = g_gt[g] if g < len(g_gt) else {}
                pred_rec = g_pred[g] if g < len(g_pred) else {}
                for f, color in subs:
                    rows.append(_row(f, color, p, gt_rec.get(f, ""), pred_rec.get(f, ""),
                                     dk, group=g + 1))
        docs.append({"doc_key": dk, "rows": rows})
    return {"fields": [f for f, _ in fields], "documents": docs}
