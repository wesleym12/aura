# Voz da A.U.R.A.: palavra de ativacao e transcricao (faster-whisper) e fala (Kokoro/Piper). Tudo local, na CPU.
FROM python:3.11-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 curl ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Modelos baixados na construcao da imagem (depois funciona sem internet)
ENV HF_HOME=/models/hf
ARG WHISPER_MODEL=small
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8')"
RUN mkdir -p /models \
 && curl -fsSL -o /models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx \
 && curl -fsSL -o /models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

COPY app.py .
RUN useradd -m -u 1000 aura && mkdir -p /models/piper && chown -R aura /models
USER aura

EXPOSE 8767
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8767"]
