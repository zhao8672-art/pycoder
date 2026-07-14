"""
模式提取器 — 从历史经验中提取可复用的修复模式

功能:
  1. 错误聚类 — 按错误签名归组
  2. 修复模式挖掘 — 提取通用修复模板
  3. 热点分析 — 识别高频出错的模块
  4. Prompt 优化建议 — 基于历史成功率调整
  5. 模式持久化 — JSONL 写入磁盘，重启后可恢复（H5）

用法:
  from .pattern_extractor import PatternExtractor
  pe = PatternExtractor()
  patterns = pe.extract_fix_patterns(min_success=3)
  hotspots = pe.get_hotspots(top_n=10)
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path

PATTERNS_DIR = Path(
    os.environ.get(
        "PYCODER_PATTERNS_DIR",
        str(Path.home() / ".pycoder" / "learning" / "patterns"),
    )
)


@dataclass
class FixPattern:
    """通用修复模式"""

    pattern_id: str = ""  # 模式 ID
    error_type: str = ""  # 错误类型
    description: str = ""  # 模式描述
    fix_template: str = ""  # 修复模板（含占位符）
    example_error: str = ""  # 示例错误
    example_fix: str = ""  # 示例修复
    success_count: int = 0
    fail_count: int = 0
    last_used: float = 0.0
    files_affected: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total > 0 else 0.0


@dataclass
class HotspotInfo:
    """热点信息"""

    file_path: str = ""
    entity: str = ""
    error_count: int = 0
    fix_success_rate: float = 0.0
    recent_errors: list[str] = field(default_factory=list)
    risk_score: float = 0.0


@dataclass
class ClusterInfo:
    """聚类信息"""

    cluster_id: str = ""
    error_type: str = ""
    member_count: int = 0
    common_fix: str = ""
    fix_confidence: float = 0.0
    member_signatures: list[str] = field(default_factory=list)


class PatternExtractor:
    """模式提取器"""

    def __init__(self, persist_dir: Path | None = None):
        self._patterns: list[FixPattern] = []
        self._last_extraction: float = 0.0
        # H5: 持久化目录与文件路径（与 feedback_loop 同构）
        self._persist_dir = persist_dir or PATTERNS_DIR
        self._patterns_path = self._persist_dir / "patterns.jsonl"
        # 启动时加载历史模式，使重启后仍可复用
        self._load_patterns()

    # ─── 修复模式提取 ───

    def extract_fix_patterns(
        self,
        knowledge_base=None,
        experience_buffer=None,
        min_success: int = 3,
    ) -> list[FixPattern]:
        """从知识库和经验缓冲区提取通用修复模式"""
        patterns: list[FixPattern] = []

        # 从知识库提取
        if knowledge_base:
            top_errors = knowledge_base.get_top_errors(limit=50)
            for ep in top_errors:
                if ep.success_count >= min_success and ep.fix_template:
                    patterns.append(
                        FixPattern(
                            pattern_id=f"KB-{ep.id}",
                            error_type=ep.error_type,
                            description=f"修复 {ep.error_type} 的高成功率方案",
                            fix_template=ep.fix_template,
                            example_error=ep.error_signature,
                            example_fix=ep.fix_template[:500],
                            success_count=ep.success_count,
                            fail_count=ep.fail_count,
                            last_used=ep.last_seen,
                            files_affected=[ep.file_pattern] if ep.file_pattern else [],
                        )
                    )

        # 从经验缓冲区提取
        if experience_buffer:
            stats = experience_buffer.get_stats(window_hours=168)
            for err_type, count in stats.top_error_types:
                exps = experience_buffer.get_by_error_type(err_type, limit=10)
                successes = [e for e in exps if e.outcome == "success"]
                if len(successes) >= min_success:
                    # 提取最常见的修复方法
                    fix_contents = [e.fix_content[:200] for e in successes if e.fix_content]
                    common_fix = self._find_common_substring(fix_contents) if fix_contents else ""
                    patterns.append(
                        FixPattern(
                            pattern_id=f"EXP-{err_type[:20]}",
                            error_type=err_type,
                            description=f"常见 {err_type} 修复模式（{count}次出现）",
                            fix_template=common_fix or "（无通用模板）",
                            example_error=successes[0].error_message if successes else "",
                            example_fix=successes[0].fix_content[:500] if successes else "",
                            success_count=len(successes),
                            fail_count=count - len(successes),
                        )
                    )

        self._patterns = patterns
        self._last_extraction = time.time()
        # H5: 提取完成后立即持久化，避免进程崩溃丢失
        self._save_patterns()
        return patterns

    @staticmethod
    def _find_common_substring(strings: list[str]) -> str:
        """找多段文本的公共子串"""
        if not strings or len(strings) < 2:
            return strings[0] if strings else ""

        # 简化的最长公共前缀
        common = ""
        for i in range(min(len(s) for s in strings)):
            char = strings[0][i]
            if all(s[i] == char for s in strings):
                common += char
            else:
                break

        # 如果公共前缀太短，返回第一个字符串的截断
        if len(common) < 10:
            return strings[0][:200]
        return common[:500]

    # ─── 热点分析 ───

    def get_hotspots(
        self,
        knowledge_base=None,
        experience_buffer=None,
        top_n: int = 10,
        min_errors: int = 2,
    ) -> list[HotspotInfo]:
        """识别项目中的 bug 热点"""
        hotspots: dict[str, HotspotInfo] = {}

        # 从知识库
        if knowledge_base:
            kb_hotspots = knowledge_base.get_hotspots(limit=top_n)
            for h in kb_hotspots:
                hotspots[h["entity"]] = HotspotInfo(
                    file_path=h["entity"],
                    entity=h["entity"],
                    error_count=h["bug_frequency"],
                    risk_score=knowledge_base.get_entity_risk(h["entity"]),
                )

        # 从经验缓冲区补充
        if experience_buffer:
            file_counter: Counter = Counter()
            file_errors: dict[str, list[str]] = {}
            for exp in experience_buffer._buffer:
                for fp in exp.file_paths:
                    file_counter[fp] += 1
                    file_errors.setdefault(fp, []).append(exp.error_message[:100])

            for fp, count in file_counter.most_common(top_n):
                if count < min_errors:
                    continue
                if fp in hotspots:
                    hotspots[fp].error_count += count
                    hotspots[fp].recent_errors = file_errors.get(fp, [])[:5]
                else:
                    hotspots[fp] = HotspotInfo(
                        file_path=fp,
                        entity=fp,
                        error_count=count,
                        recent_errors=file_errors.get(fp, [])[:5],
                        risk_score=min(count * 10, 100),
                    )

        # 排序
        result = sorted(hotspots.values(), key=lambda h: -h.error_count)
        return result[:top_n]

    # ─── 错误聚类 ───

    def cluster_errors(
        self,
        experience_buffer=None,
        min_cluster_size: int = 3,
    ) -> list[ClusterInfo]:
        """对错误进行聚类分析"""
        if not experience_buffer or not experience_buffer._buffer:
            return []

        # 按错误类型分组
        by_type: dict[str, list] = {}
        for exp in experience_buffer._buffer:
            if exp.error_signature:
                sig = exp.error_signature
                etype = sig.split(":")[0] if ":" in sig else sig[:30]
                by_type.setdefault(etype, []).append(exp)

        clusters: list[ClusterInfo] = []
        for etype, exps in by_type.items():
            if len(exps) < min_cluster_size:
                continue

            successes = [e for e in exps if e.outcome == "success"]
            fixes = [e.fix_content[:200] for e in successes if e.fix_content]

            clusters.append(
                ClusterInfo(
                    cluster_id=f"CL-{etype[:20]}",
                    error_type=etype,
                    member_count=len(exps),
                    common_fix=self._find_common_substring(fixes) if fixes else "",
                    fix_confidence=len(successes) / len(exps) if exps else 0,
                    member_signatures=[e.error_signature for e in exps[:10]],
                )
            )

        # 按成员数量排序
        clusters.sort(key=lambda c: -c.member_count)
        return clusters

    # ─── Prompt 分析 ───

    def analyze_prompt_effectiveness(
        self,
        experience_buffer=None,
        days: int = 7,
    ) -> dict:
        """分析不同 Agent/system prompt 的效果"""
        if not experience_buffer:
            return {}

        cutoff = time.time() - days * 86400
        recent = [e for e in experience_buffer._buffer if e.timestamp > cutoff]

        by_role: dict[str, dict] = {}
        for exp in recent:
            role = exp.agent_role or "unknown"
            if role not in by_role:
                by_role[role] = {"total": 0, "success": 0, "avg_quality": 0, "avg_tokens": 0}
            by_role[role]["total"] += 1
            if exp.outcome == "success":
                by_role[role]["success"] += 1
            by_role[role]["avg_quality"] += exp.quality_score
            by_role[role]["avg_tokens"] += exp.tokens_used

        result: dict[str, dict] = {}
        for role, data in by_role.items():
            n = data["total"]
            result[role] = {
                "total_tasks": n,
                "success_rate": data["success"] / n if n > 0 else 0,
                "avg_quality": round(data["avg_quality"] / n, 1) if n > 0 else 0,
                "avg_tokens": round(data["avg_tokens"] / n, 0) if n > 0 else 0,
            }

        return result

    # ─── 统计导出 ───

    def get_pattern_stats(self) -> dict:
        """获取模式统计"""
        if not self._patterns:
            return {"total": 0, "top_types": []}

        type_counts: Counter = Counter(p.error_type for p in self._patterns)
        return {
            "total": len(self._patterns),
            "last_extraction": self._last_extraction,
            "top_types": type_counts.most_common(10),
            "high_confidence": sum(1 for p in self._patterns if p.success_rate > 0.8),
            "patterns": [
                {
                    "id": p.pattern_id,
                    "type": p.error_type,
                    "success_rate": round(p.success_rate, 2),
                    "uses": p.success_count + p.fail_count,
                }
                for p in sorted(
                    self._patterns,
                    key=lambda x: -x.success_rate,
                )[:20]
            ],
        }

    # ─── 持久化（H5） ───

    def _load_patterns(self) -> None:
        """H5: 从 JSONL 文件加载历史模式，重启后可恢复。

        与 feedback_loop._load_signals 同构：每行一个 JSON 对象。
        """
        if not self._patterns_path.exists():
            return
        try:
            lines = self._patterns_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        loaded: list[FixPattern] = []
        for line in lines[-200:]:  # 最多保留 200 条，避免文件无限增长
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                loaded.append(
                    FixPattern(
                        pattern_id=data.get("pattern_id", ""),
                        error_type=data.get("error_type", ""),
                        description=data.get("description", ""),
                        fix_template=data.get("fix_template", ""),
                        example_error=data.get("example_error", ""),
                        example_fix=data.get("example_fix", ""),
                        success_count=int(data.get("success_count", 0)),
                        fail_count=int(data.get("fail_count", 0)),
                        last_used=float(data.get("last_used", 0.0)),
                        files_affected=list(data.get("files_affected", [])),
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        if loaded:
            # 合并：磁盘历史作为基线，新提取会覆盖
            self._patterns = loaded
            # last_extraction 取磁盘上最新模式的 last_used
            self._last_extraction = max((p.last_used for p in loaded), default=0.0)

    def _save_patterns(self) -> None:
        """H5: 全量重写 patterns.jsonl（与 feedback_loop._save_signals 同构）。

        持久化失败不应影响主流程，因此捕获 OSError 后静默。
        """
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            lines = [json.dumps(asdict(p), ensure_ascii=False) for p in self._patterns]
            self._patterns_path.write_text(
                "\n".join(lines) + ("\n" if lines else ""),
                encoding="utf-8",
            )
        except OSError:
            pass


__all__ = [
    "PatternExtractor",
    "FixPattern",
    "HotspotInfo",
    "ClusterInfo",
    "PATTERNS_DIR",
]
