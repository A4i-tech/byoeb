FROM python:3.11-slim-bookworm AS builder

ENV POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_CREATE=false \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN /usr/local/bin/python -m venv /opt/venv && /usr/local/bin/pip install --no-cache-dir "poetry==$POETRY_VERSION"

WORKDIR /app
COPY byoeb/pyproject.toml byoeb/poetry.lock ./byoeb/
COPY byoeb-integrations/pyproject.toml byoeb-integrations/poetry.lock byoeb-integrations/README.md ./byoeb-integrations/
COPY byoeb-core/pyproject.toml byoeb-core/poetry.lock byoeb-core/README.md ./byoeb-core/
# develop = true path deps only need an importable package dir at install time
RUN mkdir -p byoeb-integrations/byoeb_integrations byoeb-core/byoeb_core \
    && touch byoeb-integrations/byoeb_integrations/__init__.py byoeb-core/byoeb_core/__init__.py

WORKDIR /app/byoeb
RUN poetry install --only main --no-root --no-interaction --no-ansi

FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system appgroup \
    && useradd --system --gid appgroup --no-create-home appuser \
    && mkdir -p /app && chown appuser:appgroup /app

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=appuser:appgroup . .
WORKDIR /app/byoeb

USER appuser

EXPOSE 8000

CMD ["python3", "-m", "byoeb.chat_app.run", "--host", "0.0.0.0", "--port", "8000"]
