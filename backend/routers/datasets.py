import json
import os
import re
import tempfile
from typing import List

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from config import get_config
from models import LoadDatasetReq
from services import dataset_service

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _chunks_dir() -> str:
    d = os.path.join(get_config().storage_dir, "uploads", "_chunks")
    os.makedirs(d, exist_ok=True)
    return d


def _chunk_path(upload_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", upload_id or ""):
        raise HTTPException(400, "非法 upload_id")
    return os.path.join(_chunks_dir(), upload_id + ".part")


@router.post("/upload-chunk")
async def upload_chunk(upload_id: str = Form(...), index: int = Form(0),
                       chunk: UploadFile = File(...)):
    """分片上传：按顺序把分片追加写入临时文件（流式，不整文件入内存）。"""
    path = _chunk_path(upload_id)
    mode = "wb" if index == 0 else "ab"
    with open(path, mode) as f:
        while True:
            buf = await chunk.read(1024 * 1024)
            if not buf:
                break
            f.write(buf)
    return {"ok": True, "index": index, "size": os.path.getsize(path)}


@router.post("/upload-finish")
def upload_finish(body: dict):
    """合并完成：annotated→import_zip；否则按未标注把分片文件（zip/单文件）走 create_unannotated。"""
    body = body or {}
    upload_id = body.get("upload_id", "")
    path = _chunk_path(upload_id)
    if not os.path.exists(path):
        raise HTTPException(400, "分片文件不存在或已过期")
    name = (body.get("name") or "uploaded").strip()
    annotated = bool(body.get("annotated"))
    filename = body.get("filename") or ""
    try:
        if annotated:
            res = dataset_service.import_zip(path, name)
            fields = body.get("fields") or []
            if fields:
                dataset_service.apply_field_overrides(res["dataset"]["id"], fields)
                res = dataset_service.get_dataset(res["dataset"]["id"])
            return res
        fields = body.get("fields") or []
        if not fields:
            raise HTTPException(400, "未标注导入需先配置字段清单")
        # 给临时文件一个带真实后缀的名字，便于按 .zip 判断
        suffix = os.path.splitext(filename)[1] or ".zip"
        named = path + suffix
        os.replace(path, named)
        try:
            return dataset_service.create_unannotated(name, "", fields, [named], [filename or os.path.basename(named)])
        finally:
            if os.path.exists(named):
                os.remove(named)
    except HTTPException:
        raise
    except Exception as e:  # noqa
        raise HTTPException(400, str(e))
    finally:
        if os.path.exists(path):
            os.remove(path)


@router.post("/load")
def load(req: LoadDatasetReq):
    try:
        return dataset_service.load_dataset(req.name or "default")
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/parse-fields")
async def parse_fields(file: UploadFile = File(...)):
    """解析上传的 labels.json / 清单 / 含 labels.json 的 zip → 返回字段数组供编辑。"""
    name = (file.filename or "").lower()
    suffix = next((s for s in (".zip", ".xlsx", ".csv", ".json") if name.endswith(s)), ".json")
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    try:
        tmp.write(await file.read())
        tmp.close()
        return {"fields": dataset_service.parse_fields_from_file(tmp.name)}
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.post("/create")
async def create(name: str = Form(...), description: str = Form(""),
                 annotated: bool = Form(False), fields: str = Form("[]"),
                 files: List[UploadFile] = File(...)):
    """创建数据集。annotated=True 上传含 annotations/labels.json/doc 的 zip；
    annotated=False 上传原始文件并用 fields 生成清单。"""
    try:
        field_list = json.loads(fields or "[]")
    except Exception:
        raise HTTPException(400, "字段信息格式错误")
    if not files:
        raise HTTPException(400, "请上传文件")
    tmp_paths = []
    orig_names = []
    try:
        for uf in files:
            suffix = os.path.splitext(uf.filename or "")[1] or ""
            t = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            t.write(await uf.read())
            t.close()
            tmp_paths.append(t.name)
            orig_names.append(uf.filename or os.path.basename(t.name))
        if annotated:
            # 取第一个 zip 导入，再用用户调整后的字段覆盖
            zips = [p for p in tmp_paths if p.lower().endswith(".zip")]
            if not zips:
                raise HTTPException(400, "有标注导入请上传 zip 压缩包")
            res = dataset_service.import_zip(zips[0], name)
            if field_list:
                dataset_service.apply_field_overrides(res["dataset"]["id"], field_list)
                res = dataset_service.get_dataset(res["dataset"]["id"])
            return res
        else:
            if not field_list:
                raise HTTPException(400, "未标注导入需先配置字段清单")
            return dataset_service.create_unannotated(name, description, field_list, tmp_paths, orig_names)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        for p in tmp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass


@router.post("/upload")
async def upload(file: UploadFile = File(...), name: str = Form("uploaded")):
    if not (file.filename or "").lower().endswith(".zip"):
        raise HTTPException(400, "请上传 .zip 压缩包")
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    try:
        tmp.write(await file.read())
        tmp.close()
        return dataset_service.import_zip(tmp.name, name or "uploaded")
    except Exception as e:
        raise HTTPException(400, str(e))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


@router.get("/name-available")
def name_available(name: str, exclude_id: int = None):
    """校验数据集名称是否可用（未被占用）。供前端实时查重。"""
    return {"available": not dataset_service.name_exists(name, exclude_id)}


@router.get("")
def list_all():
    return dataset_service.list_datasets()


@router.get("/{dataset_id}")
def detail(dataset_id: int):
    try:
        return dataset_service.get_dataset(dataset_id)
    except Exception as e:
        raise HTTPException(404, str(e))


@router.delete("/{dataset_id}")
def delete(dataset_id: int):
    try:
        return dataset_service.delete_dataset(dataset_id)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.delete("/{dataset_id}/documents/{doc_key}")
def delete_document(dataset_id: int, doc_key: str):
    try:
        return dataset_service.delete_document(dataset_id, doc_key)
    except Exception as e:
        raise HTTPException(400, str(e))


@router.post("/{dataset_id}/rename")
def rename(dataset_id: int, body: dict):
    try:
        return dataset_service.rename_dataset(dataset_id, (body or {}).get("name", ""))
    except Exception as e:
        raise HTTPException(400, str(e))
