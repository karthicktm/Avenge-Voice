FROM python:3.12-slim

WORKDIR /app

# Install uv
RUN pip install uv --no-cache-dir

# Copy dependency files first (layer caching)
COPY pyproject.toml uv.lock README.md ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy full backend source (agent_runtime + app packages)
COPY . .

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "agent_runtime.main:app", "--host", "0.0.0.0", "--port", "8001"]
