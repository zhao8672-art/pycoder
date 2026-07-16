# PyCoder 升级迁移指南

> 版本: 1.0 | 更新时间: 2026-07-16 | 适用版本: v0.4.x → v0.5.0 → v1.0.0

---

## 1. 升级概览

本文档描述从 PyCoder 旧版本升级到新版本所需的步骤和注意事项。

### 1.1 版本路线

```
v0.3.x ──────▶ v0.4.x ──────▶ v0.5.0 ──────▶ v1.0.0
(基础版)      (扩展版)       (当前版本)      (目标版本)
```

### 1.2 升级影响矩阵

| 升级路径 | 数据兼容 | API 兼容 | 配置变更 | 建议操作 |
|---------|---------|---------|---------|---------|
| v0.4.x → v0.5.0 | 兼容 | 部分新增 | 新增环境变量 | 直接升级 |
| v0.5.0 → v1.0.0 | 需迁移 | 新增端点 | 结构变更 | 执行迁移脚本 |

---

## 2. v0.4.x → v0.5.0 升级

### 2.1 新增功能

- **V2 能力总线**: 119 个统一注册的 AI 能力
- **AI 大脑核心**: 意识引擎 + 任务规划器 + Agent 集群编排
- **5 级安全权限模型**: L0-L4 渐进信任 + 审计追踪 + 回滚 + 熔断
- **自进化引擎**: 8 步闭环扫描→分析→修复→测试→部署→学习
- **多平台消息网关**: Telegram、Discord、Slack、CLI 适配器
- **Docker 沙箱隔离**: 容器级代码执行，网络隔离 + 资源限制
- **4 级深度记忆**: ChromaDB 向量数据库 + 分级存储
- **幻觉抑制守卫**: SourceTracer + FactChecker 双重校验
- **DAG 并行任务调度**: 拓扑排序 + 并行执行
- **闭环学习循环**: 反馈收集→模式提取→自我优化

### 2.2 新增环境变量

```bash
# v0.5.0 新增
PYCODER_API_KEY=<key>          # API 认证密钥 (生产必设)
PYCODER_HOME=~/.pycoder        # 数据目录
PYCODER_LOG_LEVEL=INFO         # 日志级别
PYCODER_CORS_ORIGINS=...       # CORS 允许来源

# 新提供商
AGNES_API_KEY=sk-xxx           # AGNES 模型
```

### 2.3 新增 API 端点

| 模块 | 端点前缀 | 说明 |
|------|---------|------|
| 消息网关 | `/api/gateway/*` | 多平台消息管理 |
| Docker 沙箱 | `/api/sandbox/*` | 容器沙箱管理 |
| 幻觉守卫 | `/api/guard/*` | 幻觉检测与统计 |
| DAG 调度 | `/api/dag/*` | 并行任务管理 |
| 任务管理 | `/api/tasks/*` | 任务持久化 |
| 进化报告 | `/api/report/*` | 变更报告生成 |
| 专业 Agent | `/api/agents/*` | Agent 团队管理 |
| 闭环学习 | `/api/learning/*` | 学习反馈循环 |
| 深度记忆 | `/api/deep-memory/*` | 向量记忆系统 |
| 知识管理 | `/api/knowledge/*` | 知识库 CRUD |
| 工作区 | `/api/workspace/*` | 工作区管理 |
| 云同步 | `/api/cloud/*` | 云服务集成 |
| 推荐系统 | `/api/recommendations/*` | 智能推荐 |

### 2.4 升级步骤

```bash
# 1. 停止旧版本服务
systemctl stop pycoder

# 2. 备份数据
cp -r ~/.pycoder ~/.pycoder.backup.v0.4

# 3. 升级代码
cd /path/to/pycoder
git pull origin master
pip install -e . --upgrade

# 4. 配置新环境变量
# 编辑 .env 文件，添加 PYCODER_API_KEY 等

# 5. 启动服务
systemctl start pycoder

# 6. 验证升级
curl http://localhost:8420/api/health
curl http://localhost:8420/api/v2/health
```

---

## 3. v0.5.0 → v1.0.0 升级

### 3.1 重大变更

#### 3.1.1 配置结构变更

v1.0.0 引入了统一的配置系统，旧版环境变量仍然兼容但建议迁移：

```bash
# 旧版 (仍然兼容)
OPENAI_API_KEY=sk-xxx
PYCODER_DEFAULT_MODEL=gpt-4o

# 新版 (推荐)
PYCODER_PROVIDERS_OPENAI_API_KEY=sk-xxx
PYCODER_MODEL_DEFAULT=gpt-4o
```

#### 3.1.2 数据目录结构变更

```
v0.5.0:                          v1.0.0:
~/.pycoder/                      ~/.pycoder/
├── sessions.db                  ├── data/
├── memory/                      │   ├── sessions.db
├── skills/                     │   ├── memory/
├── extensions/                 │   ├── skills/
├── cache/                      │   └── extensions/
└── .api_key                    ├── cache/
                                ├── logs/
                                ├── chroma/          # 新增: 向量数据库
                                ├── learning/        # 新增: 学习数据
                                └── .api_key
```

#### 3.1.3 API 变更

| 变更类型 | 旧端点 | 新端点 | 说明 |
|---------|--------|--------|------|
| 新增 | — | `/api/v2/*` | V2 引擎端点 |
| 新增 | — | `/api/sandbox/*` | 沙箱管理 |
| 新增 | — | `/api/gateway/*` | 消息网关 |
| 新增 | — | `/api/learning/*` | 闭环学习 |
| 新增 | — | `/api/deep-memory/*` | 深度记忆 |
| 新增 | — | `/api/dag/*` | DAG 并行调度 |
| 新增 | — | `/api/agents/*` | Agent 团队 |
| 新增 | — | `/api/report/*` | 进化报告 |
| 新增 | — | `/ws/chat/v2` | V2 聊天 WebSocket |
| 新增 | — | `/ws/gateway` | 网关 WebSocket |
| 新增 | — | `/ws/autonomous` | 自主流水线 WebSocket |
| 新增 | — | `/ws/collab` | 团队协作 WebSocket |
| 废弃 | `/api/skills/v1` | `/api/skills/v2` | Skills API 升级 |

### 3.2 迁移脚本

```bash
#!/bin/bash
# migrate_v0.5_to_v1.0.sh

set -e

echo "=== PyCoder v0.5.0 → v1.0.0 迁移 ==="

# 1. 停止服务
echo "[1/6] 停止服务..."
systemctl stop pycoder 2>/dev/null || true

# 2. 备份
echo "[2/6] 备份数据..."
BACKUP_DIR="$HOME/pycoder_backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp -r ~/.pycoder "$BACKUP_DIR/"
echo "备份已保存到: $BACKUP_DIR"

# 3. 迁移数据目录结构
echo "[3/6] 迁移数据目录..."
OLD_DIR="$HOME/.pycoder"
NEW_DATA_DIR="$OLD_DIR/data"

mkdir -p "$NEW_DATA_DIR"

# 移动文件到新结构
for item in sessions.db memory skills extensions; do
    if [ -e "$OLD_DIR/$item" ]; then
        mv "$OLD_DIR/$item" "$NEW_DATA_DIR/$item" 2>/dev/null || true
    fi
done

# 创建新目录
mkdir -p "$OLD_DIR/chroma"
mkdir -p "$OLD_DIR/learning"
mkdir -p "$OLD_DIR/logs"
mkdir -p "$OLD_DIR/cache"

# 4. 更新配置
echo "[4/6] 更新配置..."
if [ -f "$OLD_DIR/.env" ]; then
    # 备份旧配置
    cp "$OLD_DIR/.env" "$OLD_DIR/.env.v0.5.backup"

    # 添加新配置项
    grep -q "PYCODER_API_KEY" "$OLD_DIR/.env" || \
        echo "PYCODER_API_KEY=$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" >> "$OLD_DIR/.env"

    grep -q "PYCODER_LOG_LEVEL" "$OLD_DIR/.env" || \
        echo "PYCODER_LOG_LEVEL=INFO" >> "$OLD_DIR/.env"
fi

# 5. 升级代码
echo "[5/6] 升级代码..."
cd /path/to/pycoder
git pull origin master
pip install -e . --upgrade

# 6. 验证
echo "[6/6] 验证升级..."
python -m pycoder --version
python -c "from pycoder.server.app import app; print('Import OK')"

echo "=== 迁移完成 ==="
echo "请手动启动服务: systemctl start pycoder"
```

### 3.3 数据库迁移

```bash
# 如果使用了 SQLAlchemy 模型变更
python -m pycoder --migrate-db

# 或手动执行
python -c "
from pycoder.core.dal import migrate_database
migrate_database()
print('数据库迁移完成')
"
```

### 3.4 回滚方案

如果升级后出现问题，可以回滚到 v0.5.0：

```bash
#!/bin/bash
# rollback_to_v0.5.sh

echo "=== 回滚到 v0.5.0 ==="

# 1. 停止服务
systemctl stop pycoder

# 2. 恢复数据
BACKUP_DIR="$HOME/pycoder_backup_20260716_120000"  # 替换为实际备份目录
rm -rf ~/.pycoder
cp -r "$BACKUP_DIR/.pycoder" ~/

# 3. 恢复代码
cd /path/to/pycoder
git checkout v0.5.0
pip install -e . --upgrade

# 4. 启动服务
systemctl start pycoder
```

---

## 4. 配置迁移参考

### 4.1 环境变量映射

| v0.4.x | v0.5.0 | v1.0.0 | 说明 |
|--------|--------|--------|------|
| — | `PYCODER_API_KEY` | `PYCODER_API_KEY` | 新增必设 |
| — | `PYCODER_HOME` | `PYCODER_HOME` | 数据目录 |
| — | `PYCODER_LOG_LEVEL` | `PYCODER_LOG_LEVEL` | 日志级别 |
| — | `PYCODER_CORS_ORIGINS` | `PYCODER_CORS_ORIGINS` | CORS 配置 |
| `OPENAI_API_KEY` | `OPENAI_API_KEY` | `PYCODER_PROVIDERS_OPENAI_API_KEY` | 推荐迁移 |
| `ANTHROPIC_API_KEY` | `ANTHROPIC_API_KEY` | `PYCODER_PROVIDERS_ANTHROPIC_API_KEY` | 推荐迁移 |
| — | `AGNES_API_KEY` | `PYCODER_PROVIDERS_AGNES_API_KEY` | 新增 |
| — | `PYCODER_DEFAULT_MODEL` | `PYCODER_MODEL_DEFAULT` | 推荐迁移 |

### 4.2 API 端点迁移

```python
# 旧版 (v0.4.x) Skills 查询
GET /api/skills/v1?q=python&limit=10

# 新版 (v0.5.0+) Skills 查询
GET /api/skills/v2?search=python&limit=10

# 旧版 (v0.4.x) 会话列表
GET /api/sessions

# 新版 (v0.5.0+) 会话列表 (兼容，新增参数)
GET /api/sessions?limit=50&offset=0

# 新增: 会话搜索
GET /api/sessions/search?q=keyword
```

---

## 5. 依赖变更

### 5.1 v0.5.0 新增依赖

```
# 核心功能
chromadb>=0.5.0          # 向量数据库 (深度记忆)
docker>=7.0.0            # Docker SDK (沙箱执行)
networkx>=3.4            # DAG 任务图管理

# 消息平台 (可选)
python-telegram-bot>=21.0  # Telegram 适配器
discord.py>=2.4.0          # Discord 适配器
slack-sdk>=3.30.0          # Slack 适配器

# 安全
bandit>=1.7.0            # 安全扫描
safety>=3.2.0            # 依赖漏洞检查
```

### 5.2 安装可选依赖

```bash
# 安装全部可选依赖
pip install -e ".[all]"

# 按需安装
pip install -e ".[telegram]"    # Telegram 支持
pip install -e ".[discord]"     # Discord 支持
pip install -e ".[slack]"       # Slack 支持
pip install -e ".[sandbox]"     # Docker 沙箱
pip install -e ".[deep-memory]" # 深度记忆
```

---

## 6. 常见问题

### 6.1 升级后服务无法启动

```bash
# 检查配置
python -c "from pycoder.config.settings import Settings; print(Settings())"

# 检查 API Key
python -c "
from pycoder.providers.auth import check_api_keys
print(check_api_keys())
"

# 检查数据目录权限
ls -la ~/.pycoder/
```

### 6.2 旧版数据无法读取

```bash
# 检查数据目录结构
python -c "
from pathlib import Path
data_dir = Path.home() / '.pycoder'
print('目录结构:')
for item in data_dir.rglob('*'):
    if item.is_file():
        print(f'  {item.relative_to(data_dir)}')
"

# 如果有数据在旧位置，手动迁移
mv ~/.pycoder/sessions.db ~/.pycoder/data/sessions.db
```

### 6.3 ChromaDB 初始化失败

```bash
# 手动初始化 ChromaDB
python -c "
import chromadb
client = chromadb.PersistentClient(path=str(Path.home() / '.pycoder' / 'chroma'))
print('ChromaDB 初始化成功')
print(f'版本: {chromadb.__version__}')
"
```

---

## 7. 版本兼容性矩阵

| 组件 | v0.3.x | v0.4.x | v0.5.0 | v1.0.0 |
|------|--------|--------|--------|--------|
| Python | 3.10+ | 3.11+ | 3.12+ | 3.12+ |
| FastAPI | 0.100+ | 0.110+ | 0.135+ | 0.135+ |
| SQLAlchemy | — | 2.0+ | 2.0+ | 2.0+ |
| ChromaDB | — | — | 0.5+ | 0.5+ |
| Docker SDK | — | — | 7.0+ | 7.0+ |
| LiteLLM | 1.50+ | 1.70+ | 1.82+ | 1.82+ |
| WebSocket 端点 | 3 | 5 | 7 | 7 |
| REST API 端点 | ~150 | ~250 | ~344 | ~350 |
| V2 能力数 | — | — | 119 | 200+ |