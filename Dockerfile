FROM python:3.10-slim

# Pin uv version for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /bin/uv

WORKDIR /app

# Copy dependency files first for layer cache optimization
COPY pyproject.toml uv.lock ./

# Install runtime dependencies only (no dev group)
RUN uv sync --frozen --no-dev --no-cache

# Copy application code
COPY . .

EXPOSE 8000

CMD [".venv/bin/uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
