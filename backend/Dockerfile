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

# Install uv (fast Python package installer) and add to PATH in same layer
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    echo 'export PATH="/root/.cargo/bin:$PATH"' >> ~/.bashrc
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python dependencies using uv (use full path to ensure it's found)
RUN /root/.cargo/bin/uv sync --frozen --no-dev

# Copy application code
COPY . .

# Expose port (Railway will set PORT env variable)
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run database migrations and start server
CMD /root/.cargo/bin/uv run alembic upgrade head && \
    /root/.cargo/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
