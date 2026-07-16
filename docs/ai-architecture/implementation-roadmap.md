# PyCoder AI 竞品差距弥补 — 实施路线图

> 目标: 在 4 周内将 PyCoder AI 能力从当前水平提升至接近竞品水平
> 策略: 利用现有 `pycoder/ai/` 接口层，有重点地逐个实现差距弥补

---

## 实施总览

| 阶段 | 时间 | 优先级 | 弥补差距 | 预期提升 |
|------|------|--------|----------|----------|
| P0 | 0-3天 | **critical** | 多层级代码分析(-7.0) + NLU消歧(-5.5) | 分析能力 45%→80% |
| P1 | 3-7天 | **high** | 多策略代码生成(-6.0) + 代码度量(-6.5) + 安全扫描(-6.0) | 生成能力 62%→80% |
| P2 | 7-14天 | medium | FIM补全(-6.5) + KV Cache(-5.0) + 工具原子性(-5.0) | 延迟降低 1200ms→600ms |
| P3 | 14-28天 | ongoing | 对话状态追踪(-5.5) + 多模型融合(-5.0) + 迭代优化 | 全面接近竞品水平 |

---

## P0: 多层级代码分析引擎 (0-3天)

### 架构

```
CodeAnalysisRequest
    │
    ├─ Layer 1: SYNTAX → AST解析(Python内置ast) → 语法错误/风格问题
    ├─ Layer 2: SEMANTIC → 类型推导(Pylance LSP) → 类型错误/空引用
    ├─ Layer 3: STRUCTURAL → 调用图 → 耦合度/循环依赖
    ├─ Layer 4: ARCHITECTURAL → 模式识别 → 架构异味/设计问题
    └─ Layer 5: BEHAVIORAL → 复杂度分析 → 性能热点
```

### 实现文件

| 文件 | 说明 |
|------|------|
| `pycoder/ai/analysis/__init__.py` | 模块入口 |
| `pycoder/ai/analysis/syntax_analyzer.py` | 语法级分析 (AST) |
| `pycoder/ai/analysis/semantic_analyzer.py` | 语义级分析 (LSP) |
| `pycoder/ai/analysis/structural_analyzer.py` | 结构级分析 (调用图) |
| `pycoder/ai/analysis/architectural_analyzer.py` | 架构级分析 |
| `pycoder/ai/analysis/composite_analyzer.py` | 复合分析器 (整合5层) |

### 代码示例 (核心)

```python
class CompositeAnalyzer(ICodeAnalyzer):
    """复合分析器 — 整合五层分析"""
    async def analyze(self, request: CodeAnalysisRequest) -> AnalysisResult:
        layers = {
            AnalysisDepth.SYNTAX: self._syntax_analyze,
            AnalysisDepth.SEMANTIC: self._semantic_analyze,
            AnalysisDepth.STRUCTURAL: self._structural_analyze,
            AnalysisDepth.ARCHITECTURAL: self._architectural_analyze,
            AnalysisDepth.BEHAVIORAL: self._behavioral_analyze,
        }
        # 并行执行所有 <= request.depth 的分析层
        tasks = []
        for depth, func in layers.items():
            if depth.value <= request.depth.value:
                tasks.append(func(request))
        results = await asyncio.gather(*tasks)
        return self._merge_results(results)
```

---

## P0: 上下文感知NLU消歧 (0-3天)

### 三层管道

```
输入文本
  │
  ├─ Layer 1: 规则快速通道 (0 Token, <1ms)
  │    ├─ 关键词匹配 → 技术领域检测
  │    ├─ 正则模式 → 任务类型检测
  │    └─ 词频分析 → 复杂度评估
  │
  ├─ Layer 2: 嵌入相似度 (<10ms)
  │    ├─ Sentence-BERT 嵌入
  │    └─ 余弦相似度 → 意图匹配
  │
  └─ Layer 3: LLM深度理解 (歧义>阈值时触发)
       ├─ Chain-of-Thought推理
       └─ 结构化输出 (JSON)
```

### 实现文件

| 文件 | 说明 |
|------|------|
| `pycoder/ai/nlu/__init__.py` | 模块入口 |
| `pycoder/ai/nlu/rule_classifier.py` | 规则快速通道 |
| `pycoder/ai/nlu/embedding_matcher.py` | 嵌入匹配层 |
| `pycoder/ai/nlu/deep_analyzer.py` | LLM深度分析 |
| `pycoder/ai/nlu/composite_nlu.py` | 三层复合NLU引擎 |

---

## P1: 多策略代码生成器 (3-7天)

```
CodeGenStrategy 选择器:
  SINGLE_PASS  → 一次生成 (简单代码)
  ITERATIVE    → 生成→验证→优化循环 (复杂算法)
  TEST_DRIVEN  → 测试→生成→验证 (有测试用例)
  SPEC_DRIVEN  → 规约→生成→验证 (有接口定义)
  TEMPLATE_BASED → 模板匹配 (常见模式)
```

### 实现文件

| 文件 | 说明 |
|------|------|
| `pycoder/ai/generation/__init__.py` | 模块入口 |
| `pycoder/ai/generation/single_pass.py` | 单次生成 |
| `pycoder/ai/generation/iterative.py` | 迭代优化 |
| `pycoder/ai/generation/test_driven.py` | 测试驱动生成 |
| `pycoder/ai/generation/multi_strategy.py` | 策略选择器 |

---

## P1: 代码度量与安全扫描 (3-7天)

### 度量维度

| 指标 | 公式 | 工具 |
|------|------|------|
| McCabe复杂度 | 决策点+1 | `radon cc` |
| 可维护性指数 | 综合公式 | `radon mi` |
| 耦合度 | 外部引用/总模块 | 自实现 |
| 代码行数 | LOC/SLOC/LLOC | 自实现 |
| 注释密度 | 注释行/总行 | 自实现 |

### 安全扫描

| 类别 | 规则源 | 检测项 |
|------|--------|--------|
| OWASP Top 10 | 自定义规则 | SQL注入/XSS/命令注入等 |
| 敏感信息泄露 | 正则匹配 | API Key/密码/Token |
| 危险函数 | 函数调用检测 | eval/exec/pickle等 |

---

## P2: FIM补全 + KV Cache (7-14天)

### FIM 补全

```python
class FIMCodeCompleter:
    """Fill-in-the-Middle 代码补全"""
    async def complete(self, prefix: str, suffix: str, language: str) -> str:
        # 使用 DeepSeek FIM 专用 API
        # POST https://api.deepseek.com/beta/completions
        # 参数: prompt=prefix, suffix=suffix
        ...
```

### KV Cache 持久化

```python
class PromptCache:
    """LLM Prompt 前缀缓存"""
    async def get_or_compute(self, prefix_hash: str, compute_fn):
        # 1. 检查本地 KV Cache (SQLite)
        # 2. 命中 → 追加新 tokens 发送
        # 3. 未命中 → 调用 LLM + 缓存结果
        ...
```

---

## 预期效果

| 指标 | 当前 | P0后 | P1后 | P2后 | P3后 |
|------|------|------|------|------|------|
| 代码生成 pass@1 | 62% | 65% | 78% | 82% | **85%** |
| 代码分析召回率 | 45% | **75%** | 80% | 82% | **85%** |
| NLU 意图准确率 | 55% | **82%** | 85% | 87% | **90%** |
| 首 Token 延迟 | 1200ms | 1000ms | 800ms | **500ms** | 450ms |
| 综合评分 | 5.8 | 7.0 | 8.0 | 8.5 | **9.0** |

---

## 实施原则

1. **最小化改动** — 每个模块独立实现，不影响现有功能
2. **先接口后实现** — 先定义抽象接口，再填充具体逻辑
3. **测试先行** — 每个模块有完整的 pytest 覆盖
4. **渐进集成** — 通过 `AIFacade` 统一门面逐步替换旧模块
5. **可回滚** — 每个阶段提交独立 git commit
