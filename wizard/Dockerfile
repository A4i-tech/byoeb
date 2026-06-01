# wizard/Dockerfile
# Build context: repo root (needs wizard/ AND sample_kb/)
FROM python:3.11-slim

WORKDIR /app

# Install Docker CLI + Compose plugin (needed to launch app containers via socket)
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates gnupg \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
       | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
       https://download.docker.com/linux/debian bookworm stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
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
