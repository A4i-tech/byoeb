FROM python:3.11-slim-bookworm AS builder

ENV POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends build-essential git \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/local/bin/python -m venv /opt/venv && /usr/local/bin/pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app
COPY byoeb/pyproject.toml byoeb/poetry.lock ./byoeb/
COPY byoeb-integrations ./byoeb-integrations
COPY byoeb-core ./byoeb-core

WORKDIR /app/byoeb
RUN poetry install --only main --no-root --no-interaction --no-ansi \
    && rm -rf /root/.cache

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=appuser:appgroup . .
WORKDIR /app/byoeb

USER appuser

EXPOSE 8000

CMD ["python3", "-m", "byoeb.chat_app.run", "--host", "0.0.0.0", "--port", "8000"]
