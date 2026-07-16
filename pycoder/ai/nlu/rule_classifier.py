"""
规则快速通道 — Layer 1 NLU

零 Token 消耗的关键词/正则匹配意图分类:
  - 技术领域检测 (8 个领域)
  - 任务类型检测 (10 种类型)
  - 歧义评估 (模糊代词/缺失目标)
  - 情感检测 (积极/消极/中性)
  - 复杂度评估
"""

from __future__ import annotations

import re
import logging

logger = logging.getLogger(__name__)


# ── 领域关键词 ──

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "data_science": [
        "数据", "机器学习", "深度学习", "pandas", "numpy", "tensorflow",
        "pytorch", "sklearn", "scikit", "数据分析", "可视化", "plot",
        "matplotlib", "seaborn", "回归", "分类", "聚类",
    ],
    "web_backend": [
        "api", "rest", "fastapi", "flask", "django", "后端", "服务端",
        "服务器", "database", "数据库", "sql", "nosql", "redis", "mq",
        "rabbitmq", "kafka", "nginx",
    ],
    "web_frontend": [
        "react", "vue", "angular", "前端", "ui", "组件", "html", "css",
        "javascript", "typescript", "页面", "界面", "样式",
    ],
    "devops": [
        "docker", "kubernetes", "k8s", "ci/cd", "jenkins", "deploy",
        "部署", "运维", "监控", "prometheus", "grafana", "terraform",
        "ansible", "gitlab",
    ],
    "security": [
        "安全", "加密", "权限", "认证", "鉴权", "oauth", "jwt",
        "xss", "csrf", "sql注入", "渗透", "漏洞",
    ],
    "system": [
        "操作系统", "linux", "window", "进程", "线程", "内存",
        "文件系统", "网络协议", "tcp/ip", "socket",
    ],
    "algorithms": [
        "算法", "排序", "搜索", "递归", "动态规划", "复杂度",
        "数据结构", "链表", "树", "图", "哈希",
    ],
    "testing": [
        "测试", "unittest", "pytest", "jest", "mocha", "tdd",
        "集成测试", "单元测试", "e2e", "覆盖率",
    ],
}


# ── 任务类型关键词 ──

TASK_KEYWORDS: dict[str, list[str]] = {
    "code_generation": [
        "写一个", "实现", "创建一个", "生成", "编写", "develop",
        "implement", "create", "write", "build", "code",
    ],
    "code_review": [
        "review", "审查", "检查代码", "代码评审", "审计", "audit",
    ],
    "debugging": [
        "bug", "修复", "错误", "调试", "debug", "fix", "crash",
        "崩溃", "异常", "报错", "不工作",
    ],
    "refactoring": [
        "重构", "优化", "改进", "refactor", "improve", "optimize",
        "清理", "clean up", "重写",
    ],
    "explanation": [
        "解释", "什么是", "为什么", "如何", "介绍", "说明",
        "explain", "what is", "how", "why", "tutorial",
    ],
    "configuration": [
        "配置", "安装", "设置", "setup", "configure", "install",
        "部署", "deploy", "环境",
    ],
    "analysis": [
        "分析", "诊断", "调查", "analyze", "diagnose", "investigate",
        "profile", "性能",
    ],
    "testing": [
        "测试", "test", "spec", "用例", "coverage",
    ],
    "documentation": [
        "文档", "doc", "readme", "注释", "手册", "manual",
        "documentation",
    ],
    "architecture": [
        "架构", "设计", "架构图", "architecture", "design",
        "规划", "plan", "系统设计",
    ],
}


# ── 歧义关键词 ──

AMBIGUITY_CLUES: dict[str, list[str]] = {
    "vague_pronoun": [
        "它", "这个", "那个", "那里", "it", "this", "that", "there",
    ],
    "missing_context": [
        "有一个", "有个", "帮我", "我想", "我需要",
        "有一个问题", "有个bug", "不行了",
    ],
    "missing_tech_stack": [
        "怎么实现", "如何做", "怎么办", "怎么做",
        "how to implement", "how to do",
    ],
}


class RuleClassifier:
    """Layer 1: 规则快速通道 NLU"""

    def __init__(self) -> None:
        self._domain_patterns = {
            name: re.compile(
                "|".join(re.escape(kw) for kw in kws),
                re.IGNORECASE,
            )
            for name, kws in DOMAIN_KEYWORDS.items()
        }
        self._task_patterns = {
            name: re.compile(
                "|".join(re.escape(kw) for kw in kws),
                re.IGNORECASE,
            )
            for name, kws in TASK_KEYWORDS.items()
        }

    async def classify(self, text: str) -> dict:
        """快速规则分类 (零 Token)"""
        result = {
            "domain": self._detect_domain(text),
            "task_type": self._detect_task_type(text),
            "ambiguity_score": self._detect_ambiguity(text),
            "complexity": self._estimate_complexity(text),
            "sentiment": self._detect_sentiment(text),
            "confidence": 0.0,
        }

        # 规则模式匹配时置信度高
        if result["domain"] != "general" or result["task_type"] != "unknown":
            result["confidence"] = 0.7
        else:
            result["confidence"] = 0.3  # 未能匹配，需要 Layer 2/3

        return result

    def _detect_domain(self, text: str) -> str:
        """检测技术领域"""
        matched_domains = []
        for domain, pattern in self._domain_patterns.items():
            if pattern.search(text):
                matched_domains.append(domain)

        if matched_domains:
            return matched_domains[0]
        return "general"

    def _detect_task_type(self, text: str) -> str:
        """检测任务类型"""
        matched_tasks = []
        for task, pattern in self._task_patterns.items():
            if pattern.search(text):
                matched_tasks.append(task)

        if matched_tasks:
            return matched_tasks[0]
        return "unknown"

    def _detect_ambiguity(self, text: str) -> float:
        """检测歧义程度 (0-1)"""
        score = 0.0
        for category, clues in AMBIGUITY_CLUES.items():
            for clue in clues:
                if clue.lower() in text.lower():
                    if category == "vague_pronoun":
                        score += 0.2
                    elif category == "missing_context":
                        score += 0.25
                    elif category == "missing_tech_stack":
                        score += 0.3

        # 短文本倾向歧义
        if len(text) < 10:
            score += 0.3
        elif len(text) < 20:
            score += 0.15

        return min(score, 1.0)

    def _estimate_complexity(self, text: str) -> str:
        """预估任务复杂度"""
        length = len(text)
        if length < 20:
            return "trivial"
        if length < 80:
            return "simple"
        if length < 200:
            return "medium"
        return "complex"

    def _detect_sentiment(self, text: str) -> str:
        """检测情感"""
        urgent_words = ["急", "紧急", "立刻", "马上", "urgent", "asap", "critical"]
        frustrated_words = ["崩溃", "不行", "坏了", "完了", "错误", "frustrated", "broken"]
        positive_words = ["感谢", "好", "完美", "great", "thanks", "perfect"]

        lower = text.lower()
        for w in frustrated_words:
            if w in lower:
                return "negative"
        for w in urgent_words:
            if w in lower:
                return "urgent"
        for w in positive_words:
            if w in lower:
                return "positive"
        return "neutral"
