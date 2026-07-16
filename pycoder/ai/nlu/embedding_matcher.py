"""
嵌入匹配引擎 — Layer 2 NLU

使用 Sentence-BERT 嵌入进行语义相似度匹配:
  - 将用户输入编码为嵌入向量
  - 与预定义的意图模板进行余弦相似度匹配
  - 返回 Top-K 匹配结果

运行时降级: 未安装 sentence-transformers 时使用简单词频匹配
"""

from __future__ import annotations

import logging
import math
from collections import Counter

logger = logging.getLogger(__name__)


# ── 意图模板嵌入签名（TF-IDF近似）──

INTENT_TEMPLATES: dict[str, list[str]] = {
    "generate_code": [
        "写一个函数实现",
        "帮我生代码",
        "实现一个功能",
        "写一个程序",
        "创建文件",
    ],
    "explain_code": [
        "这段代码是什么意思",
        "解释这个函数",
        "这段代码做了什么",
        "分析这段代码",
    ],
    "fix_bug": [
        "修复这个bug",
        "为什么报错",
        "这个错误怎么解决",
        "帮我调试",
    ],
    "refactor_code": [
        "重构这段代码",
        "优化这个实现",
        "改进代码质量",
        "重写这个函数",
    ],
    "review_code": [
        "审查代码",
        "代码走查",
        "review this code",
        "检查代码质量",
    ],
    "design_architecture": [
        "设计系统架构",
        "规划项目结构",
        "架构设计方案",
        "目录结构设计",
    ],
    "write_test": [
        "写测试用例",
        "单元测试",
        "编写测试",
        "测试覆盖率",
    ],
    "config_env": [
        "配置开发环境",
        "安装依赖",
        "部署服务",
        "设置项目",
    ],
    "documentation": [
        "写文档",
        "添加注释",
        "生成readme",
        "编写说明文档",
    ],
    "performance": [
        "性能优化",
        "分析性能瓶颈",
        "提高响应速度",
        "优化查询",
    ],
}


class EmbeddingMatcher:
    """Layer 2: 嵌入匹配层

    使用词频向量（Bag-of-Words）近似语义匹配。
    如果安装了 sentence-transformers，可升级为真嵌入向量。
    """

    def __init__(self) -> None:
        self._has_sentence_transformers = False
        self._model = None
        self._try_load_model()

        # 预计算模板特征
        self._template_features = {
            intent: self._bow_vector(" ".join(templates))
            for intent, templates in INTENT_TEMPLATES.items()
        }

    def _try_load_model(self) -> None:
        """尝试加载 sentence-transformers 模型"""
        try:
            import sentence_transformers  # noqa: F401
            self._has_sentence_transformers = True
        except ImportError:
            self._has_sentence_transformers = False

    async def match(self, text: str, top_k: int = 3) -> list[dict]:
        """匹配意图 — 返回 Top-K 结果"""
        if self._has_sentence_transformers:
            return await self._match_embedding(text, top_k)
        return self._match_bow(text, top_k)

    async def _match_embedding(self, text: str, top_k: int) -> list[dict]:
        """使用真嵌入向量匹配"""
        try:
            import numpy as np
            from sentence_transformers import SentenceTransformer

            if self._model is None:
                self._model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")

            text_vec = self._model.encode(text)
            results = []
            for intent, templates in INTENT_TEMPLATES.items():
                template_vec = self._model.encode(templates[0])
                sim = float(np.dot(text_vec, template_vec) / (
                    np.linalg.norm(text_vec) * np.linalg.norm(template_vec)
                ))
                results.append({
                    "intent": intent,
                    "confidence": round(max(0, sim), 3),
                    "method": "embedding",
                })

            results.sort(key=lambda x: x["confidence"], reverse=True)
            return results[:top_k]
        except Exception:
            # 降级到 BOW
            return self._match_bow(text, top_k)

    def _match_bow(self, text: str, top_k: int) -> list[dict]:
        """使用词袋模型近似匹配"""
        text_vec = self._bow_vector(text)
        results = []

        for intent, template_vec in self._template_features.items():
            sim = self._cosine_similarity(text_vec, template_vec)
            results.append({
                "intent": intent,
                "confidence": round(sim, 3),
                "method": "bow",
            })

        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:top_k]

    def _bow_vector(self, text: str) -> dict[str, float]:
        """构建词袋向量 (TF)"""
        import re
        words = re.findall(r"\w+", text.lower())
        total = max(len(words), 1)
        counter = Counter(words)
        return {word: count / total for word, count in counter.items()}

    def _cosine_similarity(
        self, vec1: dict[str, float], vec2: dict[str, float]
    ) -> float:
        """计算余弦相似度"""
        all_words = set(vec1) | set(vec2)
        dot_product = sum(vec1.get(w, 0) * vec2.get(w, 0) for w in all_words)
        norm1 = math.sqrt(sum(v * v for v in vec1.values()))
        norm2 = math.sqrt(sum(v * v for v in vec2.values()))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return dot_product / (norm1 * norm2)

    @property
    def has_embeddings(self) -> bool:
        """是否启用了真嵌入模型"""
        return self._has_sentence_transformers
