"""通用接口契约；模块字段由领域服务持有，不再为每个模块复制一份模型类。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ActionPayload(BaseModel):
    action: str
    remark: str | None = None


class MemberPayload(BaseModel):
    """下钻父级补录成员的请求体；度量留空表示缺失，不会被当成 0。"""
    member_code: str
    member_name: str
    member_type: str
    metrics: dict[str, Any] = Field(default_factory=dict)


class ReadComparePayload(BaseModel):
    """同一父级两次下钻读取的对照请求。"""
    base_read_id: int
    target_read_id: int
