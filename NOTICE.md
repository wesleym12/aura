# Avisos e componentes de terceiros

A **A.U.R.A.** é software livre, licenciado sob a **GNU Affero General Public License v3.0 ou posterior**
(arquivo [`LICENSE`](LICENSE)). Copyright © 2026 Wesley Martins e contribuidores.

Ela é distribuída **em código-fonte**: cada instalação baixa e monta os componentes abaixo na própria máquina
(`docker compose build`). Nenhum deles vai embutido neste repositório.

## Bibliotecas e programas

| Componente | Uso | Licença |
|---|---|---|
| FastAPI, Uvicorn, httpx, websockets, psutil | servidor | MIT / BSD-3-Clause |
| pypdf, python-docx, openpyxl, python-pptx, Pillow | leitura de documentos e imagens | BSD-3-Clause / MIT / MIT-CMU |
| google-genai | Gemini / Gemini Live | Apache-2.0 |
| mcp (Model Context Protocol) | conectores | MIT |
| faster-whisper (e modelos Whisper) | transcrição de voz | MIT |
| kokoro-onnx (e modelo Kokoro-82M) | fala | MIT / Apache-2.0 |
| **piper-tts** | fala em outras línguas | **GPL-3.0-or-later** |
| webrtcvad-wheels, onnxruntime, numpy | voz | MIT / BSD |
| Ollama | modelo local | MIT |
| Qwen3, Qwen3-VL, paraphrase-multilingual | modelos locais (baixados pelo Ollama) | Apache-2.0 |
| Home Assistant (opcional) | casa inteligente | Apache-2.0 |
| OpenAI Codex CLI | agente de programação (opcional) | Apache-2.0 |
| **Claude Code** (Anthropic) | agente de programação (opcional) | **proprietária**: instalado na montagem, nos termos da Anthropic; não redistribua imagens Docker que o contenham |
| Simple Icons | logos dos conectores | CC0-1.0 (as marcas pertencem aos seus donos; uso só para identificar o serviço, sem indicar parceria ou endosso) |
| Fontes Orbitron, Exo 2, JetBrains Mono (Google Fonts) | interface | SIL Open Font License 1.1 |

As vozes do Piper são baixadas sob demanda e cada uma tem a licença indicada no seu cartão de modelo
(rhasspy/piper-voices).

## Serviços de terceiros

A A.U.R.A. só fala com um serviço quando **você** o configura, com a **sua** conta ou chave, e fica sujeita aos
termos dele: Google (Gemini, Agenda, Gmail, Drive, Docs, Sheets, YouTube Data API), Anthropic (Claude), OpenAI (Codex),
Spotify, Telegram e os serviços dos conectores MCP.

- **Assinaturas de consumidor** (Claude Pro/Max, ChatGPT Plus) são de uso pessoal: a A.U.R.A. só usa os programas
  oficiais com o login que você fez neles. Para outros usos, prefira chaves de API.
- **Gemini no plano gratuito:** o Google pode usar o conteúdo para melhorar os produtos dele. Veja os termos da
  Gemini API.
- **YouTube:** a busca usa a API oficial (YouTube Data API v3, com a sua chave). Sem chave, ela só abre a página de
  resultados no seu navegador.

Veja também [`PRIVACIDADE.md`](PRIVACIDADE.md).
