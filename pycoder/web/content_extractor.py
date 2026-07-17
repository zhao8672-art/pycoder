"""
内容提取器 — 将 HTML 转换为结构化 Markdown/纯文本

使用 html2text（如有）或正则回退，提取可读内容。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ExtractedContent:
    """提取的结构化内容"""
    title: str = ""
    text: str = ""
    html: str = ""
    url: str = ""
    links: list[dict] = None
    images: list[str] = None
    word_count: int = 0

    def __post_init__(self):
        if self.links is None:
            self.links = []
        if self.images is None:
            self.images = []


class ContentExtractor:
    """内容提取器 — HTML → 结构化 Markdown/纯文本"""

    def __init__(self):
        self._has_html2text = False
        self._try_import()

    def _try_import(self):
        try:
            import html2text  # noqa: F401
            self._has_html2text = True
        except ImportError:
            self._has_html2text = False

    async def extract(self, html: str, url: str = "") -> ExtractedContent:
        """从 HTML 提取结构化内容"""
        content = ExtractedContent(url=url, html=html[:100000])

        # 提取标题
        title_match = re.search(
            r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL
        )
        if title_match:
            content.title = title_match.group(1).strip()

        # 提取文本
        if self._has_html2text:
            import html2text
            h = html2text.HTML2Text()
            h.body_width = 0
            h.ignore_links = False
            h.ignore_images = False
            content.text = h.handle(html)
        else:
            content.text = self._html_to_text_fallback(html)

        # 提取链接
        for match in re.finditer(
            r'<a[^>]*href=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>',
            html,
            re.IGNORECASE,
        ):
            content.links.append({
                "url": match.group(1),
                "text": re.sub(r'<[^>]+>', '', match.group(2)).strip()[:100],
            })

        # 提取图片
        for match in re.finditer(
            r'<img[^>]*src=["\'](https?://[^"\']+)["\']',
            html,
            re.IGNORECASE,
        ):
            content.images.append(match.group(1))

        content.word_count = len(content.text.split())
        return content

    def _html_to_text_fallback(self, html: str) -> str:
        """无 html2text 时的正则回退"""
        text = html
        # 移除脚本和样式
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', ' ', text)
        # 压缩空白
        text = re.sub(r'\s+', ' ', text).strip()
        # 解码常见实体
        text = text.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
        text = text.replace('&quot;', '"').replace('&#39;', "'")
        return text[:50000]
