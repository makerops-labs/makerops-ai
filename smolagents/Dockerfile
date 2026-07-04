FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

# Dependency layers first so code edits don't invalidate them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Baked for a self-contained image; compose bind-mounts these over for
# live iteration.
COPY app.py ./
COPY agents/ ./agents/

EXPOSE 7860
CMD ["uv", "run", "--no-sync", "python", "app.py"]
