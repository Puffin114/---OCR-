"""公有云「文档抽取」OpenAPI 接入：token / submit / poll，含限流与重试。"""
import base64
import json
import os
import re
import time
from typing import Dict, List, Optional

import httpx

from config import get_config

_token_cache = {"token": None, "exp": 0}


class QuotaGuardError(Exception):
    pass


class CloudError(Exception):
    pass


def get_token(cfg=None) -> str:
    cfg = cfg or get_config()
    now = time.time()
    if _token_cache["token"] and _token_cache["exp"] > now + 60:
        return _token_cache["token"]
    if not cfg.api_key or not cfg.secret_key:
        raise CloudError("未配置 api_key/secret_key，请在 config.yaml 填写")
    params = {
        "grant_type": "client_credentials",
        "client_id": cfg.api_key,
        "client_secret": cfg.secret_key,
    }
    r = httpx.get(cfg.token_url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    tok = data.get("access_token")
    if not tok:
        raise CloudError(f"获取 token 失败：{data}")
    _token_cache["token"] = tok
    _token_cache["exp"] = now + int(data.get("expires_in", 2592000))
    return tok


def _build_manifest(labels: List[dict], fields: Optional[List[str]] = None) -> str:
    """生成官方 manifest：[{key, description, parentKey}]，带组合字段父子层级。
    fields 非空时仅包含所选字段（并自动带上其父容器）。"""
    id2name = {lb.get("label_id"): lb.get("label_name") for lb in labels}
    selected = set(fields) if fields else None
    items: List[dict] = []
    included = set()

    def add(lb):
        name = lb.get("label_name")
        if not name or name in included:
            return
        pid = lb.get("parent_id")
        parent_key = id2name.get(pid, "root") if pid else "root"
        items.append({"key": name,
                      "description": lb.get("label_extend") or name,
                      "parentKey": parent_key})
        included.add(name)

    for lb in labels:
        name = lb.get("label_name")
        if selected is not None and name not in selected:
            continue
        pid = lb.get("parent_id")
        if pid:
            parent = next((x for x in labels if x.get("label_id") == pid), None)
            if parent:
                add(parent)
        add(lb)
    return json.dumps(items, ensure_ascii=False)


def _submit(file_path: str, token: str, cfg, manifest: Optional[str]) -> str:
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    data = {"file": b64, "fileName": os.path.basename(file_path)}
    if cfg.manifest_version_id:
        data["manifestVersionId"] = cfg.manifest_version_id
    elif manifest:
        data["manifest"] = manifest
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    r = httpx.post(f"{cfg.submit_url}?access_token={token}", data=data,
                   headers=headers, timeout=120)
    r.raise_for_status()
    resp = r.json()
    if resp.get("error_code"):
        raise CloudError(f"提交失败：{resp.get('error_code')} {resp.get('error_msg')}")
    task_id = (resp.get("result") or {}).get("taskId")
    if not task_id:
        raise CloudError(f"提交未返回 taskId：{resp}")
    return task_id


def _poll(task_id: str, token: str, cfg) -> dict:
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    deadline = time.time() + cfg.poll_timeout_sec
    time.sleep(min(cfg.poll_interval_sec, cfg.poll_timeout_sec))
    while time.time() < deadline:
        r = httpx.post(f"{cfg.result_url}?access_token={token}",
                       data={"taskId": task_id}, headers=headers, timeout=60)
        r.raise_for_status()
        resp = r.json()
        if resp.get("error_code"):
            raise CloudError(f"取结果失败：{resp.get('error_code')} {resp.get('error_msg')}")
        result = resp.get("result") or {}
        status = str(result.get("status", "")).lower()
        if status == "failed":
            raise CloudError(f"抽取失败：{result.get('reason') or resp.get('error_msg') or '未知原因'}")
        # 完成则返回（官方 Success；兼容其它完成信号）
        if status in ("success", "finished", "done", "2") or result.get("retCode") == 0:
            return resp
        if result and ("extractResult" in result or "data" in result or "fields" in result):
            return resp
        time.sleep(5)
    raise CloudError(f"轮询超时 task_id={task_id}")


def manifest_from_defs(field_defs: List[dict]) -> str:
    """由前端字段定义 [{name,description,parent,include}] 生成 manifest（仅含勾选字段，带父层级）。"""
    labels = [{"label_id": d.get("name"), "label_name": d.get("name"),
               "label_extend": d.get("description"), "parent_id": d.get("parent")}
              for d in field_defs if d.get("name")]
    fields = [d["name"] for d in field_defs if d.get("name") and d.get("include", True)]
    return _build_manifest(labels, fields)


def ocr_region(doc_key: str, page_num: int, box: List[float], dataset_id: int = None) -> str:
    """对框选区域实时 OCR（通用文字识别）。box 为页面点坐标 [x,y,w,h]。"""
    from services import dataset_service
    import fitz  # PyMuPDF
    cfg = get_config()
    path = dataset_service.doc_file_path(doc_key, dataset_id)
    doc = fitz.open(path)
    try:
        if page_num < 1 or page_num > doc.page_count:
            return ""
        x, y, w, h = box
        clip = fitz.Rect(x, y, x + w, y + h)
        pix = doc[page_num - 1].get_pixmap(matrix=fitz.Matrix(3, 3), clip=clip, alpha=False)
        png = pix.tobytes("png")
    finally:
        doc.close()
    if not png:
        return ""
    token = get_token(cfg)
    b64 = base64.b64encode(png).decode("utf-8")
    r = httpx.post(f"{cfg.ocr_url}?access_token={token}", data={"image": b64},
                   headers={"Content-Type": "application/x-www-form-urlencoded"}, timeout=30)
    r.raise_for_status()
    resp = r.json()
    if resp.get("error_code"):
        raise CloudError(f"OCR 失败：{resp.get('error_code')} {resp.get('error_msg')}")
    words = [w.get("words", "") for w in (resp.get("words_result") or [])]
    return "".join(words)


def parse_result(resp: dict) -> Dict[str, List[str]]:
    """按真实「文档抽取」返回解析出 {字段: [值...]}。

    真实结构：result.extractResult[*].data.{singleKey, comboKey}
      - singleKey: {字段名: [ {value|word, ...} ]}         普通字段（可多值）
      - comboKey:  {母字段名: [ {子字段名: {value|word}} ]}  组合字段（展开子字段）
    评测对比的是子字段/非组合字段，故母字段本身不写入。
    若无 extractResult，回退到旧的顶层猜测逻辑（兼容其它返回形态）。
    """
    out: Dict[str, List[str]] = {}

    def _add(name, value):
        if name and value is not None and str(value).strip():
            out.setdefault(str(name), []).append(str(value).strip())

    def _val(item):
        if isinstance(item, dict):
            return item.get("value") or item.get("word") or item.get("text")
        return item

    result = resp.get("result") or {}
    extract = result.get("extractResult")
    if isinstance(extract, list) and extract:
        for doc in extract:
            data = (doc or {}).get("data") or {}
            for name, items in (data.get("singleKey") or {}).items():
                for it in (items if isinstance(items, list) else [items]):
                    _add(name, _val(it))
            for _parent, groups in (data.get("comboKey") or {}).items():
                for grp in (groups if isinstance(groups, list) else [groups]):
                    if isinstance(grp, dict):
                        for sub_name, sub_val in grp.items():
                            _add(sub_name, _val(sub_val))
        return out

    # 兜底：旧/异常结构的顶层猜测
    candidates = []
    for k in ("extractResult", "data", "fields", "results"):
        v = result.get(k)
        if v:
            candidates.append(v)
    if not candidates and isinstance(result, (list, dict)):
        candidates.append(result)

    for cand in candidates:
        if isinstance(cand, dict):
            for name, val in cand.items():
                if isinstance(val, dict):
                    _add(name, val.get("value") or val.get("text") or val.get("word"))
                elif isinstance(val, list):
                    for it in val:
                        if isinstance(it, dict):
                            _add(name, it.get("value") or it.get("text") or it.get("word"))
                        else:
                            _add(name, it)
                else:
                    _add(name, val)
        elif isinstance(cand, list):
            for it in cand:
                if isinstance(it, dict):
                    name = it.get("key") or it.get("fieldName") or it.get("name") or it.get("label")
                    val = it.get("value") or it.get("text") or it.get("word")
                    if isinstance(val, list):
                        for v in val:
                            _add(name, v.get("value") if isinstance(v, dict) else v)
                    else:
                        _add(name, val)
    return out


def _slice_count(file_path: str) -> int:
    """文档切片数（PDF/图片页数），失败兜底 1。"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(file_path)
        n = doc.page_count
        doc.close()
        return max(n, 1)
    except Exception:  # noqa
        return 1


def run_extract(doc_paths: List[str], labels: List[dict], on_progress=None,
                doc_keys: Optional[List[str]] = None,
                fields: Optional[List[str]] = None,
                manifest_override: Optional[str] = None) -> Dict[str, dict]:
    """逐篇提交并轮询。返回 {basename: {raw, parsed, elapsed_ms, slice_count}}。"""
    cfg = get_config()
    token = get_token(cfg)
    manifest = manifest_override
    if manifest is None and not cfg.manifest_version_id and cfg.use_local_manifest_as_fallback:
        manifest = _build_manifest(labels, fields)

    interval = 1.0 / cfg.submit_qps if cfg.submit_qps > 0 else 0.5
    results: Dict[str, dict] = {}
    for i, p in enumerate(doc_paths):
        if on_progress:
            on_progress(i, len(doc_paths), os.path.basename(p))
        slices = _slice_count(p)
        t0 = time.perf_counter()
        for attempt in range(cfg.max_retries + 1):
            try:
                task_id = _submit(p, token, cfg, manifest)
                resp = _poll(task_id, token, cfg)
                results[os.path.basename(p)] = {
                    "raw": resp, "parsed": parse_result(resp),
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                    "slice_count": slices}
                break
            except Exception as e:  # noqa
                if attempt >= cfg.max_retries:
                    results[os.path.basename(p)] = {
                        "raw": {"error": str(e)}, "parsed": {},
                        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 2),
                        "slice_count": slices}
                else:
                    time.sleep(2)
        time.sleep(interval)
    return results
