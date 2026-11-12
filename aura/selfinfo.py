"""Autoconhecimento: a Aura descreve a si mesmo a partir do sistema real, a cada chamada.

Renomeou nas configuracoes, instalou um plugin, fez login no Claude, desligou o
container de voz? Ele passa a saber disso sem ninguem editar prompt.
"""
import time

import httpx

from . import llm, settings, workdir
from .tools import REGISTRY

# capacidades planejadas: se nenhuma ferramenta cobre, ele diz que ainda nao tem
PLANNED = {
    "agenda/calendario": ("agenda", "calendario", "evento"),
    "email": ("email", "gmail", "outlook"),
    "casa inteligente": ("casa", "luz", "lampada", "tomada", "home"),
}

_voice_cache = {"t": 0.0, "ok": False}


def _voice_ok() -> bool:
    if time.time() - _voice_cache["t"] > 30:
        try:
            _voice_cache["ok"] = httpx.get("http://voice:8767/health", timeout=1).status_code == 200
        except httpx.HTTPError:
            _voice_cache["ok"] = False
        _voice_cache["t"] = time.time()
    return _voice_cache["ok"]


def _top_level(limit: int = 20) -> str:
    """O que existe na raiz da pasta de trabalho (para o modelo nao inventar caminhos)."""
    try:
        items = sorted(workdir.current().iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except OSError:
        return "(nao consegui ler)"
    items = [x for x in items if not x.name.startswith((".", "$"))]
    if not items:
        return "(vazia)"
    names = [x.name + ("/" if x.is_dir() else "") for x in items[:limit]]
    return ", ".join(names) + (f" e mais {len(items) - limit}" if len(items) > limit else "")


def now_line() -> str:
    return (f"Agora: {['segunda', 'terca', 'quarta', 'quinta', 'sexta', 'sabado', 'domingo'][time.localtime().tm_wday]}, "
            f"{time.strftime('%d/%m/%Y %H:%M')}.")


def profile(ctx: dict | None = None) -> str:
    ctx = ctx or {}
    s = settings.get()
    active = [t for t in REGISTRY.values() if t.is_available()]
    inactive = [t for t in REGISTRY.values() if not t.is_available()]
    names = " ".join(t.name for t in active)
    missing = [cap for cap, keys in PLANNED.items() if not any(k in names for k in keys)]

    lines = [
        f"- Nome: {s['assistant_name']} (palavra de ativacao: \"{s['wake_word']}\"). Usuario: {s['user_name']}.",
        f"- Roda em: {ctx.get('host_os') or 'PC do usuario'} (servicos em containers Docker). "
        f"Cerebro (o modelo que esta respondendo agora): {ctx.get('brain') or llm.describe()}.",
        f"- Voz: {'ativa (ouve pelo microfone e responde falando)' if _voice_ok() else 'desligada no momento'}.",
        f"- Pasta de trabalho (onde voce, o Claude e o Codex mexem em arquivos): {workdir.to_windows(workdir.current())}. "
        "Nas ferramentas de arquivo use caminhos RELATIVOS a ela: 'hello.txt' fica direto nela; NAO repita o nome "
        f"da pasta. Itens na raiz agora: {_top_level()}.",
        # a data/hora NAO vai aqui: mudaria o prompt a cada minuto e o Ollama perderia o cache (ver brain.turn_context)
        # so os nomes: as descricoes ja vao para o modelo na lista de ferramentas (economiza contexto)
        "- Habilidades disponiveis agora: " + ", ".join(
            f"{t.name}{' (plugin)' if t.origin != 'nativa' else ''}" for t in active) + ".",
    ]
    if inactive:
        lines.append("- Instaladas mas indisponiveis agora (ex.: falta login): " + ", ".join(t.name for t in inactive) + ".")
    # por que o controle do PC (abrir programas/pastas, clicar, digitar) pode estar fora
    from . import hostbridge
    if not s.get("desktop_control"):
        lines.append("- Controle do computador: DESLIGADO. Se pedirem para abrir programas/pastas ou mexer na tela, "
                     "diga que o usuario precisa ligar o botao 'Controle' na barra de controles.")
    elif not hostbridge.agent_online():
        lines.append("- Controle do computador: ligado, mas o agente do Windows NAO esta rodando. Se pedirem para abrir "
                     "programas/pastas, diga para rodar o iniciar.ps1 (ou host-agent\\start.ps1) no Windows.")
    lines.append("- REGRA: so diga que fez algo (criou, salvou, abriu, apagou...) se chamou a ferramenta e ela confirmou. "
                 "Nunca invente arquivos, caminhos ou resultados.")
    if "agenda/calendario" in missing:
        missing.remove("agenda/calendario")
        lines.append("- Google Agenda: NAO conectado. Se pedirem agenda/compromissos, diga que da para conectar em "
                     "Configuracoes -> Conectores (com a conta Google do usuario).")
    if "email" in missing:
        missing.remove("email")
        lines.append("- E-mail: NAO conectado. Se pedirem e-mails, diga que da para conectar o Gmail em Configuracoes -> Conectores.")
    gapps = {"drive": "Google Drive", "docs": "Google Docs", "sheets": "Google Sheets"}
    from . import gcal
    off = [n for k, n in gapps.items() if not gcal.has(k)]
    from . import homeassistant, spotify
    if not spotify.configured():
        lines.append("- Spotify: NAO conectado (nao da para escolher playlist/musica). Se pedirem, diga que da para "
                     "conectar em Configuracoes -> Plugins -> Nativos -> Spotify; ate la so abrir o app e teclas de midia.")
    if not homeassistant.configured():
        lines.append("- Casa inteligente: NAO conectada. Se pedirem para controlar luzes/aparelhos, diga que da para "
                     "conectar o Home Assistant em Configuracoes -> Plugins -> Nativos -> Casa inteligente.")
    if off:
        lines.append(f"- NAO conectados: {', '.join(off)}. Se pedirem, diga que da para conectar em Configuracoes -> Conectores.")
    if missing:
        lines.append("- Ainda NAO conectado: " + ", ".join(missing) + ". Se pedirem, diga que a integracao ainda nao existe.")
    return "\n".join(lines)
