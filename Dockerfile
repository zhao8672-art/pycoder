# PyCoder Dockerfile
# 多阶段构建: builder (编译) + runtime (轻量)
# 用法:
#   docker build -t pycoder:latest .
#   docker run -d -p 8423:8423 --name pycoder pycoder:latest
#   docker compose up -d

# ===== Stage 1: Builder =====
FROM python:3.12-slim AS builder

# 防止 .pyc 文件, 强制 stdout/stderr 非缓冲
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 安装构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        libffi-dev \
        libssl-dev \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        libtesseract-dev \
        poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# 先复制依赖清单, 利用 Docker 缓存
COPY requirements.txt requirements-all.txt pyproject.toml ./
COPY requirements/ ./requirements/

# 升级 pip + 安装 pip-tools (用于 lock 同步)
RUN pip install --upgrade pip pip-tools

# 从 requirements.in 重新生成 lock 文件 (审计追踪)
RUN pip-compile requirements/requirements.in -o requirements.lock.txt 2>/dev/null || true

# 安装项目依赖 (含 multimodal)
RUN pip install --no-cache-dir -r requirements-all.txt

# 复制源码
COPY pycoder/ ./pycoder/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

# 可编辑安装
RUN pip install --no-cache-dir -e .

# ===== Stage 2: Runtime =====
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYCODER_SANDBOX=docker \
    PYCODER_PORT=8423 \
    PYCODER_HOST=0.0.0.0

# 仅安装运行时系统依赖 (tesseract + poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-chi-sim \
        tesseract-ocr-eng \
        poppler-utils \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 阶段复制已安装的包
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# 创建非 root 用户
RUN groupadd -r pycoder && useradd -r -g pycoder pycoder \
    && mkdir -p /app /workspace /home/pycoder/.pycoder \
    && chown -R pycoder:pycoder /app /workspace /home/pycoder

WORKDIR /app
USER pycoder

# 复制应用代码 (只读)
COPY --chown=pycoder:pycoder --chmod=555 pycoder/ ./pycoder/
COPY --chown=pycoder:pycoder --chmod=555 scripts/ ./scripts/
COPY --chown=pycoder:pycoder --chmod=555 pyproject.toml requirements*.txt ./

# 暴露端口
EXPOSE 8423

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -fsS -H "X-API-Key: ${PYCODER_API_KEY}" http://localhost:8423/api/health/live || exit 1

# 默认启动: 内存数据库 + 监听所有接口
CMD ["python", "-m", "uvicorn", "pycoder.server.app:app", \
     "--host", "0.0.0.0", "--port", "8423", "--workers", "1"]
