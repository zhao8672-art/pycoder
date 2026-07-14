"""
交互式图表生成器 — Plotly/Altair/Matplotlib

生成可直接在 UI 中嵌入的 HTML 交互式图表。
"""

from __future__ import annotations

import json
import tempfile


class ChartGenerator:
    """图表生成引擎"""

    def plotly_chart(self, chart_type: str, data: list[dict], title: str = "") -> dict:
        """生成 Plotly 交互式 HTML 图表"""
        html = f"""<!DOCTYPE html>
<html><head><script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
<style>body{{margin:0;background:#1a1b2e}}.chart{{width:100%;height:100vh}}</style></head>
<body><div id="chart" class="chart"></div><script>
var data = {json.dumps(data)};
var trace = {{x: data.map(d=>d.x||d.label||d.name), y: data.map(d=>d.y||d.value||0),
type: '{chart_type}', name: '{title}', marker: {{color: '#7c6ef0'}}}};
var layout = {{title: '{title}', paper_bgcolor: '#1a1b2e', plot_bgcolor: '#1a1b2e',
font: {{color: '#e4e4f0'}}, xaxis: {{gridcolor: '#2a2a40'}},
yaxis: {{gridcolor: '#2a2a40'}}}};
Plotly.newPlot('chart', [trace], layout);
</script></body></html>"""

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".html",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(html)
            chart_path = f.name

        return {
            "success": True,
            "chart_path": chart_path,
            "chart_type": chart_type,
            "title": title,
            "data_points": len(data),
            "is_interactive": True,
        }

    def altair_chart(self, data: list[dict], x_field: str, y_field: str, title: str = "") -> dict:
        """生成 Altair 规范（JSON 格式）"""
        spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "title": title,
            "data": {"values": data},
            "mark": "bar",
            "encoding": {
                "x": {"field": x_field, "type": "nominal"},
                "y": {"field": y_field, "type": "quantitative"},
            },
        }
        return {
            "success": True,
            "spec": spec,
            "note": "Altair/Vega-Lite 规范，可嵌入前端渲染",
        }

    def flame_graph_data(self, profile_result: dict) -> dict:
        """从性能分析结果生成火焰图数据"""
        if not profile_result.get("output"):
            return {"success": False, "error": "需要 profile_python 输出"}

        lines = profile_result["output"].split("\n")
        frames = []
        total = 0
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    count = int(parts[0])
                    total += count
                    func = parts[-1]
                    frames.append({"name": func, "value": count})
                except ValueError:
                    continue

        return {
            "success": True,
            "total_calls": total,
            "frames": frames[:50],
            "format": "flame_graph",
            "note": "可嵌入 flamegraph-js 渲染交互式火焰图",
        }

    def quick_charts(self, data: list[dict]) -> list[dict]:
        """一行代码生成多种图表类型"""
        return [
            {"type": "bar", "chart": self.plotly_chart("bar", data, "柱状图")},
            {"type": "line", "chart": self.plotly_chart("scatter", data, "折线图")},
            {"type": "pie", "chart": self.plotly_chart("pie", data, "饼图")},
        ]


_chart_gen: ChartGenerator | None = None


def get_chart_generator() -> ChartGenerator:
    global _chart_gen
    if _chart_gen is None:
        _chart_gen = ChartGenerator()
    return _chart_gen
