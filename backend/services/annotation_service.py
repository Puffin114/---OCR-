"""二次标注：框选坐标与 parser 文本节点求交匹配。

坐标约定：
- UI/标注使用 1-based pageNum；parser 使用 0-based pageno（parser_pageno = page_num - 1）。
- 框 box 与 parser box 均为 [x, y, w, h]，同一页面坐标系。
"""
import json
import os
from typing import Dict, List, Tuple

_parser_cache: Dict[str, dict] = {}

# 命中阈值：文本节点面积落在框内的占比达到该值才算被框选，避免边缘擦到的相邻文字混入
CONTAIN_RATIO = 0.6


def _load_parser(doc_key: str, dataset_id: int = None) -> dict:
    cache_key = f"{dataset_id}:{doc_key}"
    if cache_key in _parser_cache:
        return _parser_cache[cache_key]
    from services import dataset_service
    _, parser_dir, _ = dataset_service.dirs_for_doc(doc_key, dataset_id)
    path = os.path.join(parser_dir, doc_key + ".json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 控制缓存规模
    if len(_parser_cache) > 8:
        _parser_cache.clear()
    _parser_cache[cache_key] = data
    return data


def _rect_intersect(a: Tuple[float, float, float, float],
                    b: Tuple[float, float, float, float]) -> bool:
    ax2, ay2 = a[0] + a[2], a[1] + a[3]
    bx2, by2 = b[0] + b[2], b[1] + b[3]
    return not (a[0] > bx2 or b[0] > ax2 or a[1] > by2 or b[1] > ay2)


def _overlap_ratio(sel: Tuple[float, float, float, float],
                   nd: Tuple[float, float, float, float]) -> float:
    """交集面积 / 文本节点面积。"""
    ix = max(0.0, min(sel[0] + sel[2], nd[0] + nd[2]) - max(sel[0], nd[0]))
    iy = max(0.0, min(sel[1] + sel[3], nd[1] + nd[3]) - max(sel[1], nd[1]))
    inter = ix * iy
    area = max(nd[2] * nd[3], 1e-6)
    return inter / area


def page_nodes(doc_key: str, page_num: int, dataset_id: int = None) -> List[dict]:
    """返回某页（1-based）的文本节点：{text, box, layout_index}。"""
    data = _load_parser(doc_key, dataset_id)
    tree = data.get("doctree", {})
    nodes = tree.get("para_nodes", [])
    target = page_num - 1
    out = []
    for n in nodes:
        text = (n.get("text") or "").strip()
        if not text:
            continue
        for pos in n.get("position", []) or []:
            if pos.get("pageno") == target and pos.get("box"):
                out.append({
                    "text": text,
                    "box": pos["box"],
                    "layout_index": pos.get("layout_index", 0),
                })
                break
    return out


def recognize_box(doc_key: str, page_num: int, box: List[float], dataset_id: int = None) -> str:
    """框选识别：默认走实时 OCR（config.recognize_use_ocr=true）；否则用本地 parser 面积占比匹配，
    若本地 parser 无可用节点则自动回退 OCR（兼容无 parser 的上传数据集）。"""
    from config import get_config
    cfg = get_config()
    if getattr(cfg, "recognize_use_ocr", False):
        from services import cloud_service
        return cloud_service.ocr_region(doc_key, page_num, box, dataset_id)
    nodes = page_nodes(doc_key, page_num, dataset_id)
    if not nodes:
        # 本地无 parser 节点 → 兜底走 OCR
        from services import cloud_service
        return cloud_service.ocr_region(doc_key, page_num, box, dataset_id)
    rect = (box[0], box[1], box[2], box[3])
    hits = [nd for nd in nodes if _overlap_ratio(rect, tuple(nd["box"])) >= CONTAIN_RATIO]
    hits.sort(key=lambda x: (x["box"][1], x["box"][0], x["layout_index"]))
    return "".join(h["text"] for h in hits)


def _box_to_location(box):
    if not box:
        return []
    x, y, w, h = box
    return [{"x": x, "y": y}, {"x": x + w, "y": y},
            {"x": x + w, "y": y + h}, {"x": x, "y": y + h}]


def _value_tag(value, page_num, location):
    return {
        "text": value, "valueId": "", "editedText": value, "direction": "",
        "tagDetail": [{"id": "", "text": value, "pageNum": page_num, "location": location}],
        "types": [],
    }


def _new_node(field, label_id):
    return {
        "annotationId": "", "label": field, "labelId": label_id,
        "labelType": "structure", "resultClasses": [], "noNeedAnnotation": 0,
        "textTag": [{"tagId": "", "keyTag": {"text": "", "valueId": "", "editedText": "",
                                             "direction": "", "tagDetail": [], "types": None},
                     "valueTag": [], "property": []}],
        "tableTag": [], "extendTag": None,
    }


def _load_ann_data(doc_key, dataset_id):
    from services import dataset_service
    ann_dir, _, _ = dataset_service.dirs_for_doc(doc_key, dataset_id)
    path = os.path.join(ann_dir, doc_key + ".json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"annotations": [], "classifyInfo": {"annotationId": "", "labelList": None}}
    return path, data


def _persist(path, data, doc_key, dataset_id):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    _parser_cache.pop(f"{dataset_id}:{doc_key}", None)
    from db import get_conn
    with get_conn() as conn:
        if dataset_id is not None:
            conn.execute("UPDATE document SET has_annotation=1 WHERE dataset_id=? AND key=?",
                         (dataset_id, doc_key))
        else:
            conn.execute("UPDATE document SET has_annotation=1 WHERE key=?", (doc_key,))
        conn.commit()


def save_annotation(doc_key: str, field: str, label_id: str, value: str,
                    page_num: int, box: List[float] = None, dataset_id: int = None,
                    parent_field: str = None, parent_label_id: str = None,
                    group_index: int = None) -> dict:
    """写回标注文件。
    - 单字段（无 parent_field）：顶层 annotations[] 下单 valueTag 覆盖（兼容原逻辑）。
    - 组合子字段（有 parent_field）：写入父标注 textTag[0].property[] 下子节点的第 group_index 组 valueTag，
      保持 property 嵌套与多组结构，不在顶层新建子字段标注。"""
    path, data = _load_ann_data(doc_key, dataset_id)

    if parent_field:
        gi = group_index or 0
        # 找/建父标注（顶层）
        parent = None
        for a in data.get("annotations", []):
            if a.get("label") == parent_field or (parent_label_id and a.get("labelId") == parent_label_id):
                parent = a
                break
        if parent is None:
            parent = _new_node(parent_field, parent_label_id or "")
            data.setdefault("annotations", []).append(parent)
        if not parent.get("textTag"):
            parent["textTag"] = [{"tagId": "", "keyTag": {"text": "", "valueId": "", "editedText": "",
                                                          "direction": "", "tagDetail": [], "types": None},
                                  "valueTag": [], "property": []}]
        ptt = parent["textTag"][0]
        ptt.setdefault("property", [])
        # 找/建子节点
        sub = None
        for s in ptt["property"]:
            if isinstance(s, dict) and (s.get("label") == field or s.get("labelId") == label_id):
                sub = s
                break
        if sub is None:
            sub = _new_node(field, label_id)
            ptt["property"].append(sub)
        if not sub.get("textTag"):
            sub["textTag"] = [{"tagId": "", "keyTag": {"text": "", "valueId": "", "editedText": "",
                                                       "direction": "", "tagDetail": [], "types": None},
                               "valueTag": [], "property": []}]
        stt = sub["textTag"][0]
        vts = stt.setdefault("valueTag", [])
        # 补齐到 group_index
        while len(vts) <= gi:
            vts.append(_value_tag("", page_num, []))
        # location：有框用框；无框保留该组已有
        if box:
            location, loc_page = _box_to_location(box), page_num
        else:
            old = vts[gi].get("tagDetail") or [{}]
            location = (old[0].get("location") if old else []) or []
            loc_page = (old[0].get("pageNum") if old else page_num) or page_num
        vts[gi] = _value_tag(value, loc_page, location)
        _persist(path, data, doc_key, dataset_id)
        return {"ok": True, "doc_key": doc_key, "field": field, "group_index": gi, "value": value}

    # 单字段：原逻辑
    found = None
    for a in data.get("annotations", []):
        if a.get("label") == field or a.get("labelId") == label_id:
            found = a
            break
    if found is None:
        found = _new_node(field, label_id)
        found["textTag"] = []
        data.setdefault("annotations", []).append(found)

    location = []
    loc_page = page_num
    if box:
        location = _box_to_location(box)
    else:
        for tt in found.get("textTag", []) or []:
            for vt in tt.get("valueTag", []) or []:
                for det in vt.get("tagDetail", []) or []:
                    if det.get("location"):
                        location = det["location"]
                        loc_page = det.get("pageNum", page_num)
                        break
                if location:
                    break
            if location:
                break

    found["textTag"] = [{
        "tagId": "", "keyTag": {"text": "", "valueId": "", "editedText": "",
                                "direction": "", "tagDetail": [], "types": None},
        "valueTag": [_value_tag(value, loc_page, location)], "property": [],
    }]
    _persist(path, data, doc_key, dataset_id)
    return {"ok": True, "doc_key": doc_key, "field": field, "value": value}


def delete_annotation_group(doc_key: str, parent_field: str, group_index: int,
                            dataset_id: int = None) -> dict:
    """删除某组合父下第 group_index 组：移除其 property 下每个子节点的第 group_index 个 valueTag。"""
    path, data = _load_ann_data(doc_key, dataset_id)
    for a in data.get("annotations", []):
        if a.get("label") != parent_field:
            continue
        for tt in a.get("textTag", []) or []:
            for sub in tt.get("property", []) or []:
                if not isinstance(sub, dict):
                    continue
                for stt in sub.get("textTag", []) or []:
                    vts = stt.get("valueTag") or []
                    if 0 <= group_index < len(vts):
                        vts.pop(group_index)
    _persist(path, data, doc_key, dataset_id)
    return {"ok": True, "doc_key": doc_key, "parent_field": parent_field, "group_index": group_index}
