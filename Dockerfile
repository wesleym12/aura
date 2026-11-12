# Aura: API + chat web + CLIs do Claude Code e do Codex
FROM node:22-bookworm-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates git ripgrep tzdata \
 && rm -rf /var/lib/apt/lists/*

# CLIs que a Aura usa para delegar tarefas (o login fica em volumes, nao na imagem)
RUN npm install -g @anthropic-ai/claude-code @openai/codex && npm cache clean --force

WORKDIR /app
COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    CLAUDE_CONFIG_DIR=/home/node/.claude \
    CODEX_HOME=/home/node/.codex \
    AURA_WORKSPACE=/workspace \
    AURA_DB=/data/aura.db

COPY aura ./aura

# roda como usuario sem privilegios (node, uid 1000)
RUN mkdir -p /data /workspace /memoria /home/node/.claude /home/node/.codex /home/node/.cache /home/node/.npm \
 && chown -R node:node /data /workspace /memoria /home/node
USER node

EXPOSE 8765
CMD ["uvicorn", "aura.server:app", "--host", "0.0.0.0", "--port", "8765"]
