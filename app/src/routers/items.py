"""
Item CRUD 路由 - FastAPI
完整的增删改查 + 分页 + 搜索
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from src.database import get_db
from src.models.item import ItemModel
from src.schemas.item import (
    ItemCreate,
    ItemUpdate,
    ItemResponse,
    PaginatedResponse,
)

router = APIRouter(prefix="/items", tags=["Item"])


@router.get("", response_model=PaginatedResponse)
async def list_items(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    search: str | None = Query(None, description="搜索关键词"),
    active_only: bool = Query(False, description="仅显示启用的"),
    db: Session = Depends(get_db),
):
    """获取 Item 列表 (分页+搜索)"""
    query = db.query(ItemModel)

    # 搜索
    if search:
        query = query.filter(
            or_(
                ItemModel.title.contains(search),
                ItemModel.description.contains(search),
            )
        )

    # 过滤
    if active_only:
        query = query.filter(ItemModel.is_active.is_(True))

    # 总数
    total = query.count()

    # 分页
    items = query.order_by(ItemModel.created_at.desc()) \
                 .offset((page - 1) * page_size) \
                 .limit(page_size) \
                 .all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(
    item_id: int,
    db: Session = Depends(get_db),
):
    """获取单个 Item"""
    item = db.query(ItemModel).filter(ItemModel.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item 不存在")
    return item


@router.post("", response_model=ItemResponse, status_code=201)
async def create_item(
    data: ItemCreate,
    db: Session = Depends(get_db),
):
    """创建 Item"""
    item = ItemModel(**data.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.put("/{item_id}", response_model=ItemResponse)
async def update_item(
    item_id: int,
    data: ItemUpdate,
    db: Session = Depends(get_db),
):
    """更新 Item (部分更新)"""
    item = db.query(ItemModel).filter(ItemModel.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item 不存在")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)
    return item


@router.delete("/{item_id}")
async def delete_item(
    item_id: int,
    db: Session = Depends(get_db),
):
    """删除 Item"""
    item = db.query(ItemModel).filter(ItemModel.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item 不存在")

    db.delete(item)
    db.commit()
    return {"message": "Item 已删除", "id": item_id}
