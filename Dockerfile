# syntax=docker/dockerfile:1

FROM python:3.11-slim

# 引入 uv 二进制（官方推荐做法）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# uv 装进系统 Python；字节码编译 + 复制模式适配容器
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 替换为国内镜像源（Debian 12 使用 bookworm，不是 trixie）
RUN sed -i 's/deb.debian.org/mirrors.163.com/g' /etc/apt/sources.list.d/debian.sources \
    && sed -i 's/security.debian.org/mirrors.163.com/g' /etc/apt/sources.list.d/debian.sources

# ca-certificates：下载云端模型/依赖时需要
# 添加 gcc 和 python3-dev 以支持编译 python-bcrypt
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        gcc \
        python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 依赖清单（利用 Docker 层缓存，改依赖才重装）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 项目代码
COPY app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]