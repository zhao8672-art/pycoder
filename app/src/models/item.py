"""
Item 数据模型 - SQLAlchemy ORM
"""
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean
from src.database import Base


class ItemModel(Base):
    """Item 模型"""
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    title = Column(String(200), nullable=False, index=True, comment="标题")
    description = Column(Text, nullable=True, comment="描述")
    is_active = Column(Boolean, default=True, comment="是否启用")
    created_at = Column(DateTime, default=datetime.utcnow, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment="更新时间")

    def __repr__(self) -> str:
        return f"<Item {self.id}: {self.title}>"
