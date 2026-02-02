# Backend Dockerfile for Railway deployment
# Uses Python 3.12 with uv for fast dependency installation

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv using pip (more reliable in Docker)
RUN pip install --no-cache-dir uv

# Copy dependency files and README (required by pyproject.toml)
COPY pyproject.toml uv.lock README.md ./

# Install Python dependencies using uv
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Expose port (Railway will set PORT env variable)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set PATH to include the virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Run database migrations and start server
# Use timeout for migrations and || true to continue even if migrations fail
CMD echo "Starting application..." && \
    echo "Running database migrations (timeout 60s)..." && \
    timeout 60 alembic upgrade head || echo "Migrations skipped or timed out" && \
    echo "Starting uvicorn server on port ${PORT:-8000}..." && \
    exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info
