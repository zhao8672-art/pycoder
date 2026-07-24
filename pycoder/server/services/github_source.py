"""
GitHub 高质量扩展数据源模块
功能:
- 从 GitHub API 拉取高星标的 Python/LLM/AI 相关项目
- 解析项目信息并转换为 PyCoder 技能格式
- 支持增量更新和全量同步
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp

from pycoder.server.log import log


@dataclass
class GitHubSkill:
    """GitHub 技能数据模型"""

    id: str
    name: str
    description: str
    url: str
    stars: int
    language: str
    source: str = "github_trending"
    last_updated: str = ""
    tags: List[str] = field(default_factory=list)
    quality_score: float = 0.0
    categories: List[str] = field(default_factory=list)


class GitHubTrendingSource:
    """
    GitHub 高质量扩展数据源
    
    定期拉取 GitHub 上高星标的 Python/LLM/Agent 相关项目，
    并将其转换为 PyCoder 技能格式。
    """

    def __init__(self):
        self.api_url = "https://api.github.com/search/repositories"
        self.headers = {
            "Accept": "application/vnd.github.v3+json",
        }
        # 从环境变量获取 GitHub Token，避免速率限制
        self.token = os.getenv("GITHUB_TOKEN", "")
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
        
        # 搜索查询配置
        self.queries = [
            # Python 高星项目
            {
                "q": "language:python stars:>500 updated:>2023-01-01",
                "category": "python-tools",
                "tags": ["python", "tools", "development"]
            },
            # AI/LLM 相关 TypeScript/JS 项目
            {
                "q": "language:typescript language:javascript stars:>1000 topic:ai",
                "category": "ai-llm",
                "tags": ["ai", "llm", "machine-learning"]
            },
            # MCP Server 项目
            {
                "q": "topic:mcp-server topic:llm",
                "category": "mcp-tools",
                "tags": ["mcp", "agent", "tools"]
            },
            # Agent 框架
            {
                "q": "language:python stars:>300 topic:agent OR topic:llm-agent",
                "category": "agent-frameworks",
                "tags": ["agent", "framework", "automation"]
            },
        ]

    async def fetch_skills(self) -> List[GitHubSkill]:
        """
        从 GitHub API 拉取高质量技能
        
        Returns:
            List[GitHubSkill]: 技能列表
        """
        skills = []
        
        try:
            async with aiohttp.ClientSession() as session:
                for query_config in self.queries:
                    params = {
                        "q": query_config["q"],
                        "sort": "stars",
                        "order": "desc",
                        "per_page": 20,  # 每查询返回 20 个结果
                    }
                    
                    log.info(
                        "github_fetch_start",
                        query=query_config["q"],
                        category=query_config["category"],
                    )
                    
                    try:
                        async with session.get(
                            self.api_url, headers=self.headers, params=params, timeout=aiohttp.ClientTimeout(total=30)
                        ) as response:
                            if response.status == 200:
                                data = await response.json()
                                items = data.get("items", [])
                                
                                for item in items:
                                    skill = self._parse_repository(item, query_config)
                                    if skill:
                                        skills.append(skill)
                                
                                log.info(
                                    "github_fetch_success",
                                    count=len(items),
                                    category=query_config["category"],
                                )
                                
                            elif response.status == 403:
                                log.warning(
                                    "github_rate_limit",
                                    message="GitHub API rate limit exceeded. Consider setting GITHUB_TOKEN.",
                                )
                                break
                            else:
                                log.warning(
                                    "github_fetch_failed",
                                    status=response.status,
                                    category=query_config["category"],
                                )
                    except asyncio.TimeoutError:
                        log.warning(
                            "github_fetch_timeout",
                            category=query_config["category"],
                        )
                    except Exception as e:
                        log.error(
                            "github_fetch_error",
                            error=str(e),
                            category=query_config["category"],
                        )
        
        except Exception as e:
            log.error("github_fetch_session_error", error=str(e))
        
        return skills

    def _parse_repository(self, repo: Dict[str, Any], query_config: Dict[str, Any]) -> Optional[GitHubSkill]:
        """
        解析 GitHub 仓库数据为技能对象
        
        Args:
            repo: GitHub API 返回的仓库数据
            query_config: 查询配置
            
        Returns:
            GitHubSkill 或 None
        """
        try:
            # 计算质量评分（基于星标、更新频率、描述完整性）
            quality_score = self._calculate_quality_score(repo)
            
            # 解析更新时间
            updated_at = repo.get("updated_at", "")
            last_updated = ""
            if updated_at:
                try:
                    dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                    last_updated = dt.isoformat()
                except ValueError:
                    last_updated = updated_at
            
            skill = GitHubSkill(
                id=f"github-{repo['id']}",
                name=repo["full_name"],
                description=repo.get("description") or "No description available",
                url=repo["html_url"],
                stars=repo.get("stargazers_count", 0),
                language=repo.get("language") or "Unknown",
                source="github_trending",
                last_updated=last_updated,
                tags=query_config.get("tags", []) + repo.get("topics", []),
                quality_score=quality_score,
                categories=[query_config.get("category", "general")],
            )
            
            return skill
        
        except Exception as e:
            log.warning("github_parse_error", error=str(e), repo=repo.get("full_name", "unknown"))
            return None

    def _calculate_quality_score(self, repo: Dict[str, Any]) -> float:
        """
        计算技能质量评分 (0-100)
        
        评分因素:
        - 星标数 (40%)
        - 最近更新时间 (30%)
        - 是否有描述 (15%)
        - 是否有 README (15%)
        """
        score = 0.0
        
        # 星标评分 (0-40)
        stars = repo.get("stargazers_count", 0)
        if stars >= 10000:
            score += 40
        elif stars >= 5000:
            score += 35
        elif stars >= 1000:
            score += 30
        elif stars >= 500:
            score += 25
        elif stars >= 100:
            score += 20
        else:
            score += 10
        
        # 更新时间评分 (0-30)
        updated_at = repo.get("updated_at", "")
        if updated_at:
            try:
                dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                days_since_update = (datetime.now(dt.tzinfo) - dt).days
                if days_since_update <= 30:
                    score += 30
                elif days_since_update <= 90:
                    score += 25
                elif days_since_update <= 180:
                    score += 20
                elif days_since_update <= 365:
                    score += 15
                else:
                    score += 5
            except ValueError:
                score += 10
        
        # 描述评分 (0-15)
        if repo.get("description"):
            score += 15
        else:
            score += 5
        
        # README 评分 (0-15)
        if repo.get("has_issues") or repo.get("has_wiki"):
            score += 15
        else:
            score += 5
        
        return min(score, 100.0)

    async def fetch_and_convert_to_skill_format(self) -> List[Dict[str, Any]]:
        """
        拉取数据并转换为标准技能格式
        
        Returns:
            List[Dict]: 标准技能格式列表
        """
        skills = await self.fetch_skills()
        
        result = []
        for skill in skills:
            result.append({
                "id": skill.id,
                "name": skill.name,
                "description": skill.description,
                "url": skill.url,
                "stars": skill.stars,
                "language": skill.language,
                "source": skill.source,
                "last_updated": skill.last_updated,
                "tags": skill.tags,
                "quality_score": skill.quality_score,
                "categories": skill.categories,
            })
        
        return result


# 全局实例
github_source = GitHubTrendingSource()


async def fetch_github_skills() -> List[Dict[str, Any]]:
    """
    便捷函数：获取 GitHub 高质量技能
    
    Returns:
        List[Dict]: 技能列表
    """
    return await github_source.fetch_and_convert_to_skill_format()
