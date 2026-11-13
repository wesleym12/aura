# Privacidade

A A.U.R.A. roda **no seu computador ou servidor**. O projeto e quem o mantém **não recebem nenhum dado seu**: não há
conta, servidor central, telemetria nem estatística de uso.

## O que fica só na sua máquina
- Conversas, memória, instruções, skills, configurações, backups e o diário de ações (banco SQLite no volume
  `aura-data` e na pasta `backups/`).
- Chaves de API, tokens e senhas (no banco local e no `.env`). Não compartilhe a pasta `backups/` nem o `.env`.
- No modo **modelo local**: o que você fala e escreve é processado no Ollama, no Whisper e no Kokoro, sem sair da
  máquina.

## O que sai, e só se você ligar
| Recurso | Para onde vai | O quê |
|---|---|---|
| Modo **só Gemini** / Gemini Live / modelo da nuvem no seletor | Google, ou o provedor escolhido (OpenAI, Groq…) | suas mensagens, o áudio depois da palavra de ativação, memórias relevantes ao pedido e o texto das memórias para a busca por significado |
| Contas Claude / Codex | Anthropic / OpenAI | o pedido delegado e arquivos da pasta de trabalho que o agente ler |
| Google (Agenda, Gmail, Drive…), Spotify, Home Assistant, conectores MCP, Telegram | o próprio serviço | só o necessário para cada ação que você pedir |
| Imagens (Nano Banana), documentos sem visão local | Google | a imagem ou o documento enviado |

Cada serviço trata os dados conforme a política de privacidade dele. A palavra de ativação ("Aura") é sempre
reconhecida **localmente**: nada é enviado antes dela.

## Quem instala para outras pessoas
Se você oferecer a A.U.R.A. a outras pessoas (por exemplo, numa casa ou empresa), você passa a ser o responsável
pelos dados delas e deve seguir a LGPD (ou a lei de proteção de dados do seu país).
