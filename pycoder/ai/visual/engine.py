"""可视化引擎 — 让 AI 能生成并展示图表/流程图/数据可视化

支持:
  - Mermaid 图表 (流程图/时序图/类图/甘特图)
  - Matplotlib 图表 (柱状/折线/饼图/散点图)
  - Plotly 交互式图表
  - 内联 Base64 渲染 (前端自动展示)
"""

from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)


class VisualizationEngine:
    """可视化引擎"""

    async def render_mermaid(self, mermaid_code: str) -> dict:
        """生成 Mermaid 图表代码"""
        return {
            "success": True,
            "type": "mermaid",
            "code": mermaid_code,
            "snippet": (
                "```mermaid\n" + mermaid_code + "\n```\n\n"
                "> 💡 在 PyCoder IDE 中可自动渲染此图表"
            ),
        }

    async def render_chart(self, chart_type: str, data: list,
                           title: str = "", **kwargs) -> dict:
        """生成 matplotlib 数据图表"""
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(10, 6))

            if chart_type == "bar":
                labels = [d.get("label", "") for d in data]
                values = [d.get("value", 0) for d in data]
                ax.bar(labels, values)
            elif chart_type == "line":
                x = [d.get("x", i) for i, d in enumerate(data)]
                y = [d.get("y", 0) for d in data]
                ax.plot(x, y, marker="o")
            elif chart_type == "pie":
                labels = [d.get("label", "") for d in data]
                values = [d.get("value", 0) for d in data]
                ax.pie(values, labels=labels, autopct="%1.1f%%")
            elif chart_type == "scatter":
                x = [d.get("x", 0) for d in data]
                y = [d.get("y", 0) for d in data]
                ax.scatter(x, y)

            if title:
                ax.set_title(title)

            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            plt.close()
            b64 = base64.b64encode(buf.getvalue()).decode()

            return {
                "success": True,
                "type": "image",
                "format": "png",
                "data_uri": f"data:image/png;base64,{b64}",
                "size_kb": round(len(buf.getvalue()) / 1024, 1),
            }
        except ImportError as exc:
            return {"success": False, "error": f"matplotlib 未安装: {exc}"}

    async def generate_html(self, title: str, body_html: str) -> dict:
        """生成 HTML 页面"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>{title}</title>
<style>
body {{ font-family: -apple-system, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; }}
code {{ background: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
pre {{ background: #f8f8f8; padding: 15px; border-radius: 5px; overflow-x: auto; }}
</style></head>
<body>
<h1>{title}</h1>
{body_html}
</body></html>"""
        return {
            "success": True,
            "type": "html",
            "html": html,
            "snippet": f"✅ 已生成 HTML 页面: {title}",
        }


# ══════════════════════════════════════════════════════════
# 工具定义
# ══════════════════════════════════════════════════════════

VIZ_TOOLS: list[dict] = [
    {
        "name": "viz_mermaid",
        "description": "生成 Mermaid 图表：流程图、时序图、类图、甘特图",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Mermaid 代码"},
            },
            "required": ["code"],
        },
    },
    {
        "name": "viz_chart",
        "description": "生成数据图表：柱状图/折线图/饼图/散点图",
        "parameters": {
            "type": "object",
            "properties": {
                "chart_type": {"type": "string", "enum": ["bar", "line", "pie", "scatter"]},
                "data": {
                    "type": "array",
                    "description": "数据数组，每项包含 label/value 或 x/y",
                },
                "title": {"type": "string"},
            },
            "required": ["chart_type", "data"],
        },
    },
    {
        "name": "viz_html",
        "description": "生成包含样式和交互的 HTML 页面",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body_html": {"type": "string", "description": "HTML body 内容"},
            },
            "required": ["title", "body_html"],
        },
    },
]


async def execute_viz_mermaid(code: str) -> dict:
    engine = VisualizationEngine()
    return await engine.render_mermaid(code)


async def execute_viz_chart(chart_type: str, data: list, title: str = "") -> dict:
    engine = VisualizationEngine()
    return await engine.render_chart(chart_type, data, title)


async def execute_viz_html(title: str, body_html: str) -> dict:
    engine = VisualizationEngine()
    return await engine.generate_html(title, body_html)
