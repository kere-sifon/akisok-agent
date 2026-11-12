# syntax=docker/dockerfile:1.7
# Build for the cluster (x86_64) from an Apple Silicon Mac:
#   docker buildx build --platform linux/amd64 \
#     -t nexus-lan.keresifon.com/docker-hosted/akisok-agent:<tag> --push .

FROM python:3.11-slim-bookworm
WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends git openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1001 --gid users akisok

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY config ./config
COPY scripts/k8s-admin-entrypoint.sh /k8s-admin-entrypoint.sh
RUN chmod 755 /k8s-admin-entrypoint.sh \
 && chown -R 1001:users /app

USER 1001
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ADMIN_UI_HOST=0.0.0.0 \
    ADMIN_UI_PORT=8001 \
    CONTENT_REPO_PATH=/content/akisok-site \
    HOME=/home/akisok

EXPOSE 8001
CMD ["uvicorn", "src.admin.main:app", "--host", "0.0.0.0", "--port", "8001"]
