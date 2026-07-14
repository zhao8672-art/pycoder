"""
PluginExecutor — 静默后台插件/skills 执行器

职责:
    1. 在 AI 生成响应的同时，在后台静默执行匹配的插件和 skills
    2. 执行过程不干扰主对话消息流
    3. 执行结果传递给 AI，用于丰富/优化最终响应
    4. 通过回调机制发送 plugin_event 事件（前端在进度栏展示，不在消息列表显示）

设计原则:
    - 调用方 yield token 事件（主对话）与 plugin_event 事件（进度栏）是正交的
    - plugin_event 的 hidden=true 标记前端只将渲染到进度区域，不插入消息列表
    - 执行结果通过 shared_context 字典共享给后续阶段
"""

from __future__ import annotations

import asyncio
import time
import logging
from typing import Callable, Awaitable

logger = logging.getLogger(__name__)


class PluginExecutor:
    """静默后台插件与技能执行器

    与 AI 主对话流程并行执行，结果不影响主消息流。
    """

    def __init__(self):
        self._plugin_callback: Callable[[dict], Awaitable[None]] | None = None
        self._results: dict[str, dict] = {}  # plugin_id → result

    def set_plugin_callback(self, callback: Callable[[dict], Awaitable[None]]) -> None:
        """设置插件事件回调"""
        self._plugin_callback = callback

    async def _emit_plugin_event(
        self,
        plugin_id: str,
        plugin_name: str,
        action: str,
        duration_ms: int = 0,
        error: str = "",
    ) -> None:
        """发送插件事件到前端进度栏"""
        if not self._plugin_callback:
            logger.info("plugin_emit_skipped_no_callback: pid=%s action=%s", plugin_id, action)
            return
        event = {
            "type": "plugin_event",
            "plugin_id": plugin_id,
            "plugin_name": plugin_name,
            "action": action,
            "duration_ms": duration_ms,
            "error": error[:200] if error else "",
            "hidden": True,  # 标记为静默事件，前端不插入消息列表
        }
        try:
            await self._plugin_callback(event)
        except Exception:
            pass

    async def execute_matching_plugins(
        self,
        message: str,
        shared_context: dict,
    ) -> dict[str, dict]:
        """执行与用户消息匹配的已注册插件

        Args:
            message: 用户消息
            shared_context: 共享上下文（可读写，供后续阶段使用）

        Returns:
            plugin_id → result 字典
        """
        matching_results: dict[str, dict] = {}

        try:
            # 获取插件注册表
            from pycoder.plugins.base import PluginRegistry

            registry: PluginRegistry | None = None
            try:
                from pycoder.server.app import get_plugin_registry
                registry = get_plugin_registry()
            except (ImportError, AttributeError):
                pass

            if registry is None:
                # 备选：直接从插件模块创建
                try:
                    from pycoder.plugins.hermes_plugin import HermesPlugin
                    registry = PluginRegistry()
                    registry.register(HermesPlugin())
                except Exception:
                    pass

            if registry is None:
                return matching_results

            matched_plugin = registry.match(message)
            if matched_plugin is None:
                return matching_results

            pid = matched_plugin.name
            await self._emit_plugin_event(pid, pid, "start")
            start = time.monotonic()

            try:
                # 分析阶段
                analysis = await matched_plugin.analyze(
                    {"message": message, "context": shared_context},
                )

                # 执行阶段
                result = await matched_plugin.execute(analysis)

                # 后处理
                post = await matched_plugin.post_process(result)

                elapsed_ms = int((time.monotonic() - start) * 1000)
                matching_results[pid] = {
                    "success": True,
                    "analysis": analysis,
                    "result": result,
                    "post": post,
                    "duration_ms": elapsed_ms,
                }

                # 将插件结果注入共享上下文
                shared_context["plugin_results"] = shared_context.get("plugin_results", {})
                shared_context["plugin_results"][pid] = post

                await self._emit_plugin_event(pid, pid, "done", elapsed_ms)

            except Exception as e:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                matching_results[pid] = {
                    "success": False, "error": str(e), "duration_ms": elapsed_ms,
                }
                await self._emit_plugin_event(pid, pid, "error", elapsed_ms, str(e))

        except Exception as e:
            logger.warning("plugin_executor_scan_failed: %s", e)

        return matching_results

    async def execute_matching_skills(
        self,
        message: str,
        shared_context: dict,
    ) -> dict[str, dict]:
        """执行与用户消息匹配的技能（skills）

        Skills 是安装在本地 ~/.pycoder/skills/ 的脚本文件，
        我们通过技能市场的搜索能力找到匹配项，然后静默调用。

        Args:
            message: 用户消息
            shared_context: 共享上下文

        Returns:
            skill_id → result 字典
        """
        skill_results: dict[str, dict] = {}

        try:
            # 获取技能市场管理器
            from pycoder.server.skills_market_v2 import EnhancedSkillsMarketManager

            market = EnhancedSkillsMarketManager()
            # 搜索相关技能（使用关键词匹配）
            # 提取消息中的关键词
            import re
            # 去除常见停用词后提取有效关键词
            words = re.findall(r'[\u4e00-\u9fff\w]+', message)
            keywords = [w for w in words if len(w) > 1]

            matched_skills = []
            for kw in keywords:
                result = market.search(query=kw, limit=3)
                items = result.get("items", []) if isinstance(result, dict) else []
                for skill in items:
                    sid = skill.get("id", "") if isinstance(skill, dict) else ""
                    if sid and sid not in [s.get("id") for s in matched_skills]:
                        matched_skills.append(skill)

            # 最多执行 3 个匹配技能
            matched_skills = matched_skills[:3]

            for skill in matched_skills:
                sid = skill.get("id", "") if isinstance(skill, dict) else ""
                sname = skill.get("name", sid) if isinstance(skill, dict) else sid
                if not sid:
                    continue

                await self._emit_plugin_event(sid, sname, "start")
                start = time.monotonic()
                # 技能是文件，调用方式为读取并提取关键信息
                try:
                    # 查找技能源码文件
                    from pathlib import Path
                    skill_dir = Path.home() / ".pycoder" / "skills"
                    skill_file = skill_dir / f"{sid}.md"
                    if not skill_file.exists():
                        # 尝试在子目录查找
                        for f in skill_dir.rglob(f"*{sid}*"):
                            skill_file = f
                            break

                    skill_content = ""
                    if skill_file.exists():
                        skill_content = skill_file.read_text(
                            encoding="utf-8", errors="ignore",
                        )[:3000]

                    # 将技能知识注入共享上下文，供 AI 参考
                    if skill_content:
                        context_key = f"skill_{sid}"
                        shared_context[context_key] = {
                            "name": sname,
                            "content": skill_content[:2000],
                        }
                        # 也注入到 plugin_results 统一路径
                        shared_context.setdefault("plugin_results", {})[sid] = {
                            "source": "skill",
                            "name": sname,
                            "content_preview": skill_content[:500],
                        }

                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    skill_results[sid] = {
                        "success": True,
                        "duration_ms": elapsed_ms,
                        "content_length": len(skill_content),
                    }
                    await self._emit_plugin_event(sid, sname, "done", elapsed_ms)

                except Exception as e:
                    elapsed_ms = int((time.monotonic() - start) * 1000)
                    skill_results[sid] = {
                        "success": False, "error": str(e),
                        "duration_ms": elapsed_ms,
                    }
                    await self._emit_plugin_event(sid, sname, "error", elapsed_ms, str(e))

        except Exception as e:
            logger.warning("skill_executor_scan_failed: %s", e)

        return skill_results

    async def execute_all(
        self,
        message: str,
        shared_context: dict,
    ) -> dict[str, dict]:
        """并行执行所有匹配的插件和技能

        始终发射 scan_start / scan_done 事件，即使用户消息未匹配任何插件，
        让前端可以看到后台扫描活动。插件和技能的匹配/执行结果通过 plugin_event 发射。

        两个任务并发执行以最大化效率。
        """
        # 发送扫描开始事件
        logger.info("plugin_execute_all_start: msg=%.60s cb_set=%s",
                     message, bool(self._plugin_callback))
        await self._emit_plugin_event("__scanner__", "后台扫描", "start")

        try:
            # 并发执行插件和技能扫描
            plugin_task = self.execute_matching_plugins(message, shared_context)
            skill_task = self.execute_matching_skills(message, shared_context)

            plugin_results, skill_results = await asyncio.gather(
                plugin_task, skill_task, return_exceptions=True,
            )

            # 合并结果
            all_results: dict[str, dict] = {}

            if isinstance(plugin_results, dict):
                all_results.update(plugin_results)
            else:
                all_results["__plugin_error__"] = {
                    "error": str(plugin_results), "success": False,
                }

            if isinstance(skill_results, dict):
                for k, v in (skill_results.items() if isinstance(skill_results, dict) else {}):
                    all_results[f"skill:{k}"] = v
            else:
                all_results["__skill_error__"] = {
                    "error": str(skill_results), "success": False,
                }
        except Exception as e:
            all_results = {"__fatal__": {"error": str(e), "success": False}}

        # 总结：匹配数
        match_count = sum(1 for k in all_results if not k.startswith("__"))
        await self._emit_plugin_event(
            "__scanner__",
            f"后台扫描完成 ({match_count} 匹配)",
            "done" if match_count > 0 else "skip",
        )

        return all_results
