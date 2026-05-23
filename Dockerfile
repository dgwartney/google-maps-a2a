FROM python:3.13-slim

# Pin uv version for reproducible builds
COPY --from=ghcr.io/astral-sh/uv:0.4.30 /uv /bin/uv

WORKDIR /app

# Copy dependency files first for layer cache optimization
COPY pyproject.toml uv.lock ./

# Create venv and install runtime deps using uv
# python:3.13-slim matches the lockfile Python version — venv is stable at runtime
RUN uv sync --frozen --no-dev --no-cache

# Add venv to PATH so `uvicorn` in CMD resolves without needing `uv run`
ENV PATH="/app/.venv/bin:$PATH"

# Copy application code
COPY . .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
