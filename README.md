# A.U.R.A.

**Autonomous Utility and Response Assistant** (fala-se "Aura"). Assistente pessoal que roda no seu PC, tudo em Docker.
Um modelo do **Ollama** (na GPU) cuida da rotina e chama as habilidades; o **Gemini** é opcional (voz ao vivo e nuvem);
tarefas pesadas podem ir para o **Claude Code** e o **Codex**, usando as suas assinaturas. Tudo fica numa memória
local pesquisável.

## Instalação

O instalador **analisa o computador** (processador, memória, disco, placa NVIDIA) e recomenda um modo:
- **Modelo local:** tudo no seu computador, privado e funciona sem internet. Precisa de placa de vídeo para ficar rápido.
- **Só Gemini:** o Google responde, e a busca por significado na memória também é feita por ele. O Ollama nem é instalado, então a instalação fica bem mais leve (vários GB a menos). É rápido em qualquer máquina, mas precisa de internet e de uma [chave grátis do Gemini](https://aistudio.google.com/apikey). Se o Gemini Flash estiver lotado, ela responde pelo Flash-Lite. Sem a chave, a memória continua funcionando pela busca por palavras.

Você escolhe o modo, cola a chave do Gemini (opcional no modo local) e decide se o Home Assistant sobe junto.

### Windows

Precisa do **Docker Desktop** (WSL2).

```powershell
.\iniciar.ps1
```

- Na primeira vez, chama o `instalar.ps1`: faz a análise e as perguntas, e grava o `.env`.
- Depois sobe o Docker Desktop, os containers e o agente do Windows, e abre http://127.0.0.1:8765. Só esta máquina acessa, sem senha.
- Para reconfigurar: `.\instalar.ps1`. Para só ver a análise: `.\instalar.ps1 -Analisar`.
- **Iniciar com o Windows:** Configurações → Geral.

### Linux e umbrelOS (via SSH)

Precisa de Docker com o plugin compose. O umbrelOS já tem.

```bash
git clone https://github.com/wesleym12/aura.git && cd aura
bash instalar.sh
```

- O instalador grava o `.env`, gera uma **senha de acesso** e liga o **HTTPS**, e depois sobe tudo. A primeira vez leva de 10 a 30 min.
- No fim, ele mostra o endereço (ex.: `https://umbrel.local:8765`) e a senha.
- **Acesso pela rede, com senha:** de qualquer aparelho da casa (celular, notebook). A senha fica no `.env` (`AURA_PASSWORD`).
- **HTTPS próprio:** o navegador avisa do certificado uma vez (Avançado → Continuar). Sem HTTPS o navegador bloqueia o microfone fora do `localhost`.
- **No umbrelOS:**
  - O Home Assistant do próprio Umbrel é detectado e não é instalado de novo. Conecte o dele em Plugins → Casa inteligente → "Usar outro Home Assistant", com o endereço `http://umbrel.local:8123` e um token de longa duração.
  - A pasta padrão de arquivos é a do app Arquivos (`~/umbrel/home`).
- **Sobe sozinha** quando o servidor liga (o Docker reinicia os containers). Atualizar: `./atualizar.sh`. Reconfigurar: `bash instalar.sh`.
- **O que é só do Windows:** controle do computador (abrir programas, YouTube na mesma aba, clicar), Ctrl+Espaço global e "Iniciar com o Windows". No Linux, as métricas do topo vêm do próprio servidor.
- **Logins do Google e de conectores MCP:** esses serviços só aceitam retorno em `localhost`. Faça esses logins uma vez por um túnel SSH, que encaminha uma porta do seu computador para o servidor:
  ```bash
  ssh -L 8765:localhost:8765 umbrel@umbrel.local
  ```
  Com o túnel aberto, acesse http://localhost:8765. O Spotify, o Home Assistant e as contas do Claude e do Codex funcionam direto pelo endereço da rede.
- **Spotify no servidor:** cadastre como Redirect URI o endereço mostrado no card (ex.: `https://umbrel.local:8765/api/spotify/callback`).

| Serviço | Papel |
|---|---|
| `aura` | API, chat web e CLIs `claude`/`codex`. Porta 8765: só nesta máquina (Windows) ou pela rede, com senha e HTTPS (Linux) |
| `ollama` | Modelo local, na GPU com `docker-compose.gpu.yml` (não fica exposto fora do Docker). Só no modo local (`COMPOSE_PROFILES=local`) |
| `ollama-pull` | Baixa os modelos na primeira subida e sai (modo local) |
| `voice` | Palavra de ativação, transcrição (Whisper) e fala (Kokoro/Piper). CPU, offline; a tela fala com ele pela A.U.R.A. (`/voice`) |
| `homeassistant` | Casa inteligente, porta 8123 (opcional: `COMPOSE_PROFILES=casa`) |
| agente do Windows | `host-agent\agent.ps1` (fora do Docker): métricas, Ctrl+Espaço, controle do PC. Só em `127.0.0.1:8766` |

## Voz

- **Microfone** (botão ao lado do campo de texto): clique, fale; envia sozinho quando você para de falar.
- **Sempre** (escuta contínua): fica esperando **"Aura"** ("Aura, que horas são?"). Palavras parecidas ("aula", "Laura", "ouro") não a acordam. O áudio só é processado no container `voice`.
- **Ctrl+Espaço** (segurar para falar): funciona com qualquer janela em foco. O agente do Windows só observa essas duas teclas.
- **Modo conversa** (Configurações → Microfone e som, **desligado por padrão**):
  - Desligado: a cada pedido ela responde e volta a esperar "Aura", então não pega a conversa de quem está por perto.
  - Ligado: continua ouvindo por 2 minutos sem precisar do nome.
- `Esc` ou o botão do microfone interrompem a fala. Tarefas demoradas recebem na hora um aviso curto ("Já vou colocar para tocar").
- **Português fixo** (padrão): silêncio e ruído não viram texto, e as frases-fantasma do Whisper ("Thanks for watching"...) são descartadas.
- **A voz te segue** (desligada por padrão; Configurações → Modelos): ela responde na língua em que você falou, com uma voz nativa dela.
- **Vozes** (Voz e jeito): locais `pf_dora` (padrão), `pm_alex` e `pm_santa`; com o Gemini Live, as vozes do Gemini (padrão `Kore`).

## Motor e modelos (Configurações → Modelos)

- **Motor:** próprio (Whisper ouve, o modelo pensa, Kokoro/Piper falam) ou **Gemini Live** (conversa por voz em tempo real; cole a chave do Gemini na tela).
  - A ativação ("Aura", Ctrl+Espaço, botão) é sempre **local**. Só depois dela o áudio vai para o Google, passando pelo servidor da A.U.R.A. (a chave não vai para o navegador).
  - Com o Live ligado, o modelo do PC sai da memória e o chat escrito também usa o Gemini: Flash, depois Flash-Lite se o Flash estiver lotado, e o modelo do PC só em último caso.
  - Sem chave, sem internet ou com erro, volta sozinho para o motor próprio.
- **Cérebro:** qualquer servidor compatível com OpenAI: Ollama, LM Studio, llama.cpp, vLLM, OpenAI, Groq, DeepSeek, Mistral, xAI, OpenRouter ou "Outro". As chaves ficam no banco local e a tela só mostra o final delas.
- **Trocar no meio da conversa:** o chip no campo de texto mostra a IA da conversa (verde = PC, amarelo = nuvem, laranja = assinatura).
  - Clique para escolher entre o padrão, os modelos do PC, a nuvem e as assinaturas (Claude e Codex respondem direto, na pasta de trabalho).
  - O novo modelo lê a conversa toda, e cada conversa lembra a sua IA.
- **Contas × chave de API:** as contas (Configurações → Contas) usam a sua assinatura Claude Pro/Max ou ChatGPT Plus como **agentes** (programação e pesquisa, mais lentos, sem as habilidades da A.U.R.A.). Uma chave de API vira **o cérebro** dela, com todas as habilidades, mas é paga por uso: a assinatura do ChatGPT não inclui a API.
- **Raciocínio privado:** `<think>` e afins nunca são falados, mostrados ou salvos.

## Habilidades

### Pasta de trabalho, projetos e anexos
- **Cowork** (barra de controles) escolhe a pasta de trabalho dentro de `C:\Users\<você>`.
  - Arquivos, Claude e Codex só mexem lá dentro.
  - AppData, `.ssh` e afins são bloqueados. O seletor tem **Nova pasta**.
- **Projetos e seções** (lateral): cada projeto tem a sua pasta e as suas conversas; seções organizam os projetos.
- **Anexos:** clipe, arrastar ou colar (até 10 arquivos, 25 MB cada). Vão para `anexos/` na pasta de trabalho.
- **Documentos e imagens:** PDF (inclusive escaneado), Word, Excel e PowerPoint viram texto. Imagens são descritas por um modelo com visão local (`qwen3-vl:2b-instruct`) ou pelo Gemini.

### Desfazer
- Tudo que muda algo entra num diário: arquivos criados, alterados, movidos ou apagados, tarefas do Codex, anotações, configurações, eventos, rascunhos e a casa inteligente.
- Desfaça pelo **↩ Desfazer** embaixo da resposta, ou falando "desfaz o que você fez".
- Apagar nunca apaga de verdade: vai para uma lixeira interna. Se você mexeu no arquivo depois, ela avisa antes de sobrescrever.

### Memória, instruções e skills
- **Memória** (Configurações → Memória):
  - Aprende fatos sobre você em segundo plano, só quando a frase fala de você.
  - Antes de responder, busca por significado (embeddings locais) só o que tem a ver com o pedido.
- **Instruções** (pasta `aura\memoria`, editável no Windows ou na tela):

  | Arquivo | Para quê |
  |---|---|
  | `INSTRUCOES.md` | Como ela deve agir em **toda** conversa |
  | `SOBRE-MIM.md` | O que ela deve sempre saber sobre você |
  | `AURA.md` (na pasta do projeto) | Instruções só daquele projeto |
  | `skills/<nome>/SKILL.md` | Guias sob demanda, no formato das skills do Claude |

  - "Anota nas suas instruções que..." grava no arquivo certo, com Desfazer.
  - Uma skill entra sozinha quando o pedido combina com a descrição dela.

### Computador (Configurações → Plugins → Nativos, desligado por padrão)
- **Abrir programas** procura na lista de apps do Windows, inclusive os da Microsoft Store (Spotify, WhatsApp...). Sem o app instalado, ela avisa e não abre a versão web por conta própria.
- **YouTube** ("abre uma live do Jornal da Globo", "toca Coldplay Yellow no YouTube"):
  - Com uma **chave grátis da API oficial do YouTube** (YouTube Data API v3, em Plugins → Controle do computador), ela busca, com o filtro "Ao vivo" para lives, e toca direto o resultado que mais combina com o pedido. A cota grátis dá ~100 buscas por dia.
  - Sem a chave, ela abre a lista de resultados para você escolher.
  - Abre **na aba do YouTube que já estiver aberta**, e só digita depois de confirmar que a janela em foco é mesmo a do YouTube.
- Listar e focar janelas, ler a tela (acessibilidade do Windows), print, volume e mídia.
- **Clicar, digitar e atalhos sempre pedem Autorizar.**
- **Energia e Wi-Fi:** desligar, reiniciar, suspender e Wi-Fi pedem Autorizar, e desligar ou reiniciar têm 30 s para cancelar. `AURA_POWER_DRYRUN=1` no `.env` só simula.

### Imagens (Nano Banana)
- "Cria uma imagem de...", ou anexe uma foto e peça uma edição. Usa a chave do Gemini.
- **Precisa de faturamento ativo na chave** (o plano gratuito tem cota 0 para imagens).
- As imagens ficam em `imagens/` na pasta de trabalho, com Desfazer.

### Agendados
- Tarefas que ela executa sozinha: "todo dia às 8h me resume a agenda", "dias úteis 7h…", "a cada 30 min…".
- Cada agendamento tem a sua conversa. Ações que mudam algo esperam o seu Autorizar.

## Conectores (Configurações → Conectores)

Catálogo no estilo do Claude/ChatGPT: o Google e 28 servidores MCP oficiais. Nada se instala sozinho.

| Como conecta | Serviços |
|---|---|
| **Google** (integração própria; a sua credencial do Google Cloud, cada serviço pede só a permissão dele) | Agenda, Gmail, Drive, Docs, Sheets |
| **Autorizar no site** (OAuth com PKCE; ela se cadastra sozinha) | Notion, Linear, Atlassian, monday.com, ClickUp, Todoist, Airtable, Zapier, Dropbox, Intercom, Canva, Figma, Webflow, Wix, Sentry, Supabase, Vercel, Stripe, PayPal, Square |
| **App seu** (redirecionamento `http://localhost:8765/api/mcp/oauth/callback`) | Asana, Box, HubSpot |
| **Token pessoal** | GitHub |
| **Aberto** | Hugging Face, Cloudflare Docs, Context7, DeepWiki |

- **Google:**
  1. No Google Cloud, crie um projeto, ative as APIs que quiser e configure o Google Auth Platform: público Externo, seu e-mail como usuário de teste, depois **Publicar app** para o login não expirar em 7 dias.
  2. Crie um cliente OAuth "Aplicativo da Web" com o redirecionamento `http://localhost:8765/api/google/callback`.
  3. Cole o ID e a chave secreta na tela.
- **O que cada serviço Google faz:**
  - **Agenda:** ver, criar, alterar e apagar eventos.
  - **Gmail:** buscar, ler, rascunhar e enviar.
  - **Drive:** buscar e ler.
  - **Docs e Sheets:** ler, criar e acrescentar.
  - O que não dá para desfazer (enviar e-mail, apagar evento, mexer em documento existente) pede Autorizar. Conteúdo de e-mails e arquivos é tratado como dado: ela não obedece ordens escritas neles.
- **MCP personalizado** (+ Personalizado): um endereço HTTP, ou um comando que roda no container (`npx`/`uvx`, com cache). Ferramentas que não são só leitura pedem Autorizar, a menos que o conector seja marcado como confiável.
- Os logos ficam em `aura/web/icons` e vêm do [Simple Icons](https://simpleicons.org) (CC0); as marcas pertencem aos seus donos.

## Plugins nativos (Configurações → Plugins)

### Spotify (precisa de Premium)
1. Em https://developer.spotify.com/dashboard → **Create app**. Redirect URI: `http://127.0.0.1:8765/api/spotify/callback`; API: **Web API**.
2. Cole o **Client ID** no card e clique em **Conectar** (PKCE: não precisa do Secret).

- "Toca a minha playlist Treino" procura primeiro nas suas playlists, depois artista, música, álbum ou músicas curtidas.
- Toca no aparelho ativo (PC, celular, Echo). Se nenhum estiver aberto e o controle do computador estiver ligado, abre o Spotify do PC.
- Também: pausar, pular, volume, aleatório e "o que está tocando?".

### Casa inteligente (Home Assistant)
1. Abra http://127.0.0.1:8123 e crie a sua conta.
2. Adicione os aparelhos no próprio HA: Configurações → Dispositivos e serviços → + Adicionar integração. Use **Tuya** para Smart Life; Hue, Xiaomi, TP-Link, Shelly, Broadlink e Google Cast também entram assim. Aparelhos da rede local entram pelo IP: a busca automática não atravessa o Docker no Windows.
3. Clique em **Conectar** no card.
4. Desmarque o que ela não deve ver.

- Luzes, tomadas, ar, cortinas, mídia, aspirador e cenas: na hora, com Desfazer.
- **Fechadura, alarme, portão e garagem:** sempre pedem Autorizar, sem Desfazer automático.
- Para um HA em outra máquina, use um token de longa duração.

### Telegram
1. No **@BotFather**: `/newbot`. Cole o token no card.
2. Mande uma mensagem para o bot e aprove o código de pareamento no card.

- Texto, áudio (Whisper local), fotos, documentos e botões Autorizar/Recusar. Só conversas aprovadas recebem resposta.
- Não expõe nada na internet (long polling). Comandos: `/nova` e `/ajuda`.

### Plugins personalizados
- **+ Enviar plugin** ou arraste um `.py`. Ele confere a sintaxe e carrega na hora.
- Cada função com `@tool` (`from aura.tools import tool`) vira uma habilidade; veja `plugins/sorteio.py`.
- Plugins rodam dentro da A.U.R.A.: só instale código de quem você confia.

## Configurações e aparência

- **Menu** (com busca):
  - **Preferências:** Geral, Aparência, Contas, Modelos, Voz e jeito, Memória, Instruções.
  - **Este computador:** Microfone e som, Backups.
  - **Personalização:** Skills, Conectores, Plugins.
- **Aparência:** temas Claro e Escuro, seis modelos de orbe (Esfera, Anéis, Galáxia, Onda, Enxame, Holograma) e cor livre.
- **Lateral:** barra de ícones (Conversas, Agendados, Agenda, Conectores, Skills, Mais), **Criar** e **Procurar** (Ctrl+K).
- **Backups:** automáticos ao ligar e a cada 6 h (se algo mudou), em `aura\backups`, com os 20 mais recentes. Contêm as suas chaves: não compartilhe a pasta.
- **Iniciar com o Windows** (Geral): grava `Aura.vbs` na pasta Inicializar, que roda o `iniciar.ps1` escondido no logon. Desligar apaga o arquivo. Pelo terminal: `.\autostart.ps1`, `-Status` ou `-Remover`.
- **Aplicativo na área de trabalho:** a A.U.R.A. é um aplicativo instalável (PWA). Ela abre numa janela própria, sem abas nem barra do navegador, com ícone no menu Iniciar e na barra de tarefas. A voz funciona igual e as atualizações chegam sozinhas.
  - Para instalar: Configurações → Geral → **Instalar**, ou pelo menu ⋯ do Edge/Chrome → Aplicativos → Instalar.
  - Os instaladores também criam um atalho **A.U.R.A.** que abre direto na janela do aplicativo: na área de trabalho e no menu Iniciar (Windows; para recriar: `.\instalar.ps1 -Atalho`), ou no menu de aplicativos (Linux com área de trabalho e Chrome/Chromium/Edge).
  - O `iniciar.ps1` também abre a A.U.R.A. nessa janela.
  - No Linux acessado de outro aparelho, a instalação só é oferecida com HTTPS válido (domínio próprio). Com o certificado autogerado, use pelo navegador.
- **⏻ Encerrar A.U.R.A.** (rodapé das Configurações): o agente do Windows para todos os containers dela e sai.
  - Opcionalmente fecha também o Docker Desktop, que libera mais memória.
  - Conversas e configurações ficam salvas. Para ligar de novo: `.\iniciar.ps1`.
  - No Linux/umbrelOS não há agente: encerre pelo terminal com `docker compose --profile '*' stop`.

## Desempenho

- **Cache do prompt:** a parte fixa do prompt (quem ela é, regras, lista de habilidades) não muda entre perguntas, e o Ollama reaproveita o cálculo. Hora, memórias e skill vão junto da mensagem. O modelo pensa em ~1 a 2 s.
- **Aquecimento:** ao ligar, ela carrega o modelo antes do primeiro pedido.
- **Memória do Ollama:**
  - Uma conversa por vez, cache de contexto em 8 bits e no máximo 2 modelos carregados.
  - Cópia de prompts em RAM limitada a 1 GB (`LLAMA_ARG_CACHE_RAM`; o padrão de 8 GB derrubava o Ollama por falta de memória).
- **WSL com 16 GB de RAM:** em `%USERPROFILE%\.wslconfig`:
  ```ini
  [wsl2]
  memory=10GB
  swap=8GB

  [experimental]
  autoMemoryReclaim=dropCache
  ```
  Depois `wsl --shutdown` e abra o Docker Desktop. O `autoMemoryReclaim` devolve ao Windows a memória que o Linux só usava como cache.

## Login no Claude e no Codex

**Pela tela:** Configurações → **Contas** → Conectar.
- **Codex:** abra o link e digite o código. A tela percebe sozinha quando termina.
- **Claude:** autorize com a sua conta Pro/Max e cole o código.

Pelo terminal:
```powershell
docker compose exec -it aura claude setup-token      # depois coloque em CLAUDE_CODE_OAUTH_TOKEN no .env
docker compose exec -it aura codex login --device-auth
```

## Comandos úteis

```powershell
.\iniciar.ps1                                       # sobe tudo (registro em iniciar.log)
docker compose logs -f aura                         # logs da A.U.R.A.
docker compose up -d --build aura                   # aplicar mudanças no código Python
docker compose exec ollama ollama ps                # modelos carregados
.\host-agent\start.ps1                              # sobe só o agente do Windows
```
A interface (`aura/web/index.html`) é montada ao vivo: basta F5.

## Estrutura do código

| Arquivo | Papel |
|---|---|
| `aura/server.py` | API (FastAPI), rotas da tela e inicialização |
| `aura/brain.py` | Loop do agente: monta o prompt, chama o modelo e as habilidades, Autorizar, anti-invenção |
| `aura/llm.py` | Provedores (Ollama, Gemini, OpenAI...), escolha de modelo, Gemini Live como padrão |
| `aura/live.py` | Gemini Live (voz em tempo real) |
| `aura/tools/` | Habilidades. Para criar uma, use `@tool(...)` (`sensitive=True` se age no mundo) |
| `aura/selfinfo.py`, `aura/settings.py`, `aura/config.py` | Autoconhecimento, preferências e prompt de sistema |
| `aura/memory.py`, `aura/facts.py`, `aura/instructions.py` | Memória, aprendizado de fatos, instruções e skills |
| `aura/actions.py` | Diário de ações e Desfazer |
| `aura/gcal.py`, `aura/connectors.py`, `aura/mcpclient.py` | Google, catálogo de conectores e cliente MCP |
| `aura/spotify.py`, `aura/homeassistant.py`, `aura/telegram.py` | Plugins nativos |
| `aura/hostbridge.py`, `host-agent/agent.ps1` | Ponte com o agente do Windows |
| `aura/workdir.py`, `aura/attachments.py`, `aura/docreader.py`, `aura/imagegen.py` | Pasta de trabalho, anexos, documentos e imagens |
| `aura/scheduler.py`, `aura/backup.py`, `aura/autostart.py` | Agendados, backups e início com o Windows |
| `voice/app.py` | Serviço de voz (ativação, Whisper, Kokoro/Piper) |

## Segurança

- Só esta máquina acessa a A.U.R.A. (`127.0.0.1`), e ela recusa pedidos vindos de outros sites (CSRF e DNS rebinding). O container roda sem root.
- Ações sensíveis (enviar e-mail, fechadura, clicar, desligar o PC...) só rodam depois do seu clique em **Autorizar**.
- O agente do Windows só executa uma lista fechada de comandos, com a chave `HOST_AGENT_TOKEN`.
- Conteúdo de e-mails, páginas e documentos é tratado como dado, nunca como ordem.

## Licença

A A.U.R.A. é **software livre**: você pode usar, estudar, modificar e redistribuir sob a
**[GNU Affero General Public License v3.0](LICENSE)** (AGPL-3.0-or-later). Quem distribuir uma versão modificada, ou
oferecê-la como serviço pela rede, precisa disponibilizar o código-fonte dela sob a mesma licença.
Componentes de terceiros e as licenças deles estão em [`NOTICE.md`](NOTICE.md); o que sai (ou não) da sua máquina está
em [`PRIVACIDADE.md`](PRIVACIDADE.md).

## Aviso

A A.U.R.A. é fornecida **"no estado em que se encontra", sem garantia de qualquer tipo** (veja as seções 15 e 16 da
licença). Ela pode controlar o computador, enviar e-mails, mexer em arquivos e em aparelhos da casa: as ações
sensíveis pedem a sua confirmação, mas a responsabilidade pelo uso é de quem a instala e opera. Não use para
segurança crítica (fechaduras, alarmes, saúde) sem um meio alternativo de controle.

## Apoie o projeto

A A.U.R.A. é gratuita e feita por hobby. Se ela te ajuda, doações são bem-vindas e ajudam a manter o projeto:
<!-- adicione aqui o seu link (GitHub Sponsors, PIX, Buy Me a Coffee...) -->
- *(link de doação em breve)*

Contribuições também são bem-vindas: abra uma *issue* com bugs e ideias, ou um *pull request*.

