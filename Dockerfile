FROM python:3.13-slim

# Pin uv version for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /bin/uv

WORKDIR /app

# Copy dependency files first for layer cache optimization
COPY pyproject.toml uv.lock ./

# Install runtime deps into system Python (UV_SYSTEM_PYTHON avoids venv startup issues)
ENV UV_SYSTEM_PYTHON=1
RUN uv sync --frozen --no-dev --no-cache

# Copy application code
COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
