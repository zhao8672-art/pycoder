# 贡献指南 (Contributing Guide)

欢迎你参与 PyCoder 项目的开发！本指南帮助你快速上手。

## 开发环境搭建

```bash
# 1. 克隆仓库
git clone https://github.com/zhao8672-art/pycoder.git
cd pycoder

# 2. 安装 Python 依赖
pip install -e ".[dev]"

# 3. 安装 Electron 前端依赖
cd pycoder/electron
npm install
cd ../..

# 4. 复制环境配置
cp .env.example .env
```

## 项目结构

```
pycoder/
├── pycoder/           # Python 后端核心
│   ├── server/        # FastAPI 服务 + 路由
│   ├── providers/     # AI 模型适配层
│   ├── python/        # 工具库（代码质量/执行/重构等）
│   └── electron/      # Electron 桌面端（React + TypeScript）
├── tests/             # 自动化测试
├── docs/              # 文档
├── scripts/           # 工具脚本
└── AGENTS.md          # AI Agent 协作约定
```

## 开发流程

```bash
# 启动后端（端口 8423）
python -m pycoder --server

# 构建前端
cd pycoder/electron && npm run build

# 启动桌面端（需先启动后端）
npm run start:prod

# 运行测试
pytest tests/ -v

# 带覆盖率
pytest tests/ --cov=pycoder --cov-report=html
```

## 代码规范

| 规范 | 要求 |
| --- | --- |
| Python 风格 | PEP 8 + Black |
| TypeScript | ESLint + Prettier |
| 类型注解 | 所有公开函数必须标注 |
| 注释语言 | 中文注释 |
| 错误处理 | 使用具体异常类型，禁止裸 `except:` |

## 提交规范

提交信息格式：`<type>: <描述>`

- `feat:` — 新功能
- `fix:` — 故障修复
- `refactor:` — 重构
- `docs:` — 文档
- `test:` — 测试
- `chore:` — 构建/工具

## 测试要求

- 覆盖率目标：>= 80%
- 新功能必须附带测试
- 运行 `pytest tests/ -v` 全部通过后再提交

## PR 流程

1. 创建功能分支: `feat/xxx` 或 `fix/xxx`
2. 开发并添加测试
3. 确保 CI 全部通过
4. 创建 Pull Request
5. 至少 1 人 Code Review

## 安全注意事项

- **绝不在代码中硬编码密钥/密码**
- 敏感配置通过环境变量注入（参考 `.env.example`）
- 生产环境必须设置 `PYCODER_CLOUD_JWT_SECRET` 和 `PYCODER_API_KEY`
