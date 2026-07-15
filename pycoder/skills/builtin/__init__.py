"""
内置技能注册表 — 预装 10+ 个核心技能

每个技能包含完整的 Markdown 内容，遵循 OpenClaw ClawHub 风格。
技能在 SkillMarketplace 初始化时自动预安装。
"""

from __future__ import annotations

from pycoder.skills import SkillDefinition

# ── 内置技能列表 ───────────────────────────────────

BUILTIN_SKILLS: list[SkillDefinition] = [
    # ── 1. code-review ──
    SkillDefinition(
        id="code-review",
        name="代码审查",
        version="1.0.0",
        description="审查代码质量和最佳实践，提供改进建议",
        author="PyCoder",
        category="quality",
        tags=["code-review", "quality", "best-practices", "代码审查", "质量"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 代码审查

## 技能描述
审查代码质量和最佳实践，识别潜在问题并提供改进建议。

## 功能
- 检查代码风格是否符合 PEP 8 规范
- 识别潜在的 bug 和逻辑错误
- 评估代码可读性和可维护性
- 检查类型注解是否完整
- 验证错误处理是否正确
- 分析代码复杂度

## 使用方式
```
请审查 [文件路径] 的代码质量
```

## 审查维度
1. **代码风格**: 缩进、命名规范、空行使用
2. **类型安全**: 类型注解完整性、类型推断
3. **错误处理**: 异常捕获粒度、错误信息清晰度
4. **性能**: 循环优化、数据结构选择
5. **安全性**: SQL 注入、XSS、路径遍历
6. **可维护性**: 函数长度、模块耦合度

## 输出格式
- 严重程度: 🔴 严重 / 🟡 警告 / 🔵 建议
- 问题位置: 文件:行号
- 整改建议: 具体的修改方案
""",
    ),
    # ── 2. test-generator ──
    SkillDefinition(
        id="test-generator",
        name="测试生成器",
        version="1.0.0",
        description="自动生成单元测试代码",
        author="PyCoder",
        category="testing",
        tags=["test", "unit-test", "pytest", "测试", "单元测试"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 测试生成器

## 技能描述
自动分析源代码并生成高质量的单元测试代码。

## 功能
- 自动生成 pytest 测试用例
- 覆盖正常路径和边界条件
- 支持 mock 和 fixture 生成
- 测试异常和错误处理路径
- 生成参数化测试

## 使用方式
```
请为 [文件路径] 生成单元测试
```

## 测试覆盖
1. **正常路径**: 标准输入 → 预期输出
2. **边界条件**: 空值、极限值、特殊字符
3. **错误路径**: 无效输入、异常抛出
4. **Mock 依赖**: 外部服务、数据库、文件系统

## 生成规范
- 使用 pytest 框架
- 测试函数命名: `test_<功能描述>`
- 使用 `@pytest.mark.parametrize` 进行参数化
- 遵循 AAA 模式: Arrange → Act → Assert
""",
    ),
    # ── 3. doc-generator ──
    SkillDefinition(
        id="doc-generator",
        name="文档生成器",
        version="1.0.0",
        description="为代码生成文档和注释",
        author="PyCoder",
        category="documentation",
        tags=["doc", "documentation", "docstring", "文档", "注释"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 文档生成器

## 技能描述
为 Python 代码自动生成 Google 风格的 docstring 和文档。

## 功能
- 为函数/类/模块生成 docstring
- 支持 Google 和 NumPy 风格
- 生成类型注解的文档
- 生成 README 文件
- 提取 API 文档

## 使用方式
```
请为 [文件路径/函数名] 生成文档
```

## 文档格式
```python
def example(param1: str, param2: int = 0) -> bool:
    \"\"\"简短描述。

    Args:
        param1: 参数1的描述
        param2: 参数2的描述，默认值为0

    Returns:
        返回值的描述

    Raises:
        ValueError: 当参数无效时抛出
    \"\"\"
```

## 生成规则
- 分析函数签名和类型注解
- 从代码逻辑推断参数含义
- 识别异常抛出点
- 提供使用示例
""",
    ),
    # ── 4. refactor-helper ──
    SkillDefinition(
        id="refactor-helper",
        name="重构助手",
        version="1.0.0",
        description="帮助重构代码，提高代码质量",
        author="PyCoder",
        category="refactoring",
        tags=["refactor", "重构", "clean-code", "优化"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 重构助手

## 技能描述
帮助识别代码异味并提供重构方案，提高代码质量和可维护性。

## 功能
- 提取重复代码为函数/类
- 简化复杂条件表达式
- 优化循环和列表推导式
- 拆分过长函数
- 引入设计模式
- 改善命名

## 使用方式
```
请重构 [文件路径/函数名]
```

## 重构模式
1. **提取函数**: 将长函数拆分为多个小函数
2. **提取类**: 将相关函数和数据封装为类
3. **简化条件**: 使用 match/case 替代 if-elif 链
4. **引入参数对象**: 合并多个相关参数
5. **以多态替换条件**: 使用策略模式

## 重构原则
- 保持功能不变
- 小步提交，每次一个重构
- 确保测试通过
- 改善可读性优先
""",
    ),
    # ── 5. security-scanner ──
    SkillDefinition(
        id="security-scanner",
        name="安全扫描器",
        version="1.0.0",
        description="扫描代码中的安全漏洞和风险",
        author="PyCoder",
        category="security",
        tags=["security", "scan", "vulnerability", "安全", "漏洞"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 安全扫描器

## 技能描述
扫描代码中的安全漏洞、敏感信息泄露和常见安全风险。

## 功能
- SQL 注入检测
- XSS 漏洞检测
- 硬编码密钥检测
- 路径遍历检测
- 不安全的反序列化
- 依赖漏洞检查

## 使用方式
```
请扫描 [文件路径] 的安全问题
```

## 扫描规则
1. **SQL 注入**: 字符串拼接 SQL、未参数化查询
2. **XSS**: 未转义的用户输入输出
3. **密钥泄露**: API Key、密码、Token 硬编码
4. **路径遍历**: 未验证的文件路径拼接
5. **反序列化**: pickle/yaml.unsafe_load 使用
6. **命令注入**: os.system/subprocess 拼接用户输入

## 安全等级
- 🔴 严重: 可被利用的漏洞
- 🟡 警告: 潜在风险
- 🔵 建议: 安全最佳实践
""",
    ),
    # ── 6. performance-analyzer ──
    SkillDefinition(
        id="performance-analyzer",
        name="性能分析器",
        version="1.0.0",
        description="分析代码性能瓶颈和优化机会",
        author="PyCoder",
        category="performance",
        tags=["performance", "optimize", "性能", "优化"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 性能分析器

## 技能描述
分析代码性能瓶颈，识别优化机会，提供改进建议。

## 功能
- 时间复杂度分析
- 内存使用分析
- 循环优化建议
- 数据结构选择建议
- I/O 优化建议
- 并发优化建议

## 使用方式
```
请分析 [文件路径/函数名] 的性能
```

## 分析维度
1. **算法复杂度**: O(n) → O(1) 的优化机会
2. **数据结构**: list → set/dict 的场景
3. **循环优化**: 列表推导式、生成器表达式
4. **内存优化**: `__slots__`、弱引用
5. **I/O 优化**: 批量操作、缓存
6. **并发**: asyncio、线程池

## 优化建议格式
- 位置: 文件:行号
- 问题: 当前实现的性能问题
- 建议: 优化方案
- 收益: 预期性能提升
""",
    ),
    # ── 7. git-helper ──
    SkillDefinition(
        id="git-helper",
        name="Git 助手",
        version="1.0.0",
        description="帮助进行 Git 操作和版本管理",
        author="PyCoder",
        category="tools",
        tags=["git", "version-control", "版本控制"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# Git 助手

## 技能描述
帮助进行 Git 操作，包括提交、分支管理、合并冲突解决等。

## 功能
- 生成规范的提交信息
- 解决合并冲突
- 分支管理建议
- 代码回滚操作
- 交互式 rebase
- .gitignore 管理

## 使用方式
```
请帮我 [Git 操作描述]
```

## 支持的 Git 操作
1. **提交**: 生成 Conventional Commits 格式的提交信息
2. **分支**: 创建、切换、合并、删除分支
3. **冲突**: 分析冲突并提供解决方案
4. **回滚**: reset、revert 操作指导
5. **历史**: log、blame、diff 分析
6. **标签**: 创建和管理版本标签

## 提交信息格式
```
<type>(<scope>): <description>

[optional body]

[optional footer]
```
类型: feat, fix, docs, style, refactor, test, chore
""",
    ),
    # ── 8. dependency-checker ──
    SkillDefinition(
        id="dependency-checker",
        name="依赖检查器",
        version="1.0.0",
        description="检查项目依赖的版本、兼容性和安全性",
        author="PyCoder",
        category="tools",
        tags=["dependency", "package", "依赖", "包管理"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 依赖检查器

## 技能描述
检查项目依赖的版本兼容性、安全漏洞和更新建议。

## 功能
- 依赖版本冲突检测
- 依赖安全漏洞扫描
- 过期依赖检测
- 依赖树分析
- 许可证合规检查
- 依赖大小分析

## 使用方式
```
请检查 [项目] 的依赖情况
```

## 检查维度
1. **版本冲突**: 不同包要求的同一依赖版本不一致
2. **安全漏洞**: 已知 CVE 的依赖版本
3. **过期依赖**: 有更新版本的依赖
4. **许可证**: 不兼容的开源许可证
5. **大小**: 依赖包体积分析

## 输出格式
- 包名: 当前版本 → 建议版本
- 风险等级: 🔴 严重 / 🟡 警告 / 🔵 信息
- 建议操作: 升级 / 降级 / 替换
""",
    ),
    # ── 9. lint-fixer ──
    SkillDefinition(
        id="lint-fixer",
        name="Lint 修复器",
        version="1.0.0",
        description="自动修复代码 Lint 问题",
        author="PyCoder",
        category="quality",
        tags=["lint", "fix", "format", "代码规范"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# Lint 修复器

## 技能描述
自动检测并修复代码中的 Lint 问题，包括风格、格式和潜在错误。

## 功能
- 修复 PEP 8 风格问题
- 修复 import 排序问题
- 修复未使用的变量和导入
- 修复行长度问题
- 修复空白和缩进
- 应用代码格式化

## 使用方式
```
请修复 [文件路径] 的 Lint 问题
```

## 修复规则
1. **E501**: 行长度超过 79 字符
2. **F401**: 未使用的导入
3. **F841**: 未使用的变量
4. **E302**: 缺少空行
5. **W291**: 行尾空白
6. **I001**: import 排序

## 修复策略
- 自动修复: 安全无副作用的修改
- 提示修复: 需要人工确认的修改
- 忽略: 有意为之的代码风格
""",
    ),
    # ── 10. api-doc-generator ──
    SkillDefinition(
        id="api-doc-generator",
        name="API 文档生成器",
        version="1.0.0",
        description="为 FastAPI/Flask 项目生成 API 文档",
        author="PyCoder",
        category="documentation",
        tags=["api", "fastapi", "openapi", "swagger", "文档"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# API 文档生成器

## 技能描述
为 FastAPI/Flask/Django 项目自动生成 API 文档，包括请求示例和响应格式。

## 功能
- 生成 OpenAPI 规范文档
- 提取路由和参数信息
- 生成请求/响应示例
- 生成错误码文档
- 生成认证说明
- 生成变更日志

## 使用方式
```
请为 [项目] 生成 API 文档
```

## 文档格式
```markdown
## GET /api/users

获取用户列表

### 请求参数
| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| page | int | 否 | 页码 |
| limit | int | 否 | 每页数量 |

### 响应示例
```json
{
  "data": [...],
  "total": 100
}
```

### 错误码
| 状态码 | 说明 |
|--------|------|
| 200 | 成功 |
| 401 | 未认证 |
```

## 支持框架
- FastAPI: 自动提取 Pydantic 模型
- Flask: 扫描路由装饰器
- Django REST: 扫描 ViewSet
""",
    ),
    # ── 11. code-explainer ──
    SkillDefinition(
        id="code-explainer",
        name="代码解释器",
        version="1.0.0",
        description="解释代码逻辑和工作原理",
        author="PyCoder",
        category="documentation",
        tags=["explain", "code", "理解", "解释"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 代码解释器

## 技能描述
用通俗易懂的语言解释代码逻辑、算法和数据流，帮助理解复杂代码。

## 功能
- 逐行解释代码逻辑
- 解释算法原理
- 绘制数据流图
- 解释设计模式
- 对比不同实现方式

## 使用方式
```
请解释 [文件路径/代码片段] 的工作原理
```

## 解释层次
1. **概览**: 整体功能和架构
2. **流程**: 主要执行流程
3. **细节**: 关键算法和数据结构
4. **示例**: 具体输入输出示例

## 输出格式
- 功能概述: 代码做什么
- 执行流程: 代码如何工作
- 关键概念: 涉及的算法/模式
- 使用示例: 如何调用
""",
    ),
    # ── 12. project-scaffolder ──
    SkillDefinition(
        id="project-scaffolder",
        name="项目脚手架",
        version="1.0.0",
        description="快速生成项目结构和模板代码",
        author="PyCoder",
        category="tools",
        tags=["scaffold", "template", "project", "脚手架", "模板"],
        dependencies=[],
        is_builtin=True,
        markdown_content="""# 项目脚手架

## 技能描述
根据项目类型快速生成标准的项目结构和模板代码。

## 功能
- 生成 FastAPI 项目结构
- 生成 Streamlit 应用结构
- 生成 CLI 工具结构
- 生成 pytest 测试结构
- 生成 Docker 配置
- 生成 CI/CD 配置

## 使用方式
```
请生成一个 [项目类型] 项目
```

## 支持的项目类型
1. **FastAPI**: REST API 服务
2. **Streamlit**: 数据可视化应用
3. **CLI**: 命令行工具
4. **Library**: Python 库
5. **Data Science**: 数据分析项目

## 生成结构示例
```
myproject/
├── src/
│   └── myproject/
│       ├── __init__.py
│       ├── main.py
│       └── models.py
├── tests/
│   ├── __init__.py
│   └── test_main.py
├── pyproject.toml
├── Dockerfile
└── README.md
```
""",
    ),
]

# ── 按分类组织的技能索引 ──────────────────────────

SKILLS_BY_CATEGORY: dict[str, list[str]] = {
    "quality": ["code-review", "lint-fixer"],
    "testing": ["test-generator"],
    "documentation": ["doc-generator", "api-doc-generator", "code-explainer"],
    "refactoring": ["refactor-helper"],
    "security": ["security-scanner"],
    "performance": ["performance-analyzer"],
    "tools": ["git-helper", "dependency-checker", "project-scaffolder"],
}


def get_builtin_skill(skill_id: str) -> SkillDefinition | None:
    """按 ID 获取内置技能定义"""
    for skill in BUILTIN_SKILLS:
        if skill.id == skill_id:
            return skill
    return None


def get_builtin_skills_by_category(category: str) -> list[SkillDefinition]:
    """按分类获取内置技能列表"""
    ids = SKILLS_BY_CATEGORY.get(category, [])
    return [s for s in BUILTIN_SKILLS if s.id in ids]