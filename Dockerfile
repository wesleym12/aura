# Aura: API + chat web (o Node fica para os servidores MCP que rodam com npx)
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates git ripgrep tzdata openssl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    AURA_WORKSPACE=/workspace \
    AURA_DB=/data/aura.db

COPY aura ./aura

# roda como usuario sem privilegios (node, uid 1000)
RUN mkdir -p /data /workspace /memoria /home/node/.cache /home/node/.npm \
 && chown -R node:node /data /workspace /memoria /home/node
USER node

EXPOSE 8765
# HTTP so nesta maquina (Windows) ou HTTPS na rede (AURA_TLS=1, servidor Linux): ver aura/run.py
CMD ["python", "-m", "aura.run"]
