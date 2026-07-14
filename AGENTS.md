# pycode

> 自动生成于 2026-06-25 08:19 | PyCoder AGENTS.md

## 项目概述

- **项目名称**: pycode
- **主要语言**: Python 3.14.3
- **包管理器**: pip
- **项目类型**: Web 应用
- **框架**: FastAPI, pandas, NumPy, Matplotlib, Streamlit, pytest, Textual, Rich

## Python 编码规范

### 必须遵守

1. **PEP 8** — 代码风格严格遵循 PEP 8，使用 Black 自动格式化
2. **Type Hints** — 所有公共函数/方法必须有类型注解
3. **中文注释** — 注释和文档字符串使用中文
4. **现代语法** — 优先使用 Python 3.10+ 特性（match/case, `|` 联合类型, walrus `:=`）
5. **错误处理** — 使用具体异常类型，避免裸 `except:`
6. **f-string** — 字符串格式化统一使用 f-string

### 推荐做法

- 使用 `pathlib.Path` 替代 `os.path`
- 使用 `dataclasses` 或 `Pydantic` 定义数据模型
- 使用 `asyncio` 处理 I/O 密集型任务
- 配置通过环境变量 + `.env` 文件注入（python-dotenv）
- 敏感信息（API Key、密码）绝不硬编码

### 禁止做法

- ❌ 裸 `except:` 吞掉所有异常
- ❌ 使用 `from module import *`
- ❌ 在函数参数中使用可变默认值 `def f(x=[])`
- ❌ 硬编码文件路径（使用相对路径或配置）
- ❌ 在生产代码中使用 `print()` 调试（用 `logging`）

## 项目结构约定

```
project/
├── src/            # 源代码
├── tests/          # 测试（pytest）
├── docs/           # 文档
├── config/         # 配置文件
├── scripts/        # 工具脚本
├── pyproject.toml  # 项目元数据
├── .env.example    # 环境变量模板
└── AGENTS.md       # 本文件
```

## 测试规范

- 测试框架: **pytest**
- 覆盖率目标: >= 80%
- 测试文件命名: `test_<模块名>.py`
- CI 中必须通过全部测试才能合并

## Git 工作流

- 分支策略: `master` (稳定) + `feat/xxx` (功能) + `fix/xxx` (修复)
- 提交格式: `feat: xxx` / `fix: xxx` / `docs: xxx` / `refactor: xxx` / `test: xxx`
- PR 需要至少 1 人 Code Review 通过
- 合并前 squash commits 保持历史整洁

## 自动提交与推送

**每次完成任务后，AI 助手必须执行:**

```bash
cd C:\Users\Administrator\Desktop\pycode
python __git_commit_push.py "fix: 修改说明"
```

或双击 `__git_auto_push.bat` (Windows)

### post-commit 钩子自动推送

- `.git/hooks/post-commit` 已安装，每次 `git commit` 后自动执行 `git push origin master`
- Git 别名 `git acp "msg"` = add + commit + push 一步到位

### 手动方式

```bash
git add -A
git commit -m "fix: 说明"
git push origin master
```

## AI Agent 协作规则

当 AI 助手修改代码时，应遵循:

1. **先读后改** — 修改文件前先读取完整内容
2. **Diff 展示** — 修改后展示 unified diff，用户确认后写入
3. **保持一致性** — 遵循项目现有的代码风格和模式
4. **最小化改动** — 只修改必要的部分，不过度重构
5. **可回滚** — 重大改动前建议创建 git commit 或备份
6. **解释变更** — 每次修改附带中文说明原因

## 环境特定约定

### FastAPI 约定

- 使用 `async def` 处理路由
- 使用 Pydantic v2 模型定义请求/响应
- API 路径使用 RESTful 风格（复数名词）
- 依赖注入使用 `Depends()`

### 数据科学约定

- 使用 Jupyter Notebook 进行探索性分析
- 将可复用逻辑抽取为 .py 模块
- 数据处理管道使用函数式风格
- 结果可视化使用 matplotlib/seaborn

### 数据科学约定

- 使用 Jupyter Notebook 进行探索性分析
- 将可复用逻辑抽取为 .py 模块
- 数据处理管道使用函数式风格
- 结果可视化使用 matplotlib/seaborn

---

*此文件由 PyCoder 自动生成。运行 `python -m pycoder --agents` 重新生成。*
