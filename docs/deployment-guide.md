# PyCoder 部署指南

> 版本: 1.0 | 更新时间: 2026-07-16 | 目标读者: 运维人员与系统管理员

---

## 1. 部署概览

PyCoder 支持多种部署方式，从简单的本地开发到生产级 Docker 部署。

### 1.1 部署方式对比

| 方式 | 适用场景 | 复杂度 | 隔离性 | 资源需求 |
|------|---------|--------|--------|---------|
| pip 安装 | 本地开发/个人使用 | 低 | 低 | 最小 |
| Docker 单容器 | 小型团队 | 中 | 中 | 2GB RAM |
| Docker Compose | 生产环境 | 中 | 高 | 4GB RAM |
| Kubernetes | 企业级部署 | 高 | 最高 | 8GB+ RAM |

### 1.2 系统要求

| 组件 | 最低要求 | 推荐配置 |
|------|---------|---------|
| 操作系统 | Windows 10+ / Ubuntu 20.04+ / macOS 12+ | Ubuntu 22.04+ |
| Python | 3.12+ | 3.14 |
| 内存 | 2GB | 8GB+ |
| 磁盘 | 1GB (不含模型) | 10GB+ SSD |
| 网络 | 出站 HTTPS | 低延迟宽带 |
| Docker | 24.0+ (可选) | 26.0+ |

---

## 2. pip 安装部署

### 2.1 安装步骤

```bash
# 1. 创建虚拟环境
python3.14 -m venv /opt/pycoder/venv
source /opt/pycoder/venv/bin/activate

# 2. 安装 PyCoder
pip install -e /path/to/pycoder

# 3. 验证安装
python -m pycoder --version
```

### 2.2 配置环境变量

```bash
# /opt/pycoder/.env
PYCODER_API_KEY=<your-secure-api-key>
PYCODER_HOME=/opt/pycoder/data
PYCODER_LOG_LEVEL=INFO
PYCODER_HOST=0.0.0.0
PYCODER_PORT=8420

# LLM 提供商
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
AGNES_API_KEY=sk-xxx

# 默认模型
PYCODER_DEFAULT_MODEL=gpt-4o
```

### 2.3 启动服务

```bash
# 前台运行
python -m pycoder

# 后台运行 (Linux)
nohup python -m pycoder > /var/log/pycoder.log 2>&1 &

# 使用 systemd (推荐)
sudo cp pycoder.service /etc/systemd/system/
sudo systemctl enable pycoder
sudo systemctl start pycoder
```

### 2.4 systemd 服务文件

```ini
# /etc/systemd/system/pycoder.service
[Unit]
Description=PyCoder AI Coding Agent
After=network.target

[Service]
Type=simple
User=pycoder
Group=pycoder
WorkingDirectory=/opt/pycoder
EnvironmentFile=/opt/pycoder/.env
ExecStart=/opt/pycoder/venv/bin/python -m pycoder
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

---

## 3. Docker 部署

### 3.1 构建镜像

```bash
# 构建 PyCoder 服务镜像
docker build -t pycoder:latest .

# 构建沙箱镜像
docker build -t pycoder-sandbox:latest -f Dockerfile.sandbox .
```

### 3.2 单容器运行

```bash
docker run -d \
  --name pycoder \
  -p 8420:8420 \
  -v /opt/pycoder/data:/root/.pycoder \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -e PYCODER_API_KEY=your-secure-key \
  -e OPENAI_API_KEY=sk-xxx \
  -e ANTHROPIC_API_KEY=sk-ant-xxx \
  pycoder:latest
```

### 3.3 Docker Compose (推荐)

```yaml
# docker-compose.yml
version: "3.8"

services:
  pycoder:
    image: pycoder:latest
    container_name: pycoder
    restart: unless-stopped
    ports:
      - "8420:8420"
    volumes:
      - pycoder_data:/root/.pycoder
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - PYCODER_API_KEY=${PYCODER_API_KEY}
      - PYCODER_HOME=/root/.pycoder
      - PYCODER_LOG_LEVEL=INFO
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - AGNES_API_KEY=${AGNES_API_KEY}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8420/api/health"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - pycoder_net

  # 可选: ChromaDB 向量数据库 (深度记忆)
  chromadb:
    image: chromadb/chroma:latest
    container_name: pycoder-chromadb
    restart: unless-stopped
    volumes:
      - chromadb_data:/chroma/chroma
    environment:
      - IS_PERSISTENT=TRUE
      - ANONYMIZED_TELEMETRY=FALSE
    networks:
      - pycoder_net

  # 可选: Nginx 反向代理
  nginx:
    image: nginx:alpine
    container_name: pycoder-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/nginx/ssl
    depends_on:
      - pycoder
    networks:
      - pycoder_net

volumes:
  pycoder_data:
  chromadb_data:

networks:
  pycoder_net:
    driver: bridge
```

### 3.4 Nginx 反向代理配置

```nginx
# nginx.conf
events {
    worker_connections 1024;
}

http {
    upstream pycoder_backend {
        server pycoder:8420;
    }

    # HTTP → HTTPS 重定向
    server {
        listen 80;
        server_name pycoder.example.com;
        return 301 https://$host$request_uri;
    }

    # HTTPS 服务
    server {
        listen 443 ssl http2;
        server_name pycoder.example.com;

        ssl_certificate /etc/nginx/ssl/fullchain.pem;
        ssl_certificate_key /etc/nginx/ssl/privkey.pem;
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        # API 代理
        location /api/ {
            proxy_pass http://pycoder_backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # WebSocket 代理
        location /ws/ {
            proxy_pass http://pycoder_backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
        }

        # API 文档
        location /docs {
            proxy_pass http://pycoder_backend;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
        }
    }
}
```

### 3.5 启动 Docker Compose

```bash
# 创建 .env 文件
cat > .env << EOF
PYCODER_API_KEY=$(openssl rand -hex 32)
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-ant-xxx
AGNES_API_KEY=sk-xxx
EOF

# 启动所有服务
docker compose up -d

# 查看日志
docker compose logs -f pycoder

# 检查健康状态
curl http://localhost:8420/api/health
```

---

## 4. 安全加固

### 4.1 生产环境必做项

1. **强制 API 认证**
   ```bash
   # 生成强密钥
   export PYCODER_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
   # 不要使用 PYCODER_API_KEY=disabled
   ```

2. **限制 CORS 来源**
   ```bash
   # 仅允许生产域名
   PYCODER_CORS_ORIGINS=https://pycoder.example.com
   ```

3. **使用 HTTPS**
   ```bash
   # 使用 Let's Encrypt 获取免费证书
   certbot certonly --standalone -d pycoder.example.com
   ```

4. **防火墙规则**
   ```bash
   # 仅开放必要端口
   ufw allow 80/tcp
   ufw allow 443/tcp
   ufw deny 8420/tcp  # 不直接暴露后端端口
   ```

5. **文件权限**
   ```bash
   chmod 600 /opt/pycoder/.env
   chmod 700 /opt/pycoder/data
   chown -R pycoder:pycoder /opt/pycoder
   ```

### 4.2 安全扫描

```bash
# Bandit 安全扫描
pip install bandit
bandit -r pycoder/ -f html -o bandit_report.html

# 依赖漏洞检查
pip install safety
safety check -r requirements.txt
```

### 4.3 沙箱配置

```python
# 沙箱安全配置
SANDBOX_CONFIG = {
    "default_timeout": 30,        # 默认超时 (秒)
    "max_timeout": 300,           # 最大超时 (秒)
    "memory_limit_mb": 512,       # 内存限制
    "cpu_limit": 1.0,             # CPU 限制
    "max_output_length": 10000,   # 输出长度限制
    "max_code_length": 100000,    # 代码长度限制
    "allow_network": False,       # 默认禁止网络
    "allow_multithreading": False, # 默认禁止多线程
}
```

---

## 5. 性能优化

### 5.1 系统调优

```bash
# 增加文件描述符限制
ulimit -n 65535

# 调整内核参数 (Linux)
cat >> /etc/sysctl.conf << EOF
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
fs.file-max = 2097152
EOF
sysctl -p
```

### 5.2 Uvicorn 配置

```bash
# 多 worker 模式
python -m uvicorn pycoder.server.app:app \
  --host 0.0.0.0 \
  --port 8420 \
  --workers 4 \
  --loop uvloop \
  --http httptools \
  --log-level warning
```

### 5.3 缓存配置

```python
# 启用磁盘缓存
PYCODER_CACHE_ENABLED=true
PYCODER_CACHE_DIR=/opt/pycoder/cache
PYCODER_CACHE_MAX_SIZE=10GB
```

### 5.4 数据库优化

```bash
# SQLite 性能优化
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;  # 64MB
PRAGMA busy_timeout=5000;
```

---

## 6. 监控与运维

### 6.1 健康检查

```bash
# API 健康检查
curl http://localhost:8420/api/health
# 预期响应: {"status": "ok", "version": "0.5.0", ...}

# V2 引擎状态
curl -H "X-API-Key: your-key" http://localhost:8420/api/v2/health
```

### 6.2 日志管理

```bash
# 查看服务日志
journalctl -u pycoder -f

# Docker 日志
docker compose logs -f pycoder

# 日志轮转配置
# /etc/logrotate.d/pycoder
/var/log/pycoder/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    postrotate
        systemctl reload pycoder
    endscript
}
```

### 6.3 备份策略

```bash
# 备份脚本
#!/bin/bash
BACKUP_DIR="/backup/pycoder"
DATE=$(date +%Y%m%d_%H%M%S)

# 备份数据目录
tar -czf "$BACKUP_DIR/pycoder_data_$DATE.tar.gz" /opt/pycoder/data/

# 备份配置
cp /opt/pycoder/.env "$BACKUP_DIR/.env_$DATE"

# 保留最近 30 天
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete
```

### 6.4 自动恢复

```bash
# systemd 自动重启已配置 Restart=always
# 监控脚本
#!/bin/bash
while true; do
    if ! curl -s http://localhost:8420/api/health > /dev/null; then
        echo "$(date): Service down, restarting..."
        systemctl restart pycoder
    fi
    sleep 60
done
```

---

## 7. 升级流程

### 7.1 pip 安装升级

```bash
# 1. 停止服务
systemctl stop pycoder

# 2. 备份
tar -czf /backup/pycoder_pre_upgrade.tar.gz /opt/pycoder/

# 3. 升级
source /opt/pycoder/venv/bin/activate
pip install -e /path/to/new/pycoder --upgrade

# 4. 数据库迁移 (如有)
python -m pycoder --migrate

# 5. 启动服务
systemctl start pycoder
```

### 7.2 Docker 升级

```bash
# 1. 拉取新镜像
docker compose pull

# 2. 重建容器
docker compose up -d --build

# 3. 清理旧镜像
docker image prune -f
```

---

## 8. 故障排除

### 8.1 服务无法启动

```bash
# 检查端口占用
lsof -i :8420
netstat -tulpn | grep 8420

# 检查 Python 版本
python --version

# 检查依赖
pip check

# 查看详细错误
python -m pycoder --log-level DEBUG
```

### 8.2 WebSocket 连接失败

```bash
# 检查 Nginx WebSocket 配置
# 确保包含以下配置:
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
proxy_read_timeout 86400s;
```

### 8.3 内存不足

```bash
# 检查内存使用
docker stats pycoder

# 限制 Docker 容器内存
docker update --memory 4g --memory-swap 4g pycoder

# 减少 worker 数量
# 设置环境变量
PYCODER_WORKERS=2
```

### 8.4 Docker 沙箱不可用

```bash
# 检查 Docker 是否运行
docker info

# 挂载 Docker socket
-v /var/run/docker.sock:/var/run/docker.sock

# 构建沙箱镜像
docker build -t pycoder-sandbox:latest -f Dockerfile.sandbox .
```