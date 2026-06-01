# wizard/Dockerfile
# Build context: repo root (needs wizard/ AND sample_kb/)
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (better layer cache)
COPY wizard/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir pyyaml

# Copy wizard source and bundled KB documents
COPY wizard/ wizard/
COPY sample_kb/ sample_kb/

# Tell wizard code it's running in a container
ENV RUNNING_IN_DOCKER=1
ENV PYTHONPATH=/app

EXPOSE 5001

CMD ["python", "-m", "wizard"]
