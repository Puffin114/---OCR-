"""Extract 场景数据回流：连库查文档 → 从 BOS 下载 doc+parser → 去重 → 组装为回流数据集。

安全约定（用户强制要求）：DB 密码、BOS AK/SK 仅随本次请求传入，保存在本次回流任务的
内存上下文（局部变量）中，任务结束即释放；严禁写入 config.yaml、数据库、日志或任何持久化介质。
"""
import json
import os
import re
import threading
import time
import uuid

from config import get_config
from db import get_conn
from services import dataset_service

# Extract 场景连接配置 —— 已脱敏；内网地址/库/只读账号/桶请替换为自己的（密码/AK/SK 运行时单次传入）
EXTRACT_SCENE = {
    "label": "信息提取 Extract",
    "db_host": "<YOUR_DB_HOST>",
    "db_port": 8102,
    "db_name": "<YOUR_DB_NAME>",
    "db_user": "<YOUR_DB_READONLY_USER>",
    "bos_host": "bj.bcebos.com",
    "bos_bucket": "<YOUR_BOS_BUCKET>",
}

# 内存任务表：job_id -> 进度字典。随进程生命周期存在，不持久化。
_JOBS = {}
_JOBS_LOCK = threading.Lock()


def _safe_name(s: str) -> str:
    return re.sub(r"[^\w.\-]", "_", str(s))[:60]


def _new_job() -> str:
    job_id = uuid.uuid4().hex[:16]
    with _JOBS_LOCK:
        _JOBS[job_id] = {"status": "running", "total": 0, "done": 0,
                         "success": 0, "skipped": 0, "missing": [],
                         "message": "", "dataset_id": None}
    return job_id


def _update_job(job_id: str, **kw):
    with _JOBS_LOCK:
        if job_id in _JOBS:
            _JOBS[job_id].update(kw)


def get_job(job_id: str):
    with _JOBS_LOCK:
        j = _JOBS.get(job_id)
        return dict(j) if j else None


def _existing_backflow_doc_ids() -> set:
    """已回流过的 doc_id 集合（跨所有 backflow 数据集，用文档 key 去 .pdf 近似）。"""
    ids = set()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT doc.key AS key FROM document doc JOIN dataset d ON doc.dataset_id=d.id "
            "WHERE d.source='backflow'").fetchall()
    for r in rows:
        k = r["key"]
        ids.add(k[:-4] if k.endswith(".pdf") else k)
    return ids


def _connect_db(password: str):
    import pymysql  # 延迟导入：未安装依赖时不影响应用启动
    return pymysql.connect(
        host=EXTRACT_SCENE["db_host"], port=EXTRACT_SCENE["db_port"],
        user=EXTRACT_SCENE["db_user"], password=password,
        database=EXTRACT_SCENE["db_name"], charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=15, read_timeout=60,
    )


def _bos_client(ak: str, sk: str):
    from baidubce.auth.bce_credentials import BceCredentials
    from baidubce.bce_client_configuration import BceClientConfiguration
    from baidubce.services.bos.bos_client import BosClient
    config = BceClientConfiguration(
        credentials=BceCredentials(ak, sk),
        endpoint=EXTRACT_SCENE["bos_host"])
    return BosClient(config)


def _table_columns(cur, table):
    cur.execute(f"SHOW COLUMNS FROM {table}")
    cols = set()
    for row in cur.fetchall():
        cols.add(row.get("Field") if isinstance(row, dict) else row[0])
    return cols


def _query_docs(db_password, user_id, date_from, date_to, limit):
    """仅查 t_extract_doc（避免对任务↔文档 join 的强依赖）。先探测真实列名，
    仅取存在的列并自适应筛选/排序，规避列名差异导致整表查询失败。"""
    conn = _connect_db(db_password)
    try:
        with conn.cursor() as cur:
            cols = _table_columns(cur, "t_extract_doc")
            select_cols = ["d.id AS doc_id", "d.user_id AS user_id"]
            for c in ("user_type", "file_name", "file_path", "file_url"):
                if c in cols:
                    select_cols.append(f"d.{c} AS {c}")
            where = []
            params = []
            if "deleted_at" in cols:
                where.append("d.deleted_at IS NULL")
            if user_id and "user_id" in cols:
                where.append("d.user_id = %s"); params.append(user_id)
            if date_from and "created_at" in cols:
                where.append("d.created_at >= %s"); params.append(date_from)
            if date_to and "created_at" in cols:
                where.append("d.created_at < %s"); params.append(date_to)
            order = "d.pk DESC" if "pk" in cols else "d.id DESC"
            sql = ("SELECT " + ", ".join(select_cols) + " FROM t_extract_doc d"
                   + ((" WHERE " + " AND ".join(where)) if where else "")
                   + f" ORDER BY {order} LIMIT %s")
            params.append(int(limit))
            cur.execute(sql, params)
            return list(cur.fetchall())
    finally:
        conn.close()


def _list_keys(bos, prefix, limit=200):
    resp = bos.list_objects(EXTRACT_SCENE["bos_bucket"], prefix=prefix, max_keys=limit)
    return [obj.key for obj in (getattr(resp, "contents", None) or [])]


def _download_key(bos, key: str, dest: str):
    bos.get_object_to_file(EXTRACT_SCENE["bos_bucket"], key, dest)


def _download_url(url: str, dest: str):
    import httpx
    with httpx.stream("GET", url, timeout=120, follow_redirects=True) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(1024 * 1024):
                f.write(chunk)


_IMAGE_EXTS = ("jpg", "jpeg", "png", "tif", "tiff", "bmp", "webp", "gif")


def _fetch_doc(bos, r, doc_dir, par_dir):
    """返回 (ok, reason)。以 DB 的 file_path 作为 BOS 前缀（兼容 extract_doc/ 与 paas_extract_doc/），
    优先下转换后统一 PDF，其次原始图片；解析 JSON 一并取回。file_url 为兜底。"""
    doc_id = str(r["doc_id"])
    uid = r.get("user_id")
    fp = (r.get("file_path") or "").strip().rstrip("/")
    prefix = (fp + "/") if fp else f"extract_doc/{uid}/{doc_id}/"
    list_err = None
    keys = None
    try:
        keys = _list_keys(bos, prefix)
    except Exception as e:  # noqa
        list_err = f"{type(e).__name__}: {e}"
    if keys:
        names = {k: os.path.basename(k) for k in keys}
        # 优先转换后的统一 PDF；其次任一 PDF；再次原始图片（平台可渲染图片）
        chosen = next((k for k, n in names.items() if n == f"{doc_id}.pdf"), None) \
            or next((k for k in keys if k.lower().endswith(".pdf")), None) \
            or next((k for k in keys if k.lower().rsplit(".", 1)[-1] in _IMAGE_EXTS), None)
        if not chosen:
            sample = ", ".join(list(names.values())[:6])
            return False, f"目录内无可用文件（示例: {sample or '空'}）"
        ext = os.path.splitext(chosen)[1] or ".pdf"
        doc_name = f"{doc_id}{ext}"
        try:
            _download_key(bos, chosen, os.path.join(doc_dir, doc_name))
        except Exception as e:  # noqa
            return False, f"下载失败 {type(e).__name__}: {e}"
        parser_key = next((k for k, n in names.items() if n == f"{doc_id}.json"), None)
        if parser_key:
            try:
                _download_key(bos, parser_key, os.path.join(par_dir, f"{doc_name}.json"))
            except Exception:
                pass
        return True, ""
    url = r.get("file_url")
    if url:
        try:
            _download_url(url, os.path.join(doc_dir, f"{doc_id}.pdf"))
            return True, ""
        except Exception as e:  # noqa
            return False, f"签名URL下载失败 {type(e).__name__}: {e}"
    return False, f"列目录失败且无file_url（list错误: {list_err or 'n/a'}）"


def _safe_list(bos, prefix, limit=10):
    try:
        keys = _list_keys(bos, prefix, limit)
        return {"count": len(keys), "keys": keys[:limit]}
    except Exception as e:  # noqa
        return {"error": f"{type(e).__name__}: {e}"}


def _mask_row(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        s = "" if v is None else str(v)
        if k == "file_url" and s:
            out[k] = s.split("?")[0]  # 去掉签名参数，只留 host+path 看路径规律
        elif len(s) > 200:
            out[k] = s[:200] + "…"
        else:
            out[k] = s
    return out


def probe_extract(db_password, ak, sk, user_id=None, sample=5) -> dict:
    """探测诊断：不下载、不建数据集。返回样本文档的 DB 字段 + 各候选 BOS 前缀的列目录结果，
    用于定位到底是「字段/路径映射错」还是「桶不可见/无权限」。"""
    sample = max(1, min(int(sample or 5), 10))
    out = {"db": {}, "bos": {}, "errors": []}
    rows = []
    try:
        conn = _connect_db(db_password)
        try:
            with conn.cursor() as cur:
                cols = sorted(_table_columns(cur, "t_extract_doc"))
                out["db"]["columns"] = cols
                wanted = [c for c in ("id", "pk", "user_id", "user_type", "cloud_id",
                                      "app_id", "file_name", "file_path", "file_url",
                                      "created_at", "deleted_at") if c in cols]
                sel = ", ".join(f"d.{c}" for c in wanted) or "d.*"
                where = "WHERE d.deleted_at IS NULL" if "deleted_at" in cols else ""
                params = []
                if user_id and "user_id" in cols:
                    where = (where + " AND" if where else "WHERE") + " d.user_id=%s"
                    params.append(user_id)
                order = "d.pk DESC" if "pk" in cols else "d.id DESC"
                sql = f"SELECT {sel} FROM t_extract_doc d {where} ORDER BY {order} LIMIT %s"
                params.append(sample)
                cur.execute(sql, params)
                rows = list(cur.fetchall())
                out["db"]["sample"] = [_mask_row(r) for r in rows]

                # 为「分场景」定位：列出所有表、任务表结构与样本（场景字段通常在任务表）
                try:
                    cur.execute("SHOW TABLES")
                    out["db"]["tables"] = [(list(x.values())[0] if isinstance(x, dict) else x[0])
                                           for x in cur.fetchall()]
                except Exception as e:  # noqa
                    out["errors"].append(f"SHOW TABLES: {type(e).__name__}: {e}")
                try:
                    tcols = sorted(_table_columns(cur, "t_extract_task"))
                    out["db"]["task_columns"] = tcols
                    twanted = [c for c in ("id", "pk", "user_id", "name", "task_type",
                                           "source_type", "manifest_version_id", "scene_version_id",
                                           "extract_label_info", "status", "created_at") if c in tcols]
                    tsel = ", ".join(f"t.{c}" for c in twanted) or "t.*"
                    twhere = "WHERE t.deleted_at IS NULL" if "deleted_at" in tcols else ""
                    tparams = []
                    if user_id and "user_id" in tcols:
                        twhere = (twhere + " AND" if twhere else "WHERE") + " t.user_id=%s"
                        tparams.append(user_id)
                    torder = "t.pk DESC" if "pk" in tcols else "t.id DESC"
                    cur.execute(f"SELECT {tsel} FROM t_extract_task t {twhere} ORDER BY {torder} LIMIT %s",
                                tparams + [sample])
                    out["db"]["task_sample"] = [_mask_row(r) for r in cur.fetchall()]
                except Exception as e:  # noqa
                    out["errors"].append(f"t_extract_task: {type(e).__name__}: {e}")
                try:
                    rcols = sorted(_table_columns(cur, "t_extract_task_doc"))
                    out["db"]["task_doc_columns"] = rcols
                    cur.execute("SELECT * FROM t_extract_task_doc LIMIT %s", (sample,))
                    out["db"]["task_doc_sample"] = [_mask_row(r) for r in cur.fetchall()]
                except Exception as e:  # noqa
                    out["errors"].append(f"t_extract_task_doc: {type(e).__name__}: {e}")
        finally:
            conn.close()
    except Exception as e:  # noqa
        out["errors"].append(f"DB: {type(e).__name__}: {e}")

    try:
        bos = _bos_client(ak, sk)
        probes = {"extract_doc/": _safe_list(bos, "extract_doc/", 10)}
        for r in rows:
            doc_id = str(r.get("id") or r.get("doc_id") or "")
            uid = r.get("user_id")
            if uid is not None:
                probes[f"extract_doc/{uid}/"] = _safe_list(bos, f"extract_doc/{uid}/", 10)
                if doc_id:
                    p = f"extract_doc/{uid}/{doc_id}/"
                    probes[p] = _safe_list(bos, p, 10)
        out["bos"]["probes"] = probes
    except Exception as e:  # noqa
        out["errors"].append(f"BOS: {type(e).__name__}: {e}")
    return out


def start_extract_backflow(name, db_password, ak, sk, user_id=None,
                           date_from=None, date_to=None, limit=20, fields=None) -> str:
    """校验入参后启动后台回流任务，返回 job_id。凭证仅透传给后台线程的内存上下文。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("数据集名称不能为空")
    if dataset_service.name_exists(name):
        raise ValueError("数据集名称已存在，请换一个名称")
    if not db_password or not ak or not sk:
        raise ValueError("数据库密码、AK、SK 均为必填")
    limit = max(1, min(int(limit or 20), 500))
    job_id = _new_job()
    threading.Thread(
        target=_run_extract_backflow,
        args=(job_id, name, db_password, ak, sk, user_id, date_from, date_to, limit, fields),
        daemon=True).start()
    return job_id


def _run_extract_backflow(job_id, name, db_password, ak, sk,
                          user_id, date_from, date_to, limit, fields):
    try:
        rows = _query_docs(db_password, user_id, date_from, date_to, limit)
        existing = _existing_backflow_doc_ids()
        todo = [r for r in rows if str(r["doc_id"]) not in existing]
        skipped = len(rows) - len(todo)
        _update_job(job_id, total=len(todo), skipped=skipped)
        if not todo:
            _update_job(job_id, status="failed",
                        message="没有可回流的新文档（查询为空或均已回流）")
            return

        cfg = get_config()
        dest = os.path.join(cfg.storage_dir, "backflow",
                            f"{time.strftime('%Y%m%d%H%M%S')}_{_safe_name(name)}")
        doc_dir = os.path.join(dest, "doc")
        par_dir = os.path.join(dest, "parser")
        ann_dir = os.path.join(dest, "annotations")
        for d in (doc_dir, par_dir, ann_dir):
            os.makedirs(d, exist_ok=True)
        with open(os.path.join(ann_dir, "labels.json"), "w", encoding="utf-8") as f:
            json.dump(dataset_service._make_labels_json(fields or []), f, ensure_ascii=False)

        # 并发下载（每线程独立 BOS client），显著缩短总耗时；进度随完成累计
        from concurrent.futures import ThreadPoolExecutor
        success = 0
        missing = []
        done = 0

        def _work(r):
            return r, _fetch_doc(_bos_client(ak, sk), r, doc_dir, par_dir)

        with ThreadPoolExecutor(max_workers=8) as ex:
            for r, (ok, reason) in ex.map(_work, todo):
                done += 1
                if ok:
                    success += 1
                else:
                    missing.append({"doc_id": str(r["doc_id"]), "reason": reason})
                _update_job(job_id, done=done, success=success, missing=missing)

        if success == 0:
            sample = missing[0]["reason"] if missing else ""
            _update_job(job_id, status="failed",
                        message=f"所有文档下载失败。示例原因：{sample}（请核对 AK/SK 权限与 BOS 路径）")
            return
        res = dataset_service.load_dataset(name, base_dir=dest, source="backflow")
        _update_job(job_id, status="success", dataset_id=res["dataset"]["id"],
                    message=f"回流完成：成功 {success}，跳过(已存在) {skipped}，缺失 {len(missing)}")
    except Exception as e:  # noqa
        _update_job(job_id, status="failed", message=str(e))
    finally:
        # 显式释放本次凭证引用（局部变量随线程结束回收，不做任何持久化）
        db_password = ak = sk = None

