"""
Item Pydantic Schema - 请求/响应 模型
Pydantic v2 风格
"""
from datetime import datetime
from pydantic import BaseModel, Field


class ItemCreate(BaseModel):
    """创建 Item 请求"""
    title: str = Field(..., min_length=1, max_length=200, description="Item 标题")
    description: str | None = Field(None, description="Item 描述")


class ItemUpdate(BaseModel):
    """更新 Item 请求 (全部可选)"""
    title: str | None = Field(None, min_length=1, max_length=200, description="Item 标题")
    description: str | None = Field(None, description="Item 描述")
    is_active: bool | None = Field(None, description="是否启用")


class ItemResponse(BaseModel):
    """Item 响应"""
    id: int
    title: str
    description: str | None = None
    is_active: bool = True
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel):
    """分页响应"""
    total: int
    page: int
    page_size: int
    items: list[ItemResponse]
