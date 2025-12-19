# --- Build stage ---
FROM python:3.11-slim-bullseye AS py-build

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    POETRY_VERSION=1.8.3

# Install system dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg curl build-essential git && \
    rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install "poetry==$POETRY_VERSION"

# Set workdir
WORKDIR /app

# Copy dependency manifests and local path packages first for better caching
COPY byoeb/pyproject.toml byoeb/poetry.lock* ./byoeb/
COPY byoeb-integrations/pyproject.toml byoeb-integrations/poetry.lock* ./byoeb-integrations/
COPY byoeb-core/pyproject.toml byoeb-core/poetry.lock* ./byoeb-core/

# Copy source code for path dependencies
COPY byoeb ./byoeb
COPY byoeb-integrations ./byoeb-integrations
COPY byoeb-core ./byoeb-core/

# Install dependencies into venv
RUN python -m venv /app/.venv \
    && . /app/.venv/bin/activate \
    && poetry install --only main --directory /app/byoeb

# --- Runtime stage ---
FROM python:3.11-slim-bullseye

ENV PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Runtime system deps only
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy venv and application code
COPY --from=py-build /app/.venv /app/.venv
COPY . /app

EXPOSE 8000

CMD ["python", "-m", "byoeb.chat_app.run", "--host", "0.0.0.0", "--port", "8000"]