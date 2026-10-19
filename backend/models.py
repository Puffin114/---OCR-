"""API 请求/响应的 pydantic 模型。"""
from typing import List, Optional
from pydantic import BaseModel


class LoadDatasetReq(BaseModel):
    name: Optional[str] = "default"


class BoxRecognizeReq(BaseModel):
    doc_key: str
    page_num: int
    # parser 坐标系下的矩形框 (x, y, w, h)
    box: List[float]
    dataset_id: Optional[int] = None


class SaveAnnotationReq(BaseModel):
    doc_key: str
    field: str
    label_id: str
    value: str
    page_num: int
    box: Optional[List[float]] = None
    dataset_id: Optional[int] = None
    # 组合字段分组写入：传了 parent_field 时表示保存某组合父下第 group_index 组的子字段
    parent_field: Optional[str] = None
    parent_label_id: Optional[str] = None
    group_index: Optional[int] = None


class DeleteGroupReq(BaseModel):
    doc_key: str
    parent_field: str
    group_index: int
    dataset_id: Optional[int] = None


class CriteriaItem(BaseModel):
    field: str
    modes: List[str]
    regex: Optional[str] = None


class CreateEvalTaskReq(BaseModel):
    dataset_id: int
    name: str
    doc_keys: Optional[List[str]] = None   # 不传则自动取全部可评测样本
    version: Optional[str] = "V1"
    fields: Optional[List[str]] = None     # 本次评测/抽取的字段（预览页所选）
    criteria: Optional[List[CriteriaItem]] = None   # 预设评测标准
    field_defs: Optional[List[dict]] = None  # 预览页完整字段定义 [{name,description,color,modes,regex,parent,include}]


class RenameTaskReq(BaseModel):
    name: str


class SaveCriteriaReq(BaseModel):
    task_id: int
    items: List[CriteriaItem]


class OverrideReq(BaseModel):
    task_id: int
    doc_key: str
    field: str
    verdict: str   # success/fail


class RecomputeReq(BaseModel):
    task_id: int
