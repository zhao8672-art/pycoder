FROM python:3.12-slim

# 防止 Python 缓冲输出（便于日志收集）
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PYCODER_PORT=8423

WORKDIR /app

# Layer 1: 系统依赖（变更频率最低）
RUN apt-get update && apt-get install -y --no-install-recommends \
    git openssh-client && \
    rm -rf /var/lib/apt/lists/*

# Layer 2: Python 依赖（利用 Docker 层缓存）
COPY pyproject.toml README.md requirements.txt* ./
RUN pip install --no-cache-dir -e ".[dev]" || \
    pip install --no-cache-dir -e .

# Layer 3: 源代码（变更频率最高）
COPY pycoder/ ./pycoder/

# 安全: 创建非 root 用户运行应用
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

EXPOSE 8423

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8423/api/health')"

CMD ["python", "-m", "pycoder", "--server", "--server-port", "8423"]
