FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1

COPY pyproject.toml ./
RUN uv sync --no-dev

# Bind-mounted over by compose for live edits — these COPYs keep a
# self-contained image buildable standalone.
COPY main.py ./
COPY alexa ./alexa

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
