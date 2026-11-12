"""Cerebro da Aura: qualquer servidor que fale o protocolo da OpenAI (/v1/chat/completions).

Locais: Ollama, LM Studio, llama.cpp, vLLM. Nuvem: OpenAI, Groq, DeepSeek, Mistral, xAI, OpenRouter.
Escolhido na tela (Configuracoes -> Motor), sem editar arquivos.

Tarefas internas (aviso instantaneo, aprender fatos) usam o Ollama local quando ele esta no ar:
nao custam nada e nao mandam conteudo extra para a nuvem.
"""
import asyncio
import json
import logging
import time

import httpx

from . import secrets, settings
from .config import OLLAMA_MODEL, OLLAMA_URL
from .textutil import strip_reasoning

_log = logging.getLogger("uvicorn.error")

PROVIDERS = {
    "ollama":     {"label": "Ollama (local, no Docker)", "base": f"{OLLAMA_URL}/v1", "key": False, "local": True},
    "lmstudio":   {"label": "LM Studio (no Windows)", "base": "http://host.docker.internal:1234/v1", "key": False, "local": True},
    "llamacpp":   {"label": "llama.cpp server", "base": "http://host.docker.internal:8080/v1", "key": False, "local": True},
    "vllm":       {"label": "vLLM", "base": "http://host.docker.internal:8000/v1", "key": False, "local": True},
    "openai":     {"label": "OpenAI", "base": "https://api.openai.com/v1", "key": True},
    "groq":       {"label": "Groq", "base": "https://api.groq.com/openai/v1", "key": True},
    "deepseek":   {"label": "DeepSeek", "base": "https://api.deepseek.com/v1", "key": True},
    "mistral":    {"label": "Mistral", "base": "https://api.mistral.ai/v1", "key": True},
    "xai":        {"label": "xAI (Grok)", "base": "https://api.x.ai/v1", "key": True},
    "openrouter": {"label": "OpenRouter", "base": "https://openrouter.ai/api/v1", "key": True},
    "gemini":     {"label": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai", "key": True},
    "custom":     {"label": "Outro (compatível com OpenAI)", "base": "", "key": False},
}


class LLMError(httpx.HTTPError):
    pass


def current() -> dict:
    s = settings.get()
    prov = s.get("llm_provider") if s.get("llm_provider") in PROVIDERS else "ollama"
    p = PROVIDERS[prov]
    return {"provider": prov, "label": p["label"],
            "base": (s.get("llm_base_url") or p["base"]).rstrip("/"),
            "model": s.get("llm_model") or (OLLAMA_MODEL if prov == "ollama" else ""),
            "key": secrets.get(prov), "local": p.get("local", False)}


def describe(cfg: dict | None = None) -> str:
    c = cfg or current()
    return f"{c['model'] or '(sem modelo)'} via {c['label']}"


# ---------- modelo por conversa ----------
# Uma "escolha" e um texto: "" (padrao do Motor), "<provedor>:<modelo>" (ex.: "ollama:qwen3:8b",
# "gemini:gemini-2.5-flash") ou "agent:claude" / "agent:codex" (a assinatura responde direto).
AGENTS = {"claude": "Claude (assinatura)", "codex": "ChatGPT · Codex (assinatura)"}
_gemini_cache = {"t": 0.0, "models": []}


async def gemini_suggestions() -> list[str]:
    """Modelos do Gemini para o seletor, lidos da API (o Google aposenta versoes; nada fixo no codigo).
    Os apelidos *-latest sempre apontam para a versao atual; mais a versao numerada mais nova de flash e pro."""
    import re
    if time.time() - _gemini_cache["t"] > 3600:
        try:
            names = [m.removeprefix("models/") for m in await list_models("gemini")]
        except (httpx.HTTPError, ValueError):
            names = []
        out = [n for n in ("gemini-flash-latest", "gemini-pro-latest") if n in names]
        # mais a versao "flash" numerada mais nova (fixa, para quem quer estabilidade)
        ver = [(tuple(int(x) for x in m.group(1).split(".")), n) for n in names
               if (m := re.fullmatch(r"gemini-([\d.]+)-flash", n))]
        if ver:
            out.append(max(ver)[1])
        _gemini_cache.update(t=time.time() if names else time.time() - 3300, models=out)
    return _gemini_cache["models"]
_NOT_CHAT = ("embed", "paraphrase", "nomic", "bge", "minilm", "-vl", "vision", "rerank", "whisper")


def is_agent(choice: str | None) -> bool:
    return bool(choice) and choice.startswith("agent:")


LIVE_CHAT_MODEL = "gemini-flash-latest"
LIVE_FALLBACKS = ["gemini-flash-lite-latest"]       # mais leve; o Google costuma ter folga nele quando o Flash lota
_live_bad = {"until": 0.0}


async def chat_live_default(messages: list, tools: list | None, pinned: dict | None = None) -> tuple[dict, dict]:
    """Chat padrao com o Gemini Live ligado: Flash -> Flash-Lite -> modelo do PC (ultimo recurso).
    O Flash sobrecarregado (503/limite/demora) fica 5 min de lado para nao fazer voce esperar a cada mensagem.
    Devolve (mensagem, config usada). `pinned`: o modelo que comecou este pedido continua ate o fim (o Gemini
    recusa chamadas de ferramenta feitas por outro modelo no meio do turno)."""
    if pinned:
        return await chat(messages, tools, cfg=pinned, timeout=60), pinned
    order = [LIVE_CHAT_MODEL, *LIVE_FALLBACKS]
    if time.time() < _live_bad["until"]:
        order = order[1:] + order[:1]
    base, last = default_cfg(), None
    for m in order:
        try:
            c = {**base, "model": m}
            return await chat(messages, tools, cfg=c, timeout=25), c
        except (LLMError, httpx.HTTPError) as e:
            last = e
            _log.warning("Gemini %s falhou no chat: %s %s", m, type(e).__name__, str(e)[:160])
            if m == LIVE_CHAT_MODEL:
                _live_bad["until"] = time.time() + 300
    local = current()
    if local.get("local") and _ollama_up():
        _log.warning("Gemini indisponivel: respondendo com o modelo do PC (sai da memoria de novo em 3 min)")
        _live_local_used["t"] = time.time()
        asyncio.get_running_loop().create_task(_unload_if_idle())
        return await chat(messages, tools, cfg=local), local
    raise last if isinstance(last, LLMError) else LLMError(f"o Gemini nao respondeu ({type(last).__name__}); tente de novo")


_live_local_used = {"t": 0.0}


async def _unload_if_idle(after: float = 180):
    """Live ligado e o modelo do PC foi so uma reserva: tira ele da memoria se ninguem usou nos ultimos minutos."""
    await asyncio.sleep(after)
    if live_mode() and time.time() - _live_local_used["t"] >= after - 1:
        await unload_local()


def default_cfg() -> dict:
    """Padrao do chat: o modelo do Motor; com o Gemini Live ligado, o Gemini (o Ollama fica fora da memoria)."""
    return (live_mode() and _gemini_internal()) or current()


def cfg_for(choice: str | None) -> dict:
    """Config do cerebro para uma escolha (vazio ou invalido = padrao: Motor, ou Gemini com o Live ligado)."""
    if not choice or is_agent(choice) or ":" not in choice:
        return default_cfg()
    prov, model = choice.split(":", 1)
    if prov not in PROVIDERS or not model:
        return default_cfg()
    cur = current()
    p = PROVIDERS[prov]
    base = cur["base"] if prov == cur["provider"] else p["base"]   # endereco personalizado do Motor vale para o mesmo provedor
    return {"provider": prov, "label": p["label"], "base": base.rstrip("/"), "model": model,
            "key": secrets.get(prov), "local": p.get("local", False)}


def label_for(choice: str | None) -> dict:
    """Nome curto para a tela: modelo + se e local/nuvem/assinatura."""
    if is_agent(choice):
        a = choice.split(":", 1)[1]
        return {"choice": choice, "name": "Claude" if a == "claude" else "Codex", "where": "assinatura", "local": False,
                "label": AGENTS.get(a, a)}
    c = cfg_for(choice)
    return {"choice": choice or "", "name": c["model"], "where": "local" if c["local"] else c["label"], "local": c["local"],
            "label": describe(c)}


def _ollama_models() -> list[str]:
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []
    return sorted(m["name"] for m in tags if not any(x in m["name"].lower() for x in _NOT_CHAT))


async def choices() -> dict:
    """Opcoes do seletor de modelo do chat."""
    from .tools.agents import claude_ready, codex_ready
    cur = current()
    s = settings.get()
    local = [{"choice": f"ollama:{m}", "name": m, "detail": "no seu PC (GPU)"} for m in _ollama_models()]
    cloud, seen = [], set()

    def add(prov: str, model: str, detail: str = ""):
        cid = f"{prov}:{model}"
        if prov in PROVIDERS and model and cid not in seen and (not PROVIDERS[prov]["key"] or secrets.get(prov)):
            seen.add(cid)
            cloud.append({"choice": cid, "name": model, "detail": detail or PROVIDERS[prov]["label"]})

    if not cur["local"]:
        add(cur["provider"], cur["model"])
    for fav in s.get("llm_favorites", []):
        if ":" in fav:
            add(*fav.split(":", 1))
    if secrets.get("gemini"):
        for m in await gemini_suggestions():
            add("gemini", m, "Google Gemini" + (" · sempre a versão mais nova" if m.endswith("-latest") else ""))
    keyed = [{"id": k, "label": p["label"]} for k, p in PROVIDERS.items() if p["key"] and secrets.get(k)]
    agents = [{"choice": "agent:claude", "name": "Claude", "detail": "sua assinatura · lê e edita a pasta de trabalho",
               "ready": claude_ready(), "why": "" if claude_ready() else "faça login em Configurações → Motor"},
              {"choice": "agent:codex", "name": "Codex (ChatGPT)", "detail": "sua assinatura · programação na pasta de trabalho",
               "ready": codex_ready(), "why": "" if codex_ready() else "faça login em Configurações → Motor"}]
    return {"default": label_for(""), "local": local, "cloud": cloud, "agents": agents, "providers": keyed}


def _headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg["key"]:
        h["Authorization"] = f"Bearer {cfg['key']}"
    if cfg["provider"] == "openrouter":
        h["HTTP-Referer"] = "http://localhost:8765"
        h["X-Title"] = "Aura"
    return h


_ollama_ok = {"t": 0.0, "ok": False}


def _ollama_up() -> bool:
    """O servidor do Ollama responde? (guardado por 30 s para nao consultar a cada chamada)"""
    if time.time() - _ollama_ok["t"] > 30:
        try:
            _ollama_ok["ok"] = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=2).status_code == 200
        except httpx.HTTPError:
            _ollama_ok["ok"] = False
        _ollama_ok["t"] = time.time()
    return _ollama_ok["ok"]


def live_mode() -> bool:
    """Motor Gemini Live ligado? (entao o modelo local fica descarregado para liberar memoria)"""
    return settings.get().get("engine") == "live"


def _gemini_internal() -> dict | None:
    if not secrets.get("gemini"):
        return None
    return {"provider": "gemini", "label": PROVIDERS["gemini"]["label"], "base": PROVIDERS["gemini"]["base"],
            "model": LIVE_CHAT_MODEL, "key": secrets.get("gemini"), "local": False}


async def unload_local():
    """Tira o modelo de conversa da GPU/RAM (o de busca na memoria, pequeno, continua)."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            await c.post(f"{OLLAMA_URL}/api/generate", json={"model": OLLAMA_MODEL, "keep_alive": 0})
    except httpx.HTTPError:
        pass


def _local_internal() -> dict | None:
    """Config para tarefas internas: o Ollama local (gratis, privado), ou o Gemini quando o Live esta ligado
    (o modelo local fica descarregado para liberar memoria e a conversa ja passa pelo Gemini)."""
    if live_mode():
        g = _gemini_internal()
        if g:
            return g
    if not _ollama_up():
        return None
    return {"provider": "ollama", "label": PROVIDERS["ollama"]["label"], "base": f"{OLLAMA_URL}/v1",
            "model": OLLAMA_MODEL, "key": "", "local": True}


def _err_text(r: httpx.Response) -> str:
    """So a mensagem do erro (os provedores mandam JSON, as vezes dentro de lista)."""
    try:
        j = r.json()
        j = j[0] if isinstance(j, list) and j else j
        e = j.get("error", j) if isinstance(j, dict) else {}
        msg = e.get("message") if isinstance(e, dict) else str(e)
        if msg:
            hint = {429: " Limite da conta/cota atingido.", 503: " O provedor esta sobrecarregado; tente de novo ou troque de modelo.",
                    404: " Esse modelo nao existe mais; escolha outro no seletor."}.get(r.status_code, "")
            return msg.strip()[:300] + hint
    except (ValueError, AttributeError):
        pass
    return r.text[:300]


async def chat(messages: list, tools: list | None = None, *, max_tokens: int | None = None,
               temperature: float | None = None, json_mode: bool = False, internal: bool = False,
               timeout: float = 300, cfg: dict | None = None) -> dict:
    """Devolve a mensagem do assistente no formato OpenAI (content ja sem raciocinio, tool_calls)."""
    cfg = cfg or ((_local_internal() or current()) if internal else current())
    if not cfg["base"] or not cfg["model"]:
        raise LLMError("modelo nao configurado (Configuracoes -> Motor)")
    payload: dict = {"model": cfg["model"], "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if temperature is not None:
        payload["temperature"] = temperature
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if not cfg.get("local"):
        timeout = min(timeout, 120)                 # nuvem travada nao prende a conversa por minutos
    async with httpx.AsyncClient(timeout=timeout) as client:
        t0 = time.time()
        r = await client.post(f"{cfg['base']}/chat/completions", json=payload, headers=_headers(cfg))
        if r.status_code == 400 and json_mode:      # nem todo servidor aceita response_format
            payload.pop("response_format")
            r = await client.post(f"{cfg['base']}/chat/completions", json=payload, headers=_headers(cfg))
        if r.status_code == 500 and cfg.get("local") and "stopped" in r.text:
            # Ollama derrubou o modelo (pouca memoria de video, ex.: outro modelo ainda carregado): ele recarrega
            await asyncio.sleep(3)
            r = await client.post(f"{cfg['base']}/chat/completions", json=payload, headers=_headers(cfg))
        for wait in (2, 5):                         # nuvem sobrecarregada/limite: tenta de novo (se o erro veio rapido)
            if r.status_code not in (429, 503) or time.time() - t0 > 20:
                break
            await asyncio.sleep(wait)
            r = await client.post(f"{cfg['base']}/chat/completions", json=payload, headers=_headers(cfg))
    if r.status_code >= 400:
        raise LLMError(f"{cfg['label']} ({cfg['model']}) respondeu {r.status_code}: {_err_text(r)}")
    msg = r.json()["choices"][0]["message"]
    msg["content"] = strip_reasoning(msg.get("content"))   # raciocinio nunca sai daqui
    msg.pop("reasoning_content", None)
    msg.pop("reasoning", None)
    return msg


async def list_models(provider: str, base: str | None = None, key: str | None = None) -> list[str]:
    p = PROVIDERS.get(provider, PROVIDERS["custom"])
    cfg = {"provider": provider, "label": p["label"], "base": (base or p["base"]).rstrip("/"),
           "key": key if key is not None else secrets.get(provider), "model": "", "local": p.get("local", False)}
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"{cfg['base']}/models", headers=_headers(cfg))
    if r.status_code >= 400:
        raise LLMError(f"{cfg['label']} respondeu {r.status_code}: {r.text[:200]}")
    data = r.json()
    items = data.get("data", data if isinstance(data, list) else [])
    return sorted({m.get("id") for m in items if isinstance(m, dict) and m.get("id")})


async def test() -> dict:
    """Pergunta curta para medir se o motor escolhido responde e quanto demora."""
    t0 = time.time()
    msg = await chat([{"role": "user", "content": "Responda apenas: ok"}], max_tokens=20, timeout=60)
    return {"ok": True, "seconds": round(time.time() - t0, 2), "reply": (msg.get("content") or "")[:80],
            "model": describe()}


def parse_json(text: str) -> dict:
    """JSON da resposta, mesmo que venha com texto em volta."""
    text = strip_reasoning(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        return json.loads(text[a:b + 1]) if a >= 0 < b else {}
