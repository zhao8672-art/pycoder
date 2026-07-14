"""
Skills 可用性检测 — 判断技能是否需要外部 API Key / 特定环境

在 skills_market_v2.py 的 search() 中集成后，
每个技能会附带 `needs_external_api` 和 `api_services` 字段，
让 AI 和用户提前知道哪些技能需要额外配置。
"""

from __future__ import annotations

EXTERNAL_API_PATTERNS = [
    "openai", "api_key", "api key", "token", "secret",
    "bearer", "authorization", "muapi",
    "huggingface", "hugging face",
    "stripe", "twilio", "sendgrid",
    "aws_", "gcp_", "azure_",
]

EXTERNAL_API_KEYWORDS = [
    "需要 API", "需要密钥", "api_key", "token",
    "requires", "api key",
]


def check_skill_usability(skill: dict) -> dict:
    """检测技能是否可开箱即用

    Args:
        skill: 技能字典（含 description、tags、name、url 等字段）

    Returns:
        {
            "needs_external_api": bool,
            "api_services": list[str],
            "usable_offline": bool,
        }
    """
    description = (skill.get("description") or "").lower()
    name = (skill.get("name") or "").lower()
    tags = [t.lower() for t in (skill.get("tags") or [])]
    url = (skill.get("url") or "").lower()

    detected_services: set[str] = set()
    all_text = f"{description} {name} {' '.join(tags)} {url}"

    for pattern in EXTERNAL_API_PATTERNS:
        if pattern in all_text:
            detected_services.add(pattern)

    for kw in EXTERNAL_API_KEYWORDS:
        if kw in description or kw in name:
            detected_services.add(kw)

    return {
        "needs_external_api": len(detected_services) > 0,
        "api_services": sorted(detected_services),
        "usable_offline": len(detected_services) == 0,
    }


def batch_check_skills(skills: list[dict]) -> list[dict]:
    """批量检测并更新技能字典"""
    for skill in skills:
        usability = check_skill_usability(skill)
        skill["needs_external_api"] = usability["needs_external_api"]
        skill["api_services"] = usability["api_services"]
        skill["usable_offline"] = usability["usable_offline"]
    return skills
