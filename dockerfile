# syntax=docker/dockerfile:1

# 准备依赖，arm64上也得build amd64
FROM python:3.11-slim-bookworm AS builder

# 从 uv 官方镜像中只取出 uv 可执行文件
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./

# 下载缓存留在构建缓存中，不写进镜像层
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# 第二阶段：最终运行镜像
FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder /app/.venv /app/.venv
COPY src/ ./src/

USER 10001:10001

CMD ["python", "src/main.py"]