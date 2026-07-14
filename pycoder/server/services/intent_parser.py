"""
意图解析器 — 基于规则+关键词的轻量意图分类

策略:
    1. 规则优先（零 Token 消耗）— 正则匹配关键词/模式
    2. LLM 回退（高歧义时）— 调用轻量模型做最终判断

输入: 用户原始消息
输出: ParsedIntent (类别+美化后指令)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class TaskCategory(Enum):
    CHAT = "chat"
    HERMES = "hermes"
    AGENT = "agent"


@dataclass
class ParsedIntent:
    raw_input: str
    surface_text: str
    core_need: str
    ambiguity: str = ""
    task_category: TaskCategory = TaskCategory.CHAT
    beautified_command: str = ""
    has_risk: bool = False
    risk_description: str = ""


# ══════════════════════════════════════════════════════════
# 分类规则库
# ══════════════════════════════════════════════════════════

CATEGORY_RULES: list[tuple[str, TaskCategory, str]] = [
    # B类: 工具操作 → hermes
    (
        "修改|更改|改成|修复|修复bug|添加|增加|删除|更新|优化|改|调整|替换",
        TaskCategory.HERMES,
        "任务涉及代码/文件修改",
    ),
    (
        "安装|卸载|配置|设置|运行|执行|测试|调试|编译|构建|打包",
        TaskCategory.HERMES,
        "任务涉及工具/环境操作",
    ),
    ("写一个|生成一个|创建一个|新建一个|做一个|实现一个", TaskCategory.HERMES, "任务涉及代码生成"),
    ("检查|诊断|分析|查看|排查|审查|review|查找|搜索", TaskCategory.HERMES, "任务涉及检查/分析"),
    ("提交|commit|push|pull|merge|branch|stash|rebase", TaskCategory.HERMES, "任务涉及 Git 操作"),
    ("运行|启动|停止|重启|kill", TaskCategory.HERMES, "任务涉及进程管理"),
    # C类: 系统工程 → agent
    (
        "开发.*系统|开发.*项目|开发.*平台|开发.*应用|开发.*服务|搭建.*系统",
        TaskCategory.AGENT,
        "任务涉及完整系统开发",
    ),
    (
        "设计.*架构|规划.*项目|整体.*重构|全栈|全部重写|完整.*改造",
        TaskCategory.AGENT,
        "任务涉及架构设计/全面重构",
    ),
    ("多.*步骤|复杂.*任务|完整.*流程|全套|整合|集成", TaskCategory.AGENT, "任务涉及多步骤复杂操作"),
    (
        "从零|从头|搭建.*框架|初始化.*项目|scaffold|skycaffold",
        TaskCategory.AGENT,
        "任务涉及项目初始化",
    ),
    (
        "实现.*功能|实现.*模块|实现.*接口.*数据库|实现.*前后端",
        TaskCategory.AGENT,
        "任务涉及多模块开发",
    ),
    # A类: 简单问答 → chat（默认兜底）
    (
        "问|什么是|解释|什么意思|为什么|如何理解|介绍|是什么|区别|对比|比较|区别是什么",
        TaskCategory.CHAT,
        "纯知识问答",
    ),
    (
        "能不能|可以吗|怎么办|有没有|是否|推荐|建议|评价|怎么样|如何选择",
        TaskCategory.CHAT,
        "咨询/建议类",
    ),
    ("你好|谢谢|帮助|help|功能|能用什么|你会什么|你是谁", TaskCategory.CHAT, "元对话/自我介绍"),
]


# 高风险关键词
RISK_KEYWORDS = [
    "删除.*系统|rm -rf|format|格式化|卸载.*驱动|删除.*注册表|del /s",
    "修改.*核心|修改.*配置.*系统|修改.*权限|chmod 777",
]


class IntentParser:
    """意图解析器"""

    def parse(self, message: str) -> ParsedIntent:
        """解析用户意图。"""
        category, reason = self._classify(message)
        ambiguity = self._detect_ambiguity(message)
        beautified = self._beautify(message, category)
        has_risk, risk_desc = self._check_risk(message)

        return ParsedIntent(
            raw_input=message,
            surface_text=message.split("\n")[0][:200],
            core_need=reason,
            ambiguity=ambiguity,
            task_category=category,
            beautified_command=beautified,
            has_risk=has_risk,
            risk_description=risk_desc,
        )

    def _classify(self, message: str) -> tuple[TaskCategory, str]:
        """基于规则+权重分类。"""
        scores: dict[TaskCategory, int] = {
            TaskCategory.CHAT: 0,
            TaskCategory.HERMES: 0,
            TaskCategory.AGENT: 0,
        }

        for pattern, category, _ in CATEGORY_RULES:
            weight = 1
            # 关键词越靠前，权重越高
            match = re.search(pattern, message)
            if match:
                # 前 30 字符匹配权重更高
                if match.start() < 30:
                    weight = 2
                scores[category] += weight

        # 短消息 → chat
        if len(message.strip()) < 8:
            return TaskCategory.CHAT, "短消息判断为简单问答"

        # 有具体文件路径 → hermes
        if re.search(r"\.(?:py|ts|js|json|html|css|md|yaml|yml|toml|cfg|ini|env)\b", message):
            scores[TaskCategory.HERMES] += 2

        # 长消息无明确操作 → hermes
        if (
            len(message) > 100
            and scores[TaskCategory.HERMES] == 0
            and scores[TaskCategory.AGENT] == 0
        ):
            scores[TaskCategory.HERMES] += 1
            return TaskCategory.HERMES, "长消息判断为有具体操作需求"

        # 选最高分
        max_cat = max(scores, key=scores.get)
        if scores[max_cat] == 0:
            return TaskCategory.CHAT, "默认简单问答"

        # 获取匹配到的 reason
        for pattern, category, reason in CATEGORY_RULES:
            if category == max_cat and re.search(pattern, message):
                return max_cat, reason

        return max_cat, f"分类得分最高: {max_cat.value}"

    def _detect_ambiguity(self, message: str) -> str:
        issues: list[str] = []

        if re.search(r"这个|那个|它|那个文件|刚才的|上面的|下面", message):
            issues.append("含模糊代词，缺少具体对象引用")

        if re.search(r"修改|修复|优化|重构", message) and not re.search(
            r"\.\w{1,5}\b|\S+/\S+", message
        ):
            issues.append("提到修改操作但未指定目标文件")

        if re.search(r"写|生成|开发|创建.*项目|搭建", message) and not re.search(
            r"python|fastapi|flask|django|react|vue|node|spring|go|rust|java|typescript|javascript",
            message,
            re.IGNORECASE,
        ):
            issues.append("涉及开发但未指定技术栈/框架，将默认使用 Python")

        return "；".join(issues) if issues else ""

    def _beautify(self, message: str, category: TaskCategory) -> str:
        """美化标准化指令。"""
        beautified = message.strip()

        if category == TaskCategory.HERMES:
            if not beautified.endswith(("。", ".", "!", "！", ")", "】")):
                beautified += "。"

        elif category == TaskCategory.AGENT:
            if "技术栈" not in beautified and not re.search(
                r"python|react|vue|node|spring|go", beautified, re.IGNORECASE
            ):
                beautified += "\n默认技术栈: Python 3.12+, FastAPI, Pydantic v2"

        return beautified

    def _check_risk(self, message: str) -> tuple[bool, str]:
        """检查高风险操作。"""
        for pattern in RISK_KEYWORDS:
            if re.search(pattern, message):
                return True, f"检测到高风险操作: {pattern}"
        return False, ""


# 便捷函数
def parse_intent(message: str) -> ParsedIntent:
    return IntentParser().parse(message)
