# Checklist de testes

Testes de uso real (com as suas contas e aparelhos). Marque com `[x]` quando passar.

## Feitos
- [x] **Telegram:** bot criado, pareamento aprovado, conversa pelo celular.
- [x] **Abrir programa da Microsoft Store:** Spotify instalado abre como app (não a versão web).
- [x] **Abrir o YouTube** por voz com "Sempre" ligado.
- [x] **Pausar / continuar / pular** música ou vídeo por voz ("pausa a música no YouTube"), sem trocar o vídeo.
- [x] **Gemini Live por voz** com "Aura" e habilidades do computador.
- [x] **Modo conversa desligado:** depois de responder ela volta a "Dormindo · diga Aura" (Gemini Live).

## Pendentes
- [ ] **Login do Claude** (Configurações → Contas) e conversar escolhendo "Claude" no chip do chat.
- [ ] **Login do ChatGPT / Codex** (Configurações → Contas) e pedir uma tarefa de programação.
- [ ] **Google Agenda com credencial real** (e depois Gmail, Drive, Docs e Sheets).
- [ ] **Spotify:** criar o app no painel do Spotify, colar o Client ID, "toca a minha playlist WFM", "pula essa", "o que está tocando?".
- [ ] **Casa inteligente:** criar a conta no Home Assistant, adicionar os aparelhos (Tuya/Smart Life), Conectar, "liga a luz da sala" e Desfazer.
- [ ] **Conector MCP com login** (ex.: Notion): autorizar no site e usar uma ferramenta.
- [ ] **YouTube na mesma aba:** com o YouTube aberto, "Aura, abre uma live de lofi no YouTube" troca o vídeo na mesma aba.
- [ ] **Autorizar pela voz no Gemini Live:** pedir uma ação sensível (ex.: clicar) e aprovar na tela.
- [ ] **Modo conversa no motor próprio** (sem Gemini Live): responde e volta a esperar "Aura".
- [ ] **Iniciar com o Windows:** reiniciar o PC e conferir se tudo sobe sozinho (`iniciar.log`).
- [ ] **Instalação no umbrelOS:** `bash instalar.sh` via SSH, acesso com senha e HTTPS pelo celular, microfone funcionando.
- [ ] **Instalação limpa no Windows:** em outra máquina (ou pasta), rodar `.\iniciar.ps1` sem `.env` e conferir se ele se configura.
