"""技能数据模型 — V2 与前端 SkillItem 字段对齐"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SkillDefinition:
    """技能定义数据类（V2 — 与前端 SkillItem 字段对齐）"""

    id: str
    """唯一标识符，如 'code-review'"""
    name: str
    """技能名称"""
    version: str = "1.0.0"
    """版本号"""
    description: str = ""
    """技能描述"""
    author: str = "PyCoder"
    """作者（兼容字段，新代码用 publisher）"""
    category: str = "general"
    """分类"""
    tags: list[str] = field(default_factory=list)
    """标签列表"""
    dependencies: list[str] = field(default_factory=list)
    """依赖的技能 ID 列表"""
    install_count: int = 0
    """安装次数（前端 downloads 字段映射）"""
    rating: float = 0.0
    """平均评分 (1-5)"""
    created_at: str = ""
    """创建时间 ISO 格式"""
    updated_at: str = ""
    """更新时间 ISO 格式"""
    markdown_content: str = ""
    """技能 Markdown 内容"""
    is_builtin: bool = False
    """是否为内置技能"""

    # ── V2 新增字段（对齐前端 SkillItem）──
    publisher: str = ""
    """发布者名称（与 author 同义，前端字段）"""
    verified: bool = False
    """是否为已验证发布者"""
    source_url: str = ""
    """远程源 URL（GitHub release / 自建 registry）"""
    homepage_url: str = ""
    """主页 URL"""
    license: str = ""
    """开源许可证"""
    icon_url: str = ""
    """图标 URL"""
    local_version: str = ""
    """本地已安装版本（用于更新检测）"""
    remote_version: str = ""
    """远程最新版本（用于更新检测）"""
    stars: int = 0
    """星标数（前端字段，独立于 rating）"""

    def __post_init__(self) -> None:
        """publisher 缺省时回退到 author"""
        if not self.publisher:
            self.publisher = self.author

    @property
    def has_update(self) -> bool:
        """是否有可用更新（前端字段）"""
        return bool(
            self.remote_version and self.local_version and self.remote_version != self.local_version
        )

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（与前端 SkillItem 接口对齐）"""
        return {
            # 基础字段
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category,
            "tags": self.tags,
            "dependencies": self.dependencies,
            "install_count": self.install_count,
            "rating": self.rating,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_builtin": self.is_builtin,
            # V2 新增字段（前端期望）
            "publisher": self.publisher or self.author,
            "verified": self.verified,
            "source_url": self.source_url,
            "homepage_url": self.homepage_url,
            "license": self.license,
            "icon_url": self.icon_url,
            "local_version": self.local_version,
            "remote_version": self.remote_version,
            "stars": self.stars,
            "downloads": self.install_count,  # 前端别名
            "has_update": self.has_update,
        }
