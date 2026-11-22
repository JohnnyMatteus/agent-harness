FROM python:3.12.8-slim
RUN groupadd -g 10001 forja && useradd -u 10001 -g 10001 -M -s /usr/sbin/nologin forja \
    && apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
USER 10001:10001
WORKDIR /workspace
