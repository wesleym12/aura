import asyncio
import json
import shutil
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import (accounts, actions, attachments, autostart, backup, brain, conversations, facts, gcal, homeassistant, hostbridge,
               instructions, live, spotify,
               llm, mcpclient, memory, scheduler, secrets, settings, telegram, workdir)
from .tools import desktop
from .config import OLLAMA_MODEL, OLLAMA_URL
from .tools import REGISTRY, load_all

load_all()
memory.init()
conversations.init()
settings.init()
actions.init()
secrets.init()
mcpclient.init()
instructions.init()               # cria memoria/INSTRUCOES.md, SOBRE-MIM.md e skills/ na primeira vez
scheduler.init()
backup.start()                    # backup automatico: ao ligar e a cada 6 h (so se algo mudou)


def _persist(sid: str, res: dict):
    """Grava no historico o que a Aura respondeu (ou o pedido de autorizacao)."""
    if res["status"] == "done":
        # imagens geradas ficam no historico (a tela mostra as linhas ![imagem](...) como imagem)
        imgs = [u for u in res.get("images") or [] if u.startswith("/api/workfile")]
        extra = "".join(f"\n\n![imagem]({u})" for u in imgs)
        conversations.add(sid, "assistant", res.get("reply", "") + extra, res.get("trace"))
    elif res["status"] == "confirm":
        a = res["action"]
        conversations.add(sid, "notice", f"Autorizacao solicitada: {a['tool']} {a['args']}")

app = FastAPI(title="Aura")
WEB = Path(__file__).parent / "web"

# ---- protecao: so a propria pagina da Aura pode mandar ordens ----
# Sem isto, qualquer site aberto no navegador poderia enviar pedidos para localhost (CSRF) ou se
# passar por localhost trocando o DNS (DNS rebinding).
ALLOWED_HOSTS = {"localhost:8765", "127.0.0.1:8765"}
ALLOWED_ORIGINS = {"http://localhost:8765", "http://127.0.0.1:8765"}


def origin_ok(headers) -> bool:
    if headers.get("host") not in ALLOWED_HOSTS:
        return False
    origin = headers.get("origin")
    return origin is None or origin in ALLOWED_ORIGINS   # sem Origin = nao e um navegador (ex.: agente, testes)


@app.middleware("http")
async def guard(request, call_next):
    if request.headers.get("host") not in ALLOWED_HOSTS:
        return JSONResponse({"detail": "host nao permitido"}, status_code=403)
    if request.method not in ("GET", "HEAD", "OPTIONS") and not origin_ok(request.headers):
        return JSONResponse({"detail": "origem nao permitida"}, status_code=403)
    return await call_next(request)


@app.on_event("startup")
async def _start_mcp():
    await mcpclient.start_all()        # conexoes MCP ficam abertas em segundo plano
    asyncio.create_task(scheduler.loop())   # tarefas agendadas
    telegram.start()                        # bot do Telegram (se o token estiver configurado)
    # motor proprio: carrega o modelo e o prompt fixo antes do primeiro pedido; Gemini Live: tira o modelo local da memoria
    asyncio.create_task(llm.unload_local() if llm.live_mode() else brain.warm_up())


# ---- Telegram ----
@app.get("/api/telegram")
def telegram_status():
    return telegram.status()


# ---- casa inteligente: Home Assistant (Configuracoes -> Plugins -> Nativos) ----
def _ha(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except homeassistant.HAError as e:
        raise HTTPException(400, str(e))


@app.get("/api/casa")
def casa_status():
    return homeassistant.status()


@app.get("/api/casa/auth")
def casa_auth(request: Request):
    from fastapi.responses import RedirectResponse
    origin = f"{request.url.scheme}://{request.headers.get('host', '127.0.0.1:8765')}"
    return RedirectResponse(homeassistant.auth_url(origin))


@app.get("/api/casa/callback")
def casa_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote
    if error or not code:
        return RedirectResponse("/?casa=" + quote("erro: " + (error or "login cancelado")))
    try:
        homeassistant.finish(code, state)
    except (homeassistant.HAError, httpx.HTTPError) as e:
        return RedirectResponse("/?casa=" + quote("erro: " + str(e)))
    return RedirectResponse("/?casa=ok")


@app.put("/api/casa/token")
def casa_token(body: dict):
    return _ha(homeassistant.set_token, body.get("url", ""), body.get("token", ""))


@app.delete("/api/casa")
def casa_disconnect():
    homeassistant.disconnect()
    return homeassistant.status()


@app.get("/api/casa/entities")
def casa_entities():
    items = _ha(homeassistant.entities, include_hidden=True)
    return [{k: e[k] for k in ("entity_id", "domain", "name", "state", "area", "unit", "security", "hidden")} for e in items]


@app.put("/api/casa/hidden")
def casa_hidden(body: dict):
    settings.update({"ha_hidden": body.get("hidden", [])})
    return {"ok": True}


# ---- Spotify (Configuracoes -> Plugins -> Nativos) ----
def _sp(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except spotify.SpotifyError as e:
        raise HTTPException(400, str(e))


@app.get("/api/spotify")
def spotify_status():
    return spotify.status()


@app.put("/api/spotify/client")
def spotify_client(body: dict):
    _sp(spotify.set_client, body.get("client_id", ""))
    return spotify.status()


@app.get("/api/spotify/auth")
def spotify_auth(request: Request):
    from fastapi.responses import RedirectResponse
    host = request.headers.get("host", "127.0.0.1:8765")
    back = f"http://{host}" if host.split(":")[0] in ("localhost", "127.0.0.1") else ""
    return RedirectResponse(_sp(spotify.auth_url, back))


@app.get("/api/spotify/callback")
def spotify_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote
    back = spotify.back_for(state)                    # volta para a aba de onde saiu (localhost ou 127.0.0.1)
    if error or not code:
        return RedirectResponse(back + "/?spotify=" + quote("erro: " + (error or "login cancelado")))
    try:
        spotify.finish(code, state)
    except (spotify.SpotifyError, httpx.HTTPError) as e:
        return RedirectResponse(back + "/?spotify=" + quote("erro: " + str(e)))
    return RedirectResponse(back + "/?spotify=ok")


@app.delete("/api/spotify")
def spotify_disconnect():
    spotify.disconnect()
    return spotify.status()


# ---- iniciar com o Windows (Configuracoes -> Geral) ----
@app.get("/api/autostart")
def autostart_status():
    return autostart.status()


@app.put("/api/autostart")
def autostart_on():
    try:
        return autostart.enable()
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/autostart")
def autostart_off():
    try:
        return autostart.disable()
    except OSError as e:
        raise HTTPException(400, str(e))


@app.put("/api/telegram/token")
async def telegram_token(body: dict):
    tok = str(body.get("token", "")).strip()
    try:
        me = await telegram.check_token(tok)
    except (ValueError, httpx.HTTPError) as e:
        raise HTTPException(400, str(e))
    secrets.put("telegram_token", tok)
    telegram.start()
    return {"ok": True, "bot": me.get("username", "")}


@app.delete("/api/telegram/token")
def telegram_disconnect():
    secrets.put("telegram_token", None)
    telegram.start()                        # sem token: para o bot
    return {"ok": True}


@app.post("/api/telegram/approve/{chat_id}")
def telegram_approve(chat_id: int):
    if not telegram.approve(chat_id):
        raise HTTPException(404, "pedido expirado; mande uma mensagem ao bot de novo")
    return telegram.status()


@app.post("/api/telegram/deny/{chat_id}")
def telegram_deny(chat_id: int):
    telegram.deny(chat_id)
    return telegram.status()


@app.delete("/api/telegram/chats/{chat_id}")
def telegram_remove(chat_id: int):
    telegram.remove(chat_id)
    return telegram.status()


# ---- Tarefas agendadas ----
@app.get("/api/schedules")
def schedules_list():
    return scheduler.list_all()


@app.post("/api/schedules")
def schedules_create(body: dict):
    try:
        return scheduler.save(body)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.patch("/api/schedules/{sid}")
def schedules_edit(sid: str, body: dict):
    if not scheduler.get(sid):
        raise HTTPException(404, "agendamento nao encontrado")
    try:
        return scheduler.save(body, sid)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))


@app.delete("/api/schedules/{sid}")
def schedules_delete(sid: str):
    scheduler.delete(sid)
    return {"ok": True}


@app.post("/api/schedules/{sid}/run")
async def schedules_run(sid: str):
    if not scheduler.get(sid):
        raise HTTPException(404, "agendamento nao encontrado")
    asyncio.create_task(scheduler.run(sid, manual=True))      # roda em segundo plano; a tela acompanha
    return {"ok": True}


@app.get("/api/schedules/events")
def schedules_events(since: float = 0):
    return {"now": __import__("time").time(), "events": scheduler.events(since)}


# ---- Google Agenda: login (OAuth com a credencial do proprio usuario) e painel ----
@app.get("/api/google/status")
def google_status():
    return gcal.status()


@app.put("/api/google/client")
def google_client(body: dict):
    cid, cs = str(body.get("client_id", "")).strip(), str(body.get("client_secret", "")).strip()
    if not cid.endswith(".apps.googleusercontent.com"):
        raise HTTPException(400, "o ID do cliente termina com .apps.googleusercontent.com")
    if cs:
        secrets.put("google_client_secret", cs)
    elif not gcal.client()[1]:
        raise HTTPException(400, "cole a chave secreta do cliente")
    if cid != gcal.client()[0]:
        gcal.disconnect()                                # outra credencial: login antigo nao vale mais
    secrets.put("google_client_id", cid)
    return gcal.status()


@app.get("/api/google/auth")
def google_auth(services: str = "calendar"):
    """Login no Google pedindo os servicos escolhidos (ex.: ?services=gmail,drive), mantendo os ja concedidos."""
    from fastapi.responses import RedirectResponse
    try:
        return RedirectResponse(gcal.auth_url([s for s in services.split(",") if s in gcal.SERVICES]))
    except gcal.GoogleError as e:
        raise HTTPException(400, str(e))


@app.get("/api/google/callback")
def google_callback(code: str = "", state: str = "", error: str = ""):
    from fastapi.responses import RedirectResponse
    from urllib.parse import quote
    if error:
        return RedirectResponse("/?google=" + quote("erro: " + error))
    try:
        gcal.finish(code, state)
    except (gcal.GoogleError, httpx.HTTPError) as e:
        return RedirectResponse("/?google=" + quote("erro: " + str(e)))
    return RedirectResponse("/?google=ok")


@app.post("/api/google/disconnect")
def google_disconnect():
    gcal.disconnect()
    return gcal.status()


def _gcal_call(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except gcal.GoogleError as e:
        raise HTTPException(502, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"sem conexao com o Google: {e}")


@app.get("/api/agenda")
async def agenda(start: str = "", days: int = 7):
    from datetime import date as _date
    if not gcal.connected():
        return {"connected": False, "events": []}
    d = _date.fromisoformat(start) if start else None
    from .tools.agenda import parse_date
    s, e = gcal.day_range(d or parse_date("hoje"), max(1, min(days, 62)))
    evs = await asyncio.to_thread(_gcal_call, gcal.events, s, e, 250)
    return {"connected": True, "email": secrets.get("google_email"), "start": s.isoformat(), "events": evs}


@app.post("/api/agenda")
async def agenda_create(body: dict):
    from datetime import date as _date, datetime as _dt, timedelta as _td
    title = str(body.get("title", "")).strip()
    day = str(body.get("date", ""))
    if not title or not day:
        raise HTTPException(400, "de um titulo e uma data")
    d = _date.fromisoformat(day)
    if body.get("all_day") or not body.get("start"):
        start, end = d, d + _td(days=1)
    else:
        start = _dt.fromisoformat(f"{day}T{body['start']}").replace(tzinfo=gcal.TZ)
        end = _dt.fromisoformat(f"{day}T{body['end']}").replace(tzinfo=gcal.TZ) if body.get("end") else start + _td(hours=1)
        if end <= start:
            end = start + _td(hours=1)
    ev = await asyncio.to_thread(_gcal_call, gcal.create, title[:200], start, end, str(body.get("location", ""))[:200],
                                 str(body.get("description", ""))[:2000])
    aid = actions.record("criar_evento", f"Criou o evento '{ev['title']}' (pelo painel)", "gcal_create",
                         {"calendar": ev["calendar"], "id": ev["id"]})
    return {**ev, "action": aid}


@app.delete("/api/agenda/event")
async def agenda_delete(calendar: str, event_id: str):
    old = await asyncio.to_thread(_gcal_call, gcal.get, calendar, event_id)
    await asyncio.to_thread(_gcal_call, gcal.delete, calendar, event_id)
    aid = actions.record("apagar_evento", f"Apagou o evento '{old.get('summary', '')}' (pelo painel)", "gcal_delete",
                         {"calendar": calendar, "event": old})
    return {"ok": True, "action": aid}


# ---- Instrucoes em markdown, skills e plugins (aba Instrucoes) ----
@app.get("/api/instructions")
def instructions_get(session: str = "", project: str = ""):
    proj = workdir.use_conversation(session or None, project or None)
    pf = instructions.project_file()
    return {"dir_win": workdir.to_windows(instructions.MD_DIR) if str(instructions.MD_DIR).startswith("/host") else "aura\\memoria",
            "files": {k: {"name": n, "label": lab, "text": instructions.read(k)} for k, (n, lab, _) in instructions.FILES.items()},
            "project": {"name": proj["name"] if proj else "", "path": workdir.to_windows(pf), "text": instructions.read_project(),
                        "is_project": bool(proj)},
            "budget": instructions._budget()}


@app.put("/api/instructions/{key}")
def instructions_put(key: str, body: dict, session: str = "", project: str = ""):
    text = str(body.get("text", ""))[:60000]
    if key == "projeto":
        workdir.use_conversation(session or None, project or None)
        p = instructions.project_file()
        if text.strip():
            p.write_text(text.replace("\r\n", "\n"), encoding="utf-8")
        elif p.is_file():
            p.unlink()                                   # vazio = sem instrucoes de projeto
        return {"ok": True}
    if key not in instructions.FILES:
        raise HTTPException(404, "arquivo desconhecido")
    instructions.write(key, text)
    return {"ok": True}


@app.get("/api/skills")
def skills_list():
    return instructions.skills()


@app.get("/api/skills/{sid}")
def skill_get(sid: str):
    try:
        return {"id": sid, "source": instructions.skill_source(sid)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.put("/api/skills/{sid}")
def skill_put(sid: str, body: dict):
    try:
        instructions.save_skill(sid, str(body.get("source", "")))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.patch("/api/skills/{sid}")
def skill_toggle(sid: str, body: dict):
    off = set(settings.get().get("skills_off", []))
    (off.discard if body.get("enabled") else off.add)(sid)
    settings.update({"skills_off": sorted(off)})
    return {"ok": True}


@app.delete("/api/skills/{sid}")
def skill_delete(sid: str):
    try:
        instructions.delete_skill(sid)
    except ValueError as e:
        raise HTTPException(400, str(e))
    off = settings.get().get("skills_off", [])
    if sid in off:
        settings.update({"skills_off": [x for x in off if x != sid]})
    return {"ok": True}


@app.get("/api/plugins")
def plugins_list():
    """Plugins Python (pasta plugins/): o que cada um adicionou, ou o erro ao carregar."""
    from .tools import PLUGINS_DIR, load_plugins, plugin_errors
    load_plugins()                                     # pega arquivos copiados direto na pasta do Windows
    out: dict[str, list] = {}
    for t in REGISTRY.values():
        if t.origin.startswith("plugin:"):
            out.setdefault(t.origin.split(":", 1)[1], []).append(t.name)
    files = sorted(p.name for p in PLUGINS_DIR.glob("*.py") if not p.name.startswith("_")) if PLUGINS_DIR.is_dir() else []
    return [{"file": f, "tools": sorted(out.get(f, [])), "error": plugin_errors.get(f, ""),
             "size": (PLUGINS_DIR / f).stat().st_size} for f in files]


PLUGIN_MAX = 200 * 1024


@app.post("/api/plugins")
async def plugins_upload(file: UploadFile, replace: bool = False):
    """Instala um plugin (.py). Confere o nome e a sintaxe antes de salvar; carrega na hora."""
    import re as _re
    from .tools import PLUGINS_DIR, load_plugins, plugin_errors
    name = Path(file.filename or "").name
    if not _re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_\-]{0,60}\.py", name) or name.startswith("_"):
        raise HTTPException(400, "nome invalido: use letras, numeros, _ ou - e a extensao .py (ex.: meu_plugin.py)")
    data = await file.read()
    if len(data) > PLUGIN_MAX:
        raise HTTPException(400, "arquivo grande demais (maximo 200 KB)")
    try:
        src = data.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "o arquivo precisa ser texto UTF-8")
    try:
        compile(src, name, "exec")                    # so confere a sintaxe (nao executa)
    except SyntaxError as e:
        raise HTTPException(400, f"erro de sintaxe na linha {e.lineno}: {e.msg}")
    dst = PLUGINS_DIR / name
    if dst.exists() and not replace:
        raise HTTPException(409, f"ja existe um plugin chamado {name}")
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        dst.write_text(src, encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"nao consegui gravar na pasta plugins ({e}). Reinicie com: docker compose up -d aura")
    load_plugins()
    tools = sorted(t.name for t in REGISTRY.values() if t.origin == f"plugin:{name}")
    return {"file": name, "tools": tools, "error": plugin_errors.get(name, "")}


@app.delete("/api/plugins/{name}")
def plugins_delete(name: str):
    from .tools import PLUGINS_DIR, load_plugins
    p = PLUGINS_DIR / Path(name).name
    if p.suffix != ".py" or not p.is_file():
        raise HTTPException(404, "plugin nao encontrado")
    p.unlink()
    load_plugins()                                     # tira as habilidades dele na hora
    return {"ok": True}


# ---- Catalogo de conectores (como o do Claude/ChatGPT) ----
@app.get("/api/connectors")
def connectors_list():
    from . import connectors
    return connectors.listing(mcpclient.servers(), gcal.status())


@app.post("/api/connectors/{cid}/connect")
async def connector_connect(cid: str, body: dict | None = None):
    """Conecta um item do catalogo: cria a conexao MCP e, se for OAuth, devolve o link de autorizacao."""
    from . import connectors
    body = body or {}
    c = connectors.BY_ID.get(cid)
    if not c or c["kind"] == "builtin":
        raise HTTPException(404, "conector nao encontrado")
    s = next((x for x in mcpclient.servers() if x["catalog_id"] == cid), None)
    data = {"name": c["name"], "kind": "http", "target": c["url"], "catalog_id": cid, "enabled": True,
            "oauth": c["kind"] in ("oauth", "oauth_app")}
    if c["kind"] == "token":
        tok = str(body.get("token", "")).strip()
        if not tok and not (s and s["env"].get("Authorization")):
            raise HTTPException(400, "cole o token")
        if tok:
            data["env"] = f"Authorization=Bearer {tok.removeprefix('Bearer ').strip()}"
    if c["kind"] == "oauth_app":
        if body.get("client_id"):
            data["client_id"], data["client_secret"] = body["client_id"], body.get("client_secret", "")
        elif not s:
            raise HTTPException(400, "cole o Client ID do app que voce criou no servico")
    try:
        s = mcpclient.save(data, s["id"] if s else None)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await mcpclient.restart(s["id"])
    for _ in range(40):                                # espera o link de login (OAuth) ou a conexao ficar pronta
        p = mcpclient.public(mcpclient.server(s["id"]))
        if p["status"] in ("ok", "error", "needs_auth") and (p["status"] != "needs_auth" or p["auth_url"]):
            break
        await asyncio.sleep(0.25)
    return mcpclient.public(mcpclient.server(s["id"]))


@app.post("/api/connectors/{cid}/disconnect")
async def connector_disconnect(cid: str):
    s = next((x for x in mcpclient.servers() if x["catalog_id"] == cid), None)
    if s:
        await mcpclient.remove(s["id"])               # apaga a conexao e o login guardado
    return {"ok": True}


@app.get("/api/mcp/oauth/callback")
def mcp_oauth_callback(code: str = "", state: str = "", error: str = "", error_description: str = ""):
    """Volta do login de um conector: entrega o codigo para a conexao e mostra uma pagina simples."""
    from fastapi.responses import HTMLResponse
    import html as _h
    name = mcpclient.finish_oauth(code, state) if code and not error else None
    ok = bool(name)
    msg = (f"{_h.escape(name)} conectado!" if ok else
           f"Não deu certo: {_h.escape(error_description or error or 'pedido expirado; clique em Conectar de novo')}")
    page = f"""<!doctype html><meta charset="utf-8"><title>Conector</title>
<style>body{{font:16px system-ui,sans-serif;display:grid;place-items:center;height:100vh;margin:0;background:#eef1f5;color:#2f3640}}
.c{{background:#fff;padding:28px 34px;border-radius:16px;box-shadow:0 10px 30px rgba(30,40,60,.12);text-align:center}}
b{{color:{'#2e9e6a' if ok else '#d64545'}}}</style>
<div class="c"><p><b>{msg}</b></p><p>Pode fechar esta aba e voltar para a Aura.</p></div>
<script>try{{localStorage.setItem('auraConnector', Date.now())}}catch(e){{}};setTimeout(()=>window.close(),1500)</script>"""
    return HTMLResponse(page, status_code=200 if ok else 400)


# ---- Conexoes MCP ----
@app.get("/api/mcp")
def mcp_list():
    return [mcpclient.public(s) for s in mcpclient.servers()]


@app.post("/api/mcp")
async def mcp_add(body: dict):
    try:
        s = mcpclient.save(body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await mcpclient.restart(s["id"])
    return mcpclient.public(s)


@app.patch("/api/mcp/{sid}")
async def mcp_edit(sid: str, body: dict):
    s = mcpclient.server(sid)
    if not s:
        raise HTTPException(404, "conexao nao encontrada")
    try:
        if set(body) - {"enabled", "trusted"}:
            # sem "env" no pedido = mantem as variaveis/tokens guardados
            s = mcpclient.save({**{k: v for k, v in s.items() if k != "env"}, **body}, sid)
        else:
            s = mcpclient.set_flags(sid, **body)
    except ValueError as e:
        raise HTTPException(400, str(e))
    await mcpclient.restart(sid)
    return mcpclient.public(s)


@app.post("/api/mcp/{sid}/restart")
async def mcp_restart(sid: str):
    if not mcpclient.server(sid):
        raise HTTPException(404, "conexao nao encontrada")
    await mcpclient.restart(sid)
    return mcpclient.public(mcpclient.server(sid))


@app.delete("/api/mcp/{sid}")
async def mcp_remove(sid: str):
    await mcpclient.remove(sid)
    return {"ok": True}


class ChatIn(BaseModel):
    session: str
    message: str
    context: dict | None = None   # ex.: {"host_os": "Windows 11 Pro"}
    lang: str | None = None       # lingua que o Whisper ouviu (a voz te segue)
    files: list[str] | None = None  # anexos ja enviados por /api/upload (caminhos na pasta de trabalho)
    project: str | None = None      # projeto (so conta quando a conversa e nova)
    model: str | None = None        # modelo/IA desta conversa (seletor do chat); None = nao mexe


class ConfirmIn(BaseModel):
    session: str
    approve: bool


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/icons/{name}")
def icon(name: str):
    """Logos dos conectores (Simple Icons, CC0), guardados em web/icons: nada vem da internet na hora."""
    import re
    p = WEB / "icons" / name
    if not re.fullmatch(r"[a-z0-9-]+\.svg", name) or not p.is_file():
        raise HTTPException(404)
    return FileResponse(p, media_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})


def _stream(sid: str, run, learn_from: str | None = None) -> StreamingResponse:
    """Responde em NDJSON: eventos ao vivo ({"type":"ack"|"tool"}) e por ultimo {"type":"result"}.
    Depois da resposta, aprende fatos da mensagem do usuario em segundo plano."""
    queue: asyncio.Queue = asyncio.Queue()

    async def emit(ev: dict):
        if ev["type"] == "ack":
            conversations.add(sid, "assistant", ev["text"])   # o aviso tambem fica no historico
        await queue.put(ev)

    async def work():
        try:
            res = await run(emit)
            _persist(sid, res)
            await queue.put({"type": "result", **res})
            if learn_from:
                facts.learn_later(sid, learn_from)
        except llm.LLMError as e:
            await queue.put({"type": "error", "detail": str(e)})
        except httpx.HTTPError as e:
            await queue.put({"type": "error", "detail": f"Falha ao falar com {llm.default_cfg()['label']} ({type(e).__name__}); tente de novo"})
        except Exception as e:  # nao deixa o navegador esperando para sempre
            await queue.put({"type": "error", "detail": f"Erro interno: {e}"})
        finally:
            await queue.put(None)

    async def gen():
        task = asyncio.create_task(work())
        while (ev := await queue.get()) is not None:
            yield json.dumps(ev, ensure_ascii=False) + "\n"
        await task

    return StreamingResponse(gen(), media_type="application/x-ndjson")


def _valid_choice(choice: str) -> str:
    if not choice:
        return ""
    if llm.is_agent(choice):
        if choice.split(":", 1)[1] not in llm.AGENTS:
            raise HTTPException(400, "IA desconhecida")
        return choice
    prov = choice.split(":", 1)[0]
    if prov not in llm.PROVIDERS or ":" not in choice:
        raise HTTPException(400, "modelo invalido (use provedor:modelo)")
    return choice[:200]


def _switch_model(conv_id: str, choice: str):
    """Troca o modelo/IA da conversa; a troca fica registrada no historico."""
    choice = _valid_choice(choice)
    conv = conversations.get(conv_id)
    if conv and (conv.get("model") or "") == choice:
        return
    if conv:
        conversations.set_model(conv_id, choice)
        lab = llm.label_for(choice)
        conversations.add(conv_id, "notice", f"Modelo trocado para {lab['name']} ({lab['where']}).")
    s = brain.SESSIONS.get(conv_id)
    if s:
        s.model = choice


@app.get("/api/models")
async def model_choices():
    """Opcoes do seletor de modelo/IA do chat."""
    return await llm.choices()


@app.get("/api/models/more")
async def model_more(provider: str):
    """Todos os modelos de um provedor com chave (para escolher um que nao esta nos favoritos)."""
    if provider not in llm.PROVIDERS:
        raise HTTPException(400, "provedor desconhecido")
    try:
        models = await llm.list_models(provider)
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(502, f"Nao consegui listar os modelos: {e}")
    models = [m.removeprefix("models/") for m in models if not any(x in m.lower() for x in llm._NOT_CHAT + ("tts", "image", "audio", "dall-e", "moderation", "realtime", "transcribe"))]
    return {"models": models[:400]}


@app.get("/api/models/label")
def model_label(choice: str = ""):
    return llm.label_for(_valid_choice(choice))


@app.post("/api/chat")
async def chat(body: ChatIn):
    s = brain.get_session(body.session)  # carrega o contexto antes de gravar a mensagem nova
    proj = workdir.use_conversation(body.session, body.project)
    files = [f for f in (body.files or []) if attachments.resolve(f)][:10]
    model = _valid_choice(body.model) if body.model is not None else None
    if not s.pending:
        shown = body.message + ("\n📎 " + ", ".join(Path(f).name.split("-", 2)[-1] for f in files) if files else "")
        conversations.add(body.session, "user", shown, project_id=proj["id"] if proj else None)
        if model is not None:
            conversations.set_model(body.session, model)    # a conversa lembra a IA escolhida
    return _stream(body.session,
                   lambda emit: brain.chat(body.session, body.message, emit, body.context, body.lang, files,
                                           proj["id"] if proj else None, model),
                   learn_from=None if s.pending else body.message)


@app.post("/api/confirm")
async def confirm(body: ConfirmIn):
    conversations.add(body.session, "notice", "Autorizado" if body.approve else "Recusado")
    return _stream(body.session, lambda emit: brain.confirm(body.session, body.approve, emit))


@app.post("/api/tts/gemini")
async def tts_gemini(body: dict):
    """Fala um texto com a voz do Gemini (motor Gemini Live): saudacao, teste de voz, respostas faladas."""
    text = str(body.get("text", "")).strip()
    if not text:
        raise HTTPException(400, "texto vazio")
    if not live.available():
        raise HTTPException(400, "chave do Gemini nao configurada")
    try:
        wav = await live.speak(text, body.get("voice"))
    except Exception as e:
        raise HTTPException(502, f"Gemini nao conseguiu falar: {str(e)[:200]}")
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.websocket("/ws/live")
async def ws_live(sock: WebSocket):
    if not origin_ok(sock.headers):
        await sock.close(code=1008)
        return
    await live.handle(sock)


# ---- agente do Windows: busca comandos aqui (precisa da chave secreta) ----
@app.get("/api/host/next")
async def host_next(request: Request):
    if not hostbridge.token_ok(request.headers.get("x-agent-token")):
        raise HTTPException(401, "chave do agente invalida")
    cmd = await hostbridge.next_command()
    return cmd if cmd else Response(status_code=204)


@app.post("/api/host/result")
async def host_result(request: Request, body: dict):
    if not hostbridge.token_ok(request.headers.get("x-agent-token")):
        raise HTTPException(401, "chave do agente invalida")
    hostbridge.deliver(int(body.get("id", 0)), bool(body.get("ok")), str(body.get("output", ""))[:6_000_000])
    return {"ok": True}


@app.get("/api/host/status")
def host_status():
    p = hostbridge.pending_shutdown
    left = int(p["at"] - __import__("time").time()) if p else 0
    if p and left <= 0:
        p.clear()
    return {"agent": hostbridge.agent_online(), "dryrun": hostbridge.DRYRUN,
            "pending": {"label": p["label"], "seconds": left} if p else None}


@app.post("/api/host/cancel")
async def host_cancel():
    """Botao Cancelar da tela: cancelar e sempre seguro, nao precisa de confirmacao."""
    ok, out = await hostbridge.run("abort")
    hostbridge.pending_shutdown.clear()
    if not ok:
        raise HTTPException(502, out)
    return {"ok": True, "output": out}


@app.get("/api/live")
def live_status():
    return live.status()


# ---- contas: Claude e ChatGPT (Codex) pelas suas assinaturas, conectadas pela tela ----
@app.get("/api/accounts")
def accounts_status():
    return accounts.status()


@app.post("/api/accounts/{provider}/login")
def accounts_login(provider: str):
    try:
        return accounts.start(provider)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/accounts/claude/code")
def accounts_claude_code(body: dict):
    code = str(body.get("code", "")).strip()
    if not code:
        raise HTTPException(400, "cole o codigo")
    try:
        return accounts.submit_code(code)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/accounts/{provider}/cancel")
def accounts_cancel(provider: str):
    accounts.cancel(provider)
    return {"ok": True}


@app.post("/api/accounts/{provider}/logout")
def accounts_logout(provider: str):
    accounts.logout(provider)
    return accounts.status()


# ---- backups do banco ----
@app.get("/api/backups")
def get_backups():
    return {"items": backup.list_backups(), "folder": "aura\\backups"}


@app.post("/api/backups")
def new_backup():
    res = backup.make("manual", force=True)
    return {"made": res, "items": backup.list_backups()}


@app.delete("/api/backups")
def delete_all_backups():
    n = 0
    for b in backup.list_backups():
        try:
            backup.remove(b["name"])
            n += 1
        except ValueError:
            pass
    return {"ok": True, "removed": n}


@app.delete("/api/backups/{name}")
def delete_backup(name: str):
    try:
        backup.remove(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "items": backup.list_backups()}


@app.post("/api/backups/{name}/restore")
def restore_backup(name: str):
    try:
        res = backup.restore(name)
    except ValueError as e:
        raise HTTPException(404, str(e))
    brain.SESSIONS.clear()          # conversas abertas sao recarregadas do banco restaurado
    return res


# ---- pasta de trabalho e anexos ----
@app.get("/api/workdir")
def get_workdir(session: str = "", project: str = ""):
    """Pasta de trabalho efetiva: a do projeto da conversa, ou a geral."""
    proj = workdir.use_conversation(session or None, project or None)
    p = workdir.current()
    return {"path": str(p), "win": workdir.to_windows(p), "name": p.name or "workspace",
            "mounted": workdir.HOST.is_dir(), "project": proj}


def _project_out(p: dict) -> dict:
    from pathlib import Path as _P
    return {**p, "win": workdir.to_windows(_P(p["folder"])), "exists": _P(p["folder"]).is_dir()}


@app.get("/api/projects")
def list_projects():
    return [_project_out(p) for p in conversations.projects()]


@app.post("/api/projects")
def create_project(body: dict):
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "de um nome ao projeto")
    try:
        folder = str(workdir.validate(str(body.get("folder", ""))))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _project_out(conversations.create_project(name, folder))


@app.patch("/api/projects/{pid}")
def edit_project(pid: str, body: dict):
    if not conversations.project(pid):
        raise HTTPException(404, "projeto nao encontrado")
    folder = None
    if body.get("folder"):
        try:
            folder = str(workdir.validate(str(body["folder"])))
        except ValueError as e:
            raise HTTPException(400, str(e))
    name = str(body["name"]).strip() if body.get("name") else None
    section_id = ...
    if "section_id" in body:
        section_id = body["section_id"] or None
        if section_id and not conversations.section(section_id):
            raise HTTPException(404, "secao nao encontrada")
    return _project_out(conversations.update_project(pid, name, folder, section_id))


@app.get("/api/sections")
def list_sections():
    return conversations.sections()


@app.post("/api/sections")
def create_section(body: dict):
    name = str(body.get("name", "")).strip()
    if not name:
        raise HTTPException(400, "de um nome a secao")
    return conversations.create_section(name)


@app.patch("/api/sections/{sid}")
def edit_section(sid: str, body: dict):
    if not conversations.section(sid):
        raise HTTPException(404, "secao nao encontrada")
    return conversations.update_section(sid, str(body.get("name") or "").strip() or None, int(body.get("move") or 0))


@app.delete("/api/sections/{sid}")
def remove_section(sid: str):
    conversations.delete_section(sid)
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def remove_project(pid: str):
    conversations.delete_project(pid)
    return {"ok": True}


@app.post("/api/projects/{pid}/open")
async def open_project_folder(pid: str):
    """Abre a pasta do projeto no Explorador do Windows (pelo agente)."""
    p = conversations.project(pid)
    if not p:
        raise HTTPException(404, "projeto nao encontrado")
    from pathlib import Path as _P
    ok, out = await hostbridge.run("open", path=workdir.to_windows(_P(p["folder"])))
    if not ok:
        raise HTTPException(502, out)
    return {"ok": True}


@app.patch("/api/conversations/{conv_id}")
def edit_conversation(conv_id: str, body: dict):
    if not conversations.get(conv_id):
        raise HTTPException(404, "conversa nao encontrada")
    if "title" in body and str(body["title"]).strip():
        conversations.rename(conv_id, str(body["title"]))
    if "model" in body:
        _switch_model(conv_id, str(body["model"] or ""))
    if "project_id" in body:
        pid = body["project_id"] or None
        if pid and not conversations.project(pid):
            raise HTTPException(400, "projeto nao encontrado")
        conversations.move(conv_id, pid)
        brain.reset(conv_id)          # a proxima mensagem ja usa a pasta do novo projeto
        proj = conversations.project(pid)
        from pathlib import Path as _P
        where = workdir.to_windows(_P(proj["folder"])) if proj else "a pasta de trabalho geral"
        note = f"Conversa movida para {'o projeto ' + proj['name'] if proj else 'fora dos projetos'}: a pasta agora e {where}."
        conversations.add(conv_id, "notice", note)
        # o modelo fica sabendo, para nao repetir o que viu na pasta antiga
        brain.get_session(conv_id).messages.append(
            {"role": "user", "content": f"[sistema] {note} O que voce listou ou leu antes era de outra pasta; "
                                        "use as ferramentas de novo para ver os arquivos."})
    return conversations.get(conv_id)


@app.get("/api/fs/dirs")
def fs_dirs(path: str = ""):
    return workdir.list_dirs(path or None)


@app.post("/api/fs/mkdir")
def fs_mkdir(body: dict):
    try:
        p = workdir.make_dir(str(body.get("parent", "")), str(body.get("name", "")))
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e))
    return workdir.list_dirs(str(p))


@app.get("/api/workfile")
def workfile(p: str):
    """Imagens da pasta de trabalho/projetos para mostrar no chat (so imagens, so pastas permitidas)."""
    path = Path(p).resolve()
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".gif"} or not path.is_file() or not workdir._allowed(path):
        raise HTTPException(404, "imagem nao encontrada")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=3600"})


@app.get("/api/screens/{name}")
def screen(name: str):
    p = desktop.SCREENS / Path(name).name
    if not p.is_file():
        raise HTTPException(404, "print nao encontrado")
    return FileResponse(p, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/upload")
async def upload(file: UploadFile, session: str = "", project: str = ""):
    workdir.use_conversation(session or None, project or None)   # anexo vai para a pasta do projeto
    data = await file.read()
    try:
        return await asyncio.to_thread(attachments.save, file.filename or "arquivo", data)
    except ValueError as e:
        raise HTTPException(413, str(e))


# ---- Motor: cerebro (LLM) e chaves, tudo pela tela ----
@app.get("/api/llm")
def llm_info():
    cur = llm.current()
    return {"providers": [{"id": k, **{kk: v for kk, v in p.items()}} for k, p in llm.PROVIDERS.items()],
            "current": {k: cur[k] for k in ("provider", "label", "base", "model", "local")},
            "keys": secrets.masked(), "default_model": llm.OLLAMA_MODEL}


@app.get("/api/llm/models")
async def llm_models(provider: str, base: str = ""):
    try:
        return {"models": await llm.list_models(provider, base or None)}
    except (httpx.HTTPError, ValueError) as e:
        raise HTTPException(502, f"Nao consegui listar os modelos: {e}")


@app.post("/api/llm/test")
async def llm_test():
    try:
        return await llm.test()
    except (httpx.HTTPError, KeyError, ValueError) as e:
        raise HTTPException(502, str(e))


@app.put("/api/secrets")
def put_secrets(body: dict):
    """Salva (ou apaga, com valor vazio) chaves de API. Nunca devolve a chave inteira."""
    allowed = set(llm.PROVIDERS) | {"gemini"}
    for name, value in body.items():
        if name in allowed:
            secrets.put(name, str(value or "")[:300])
    return {"keys": secrets.masked(), "live": live.available()}


@app.get("/api/settings")
def get_settings():
    return {
        "settings": settings.get(),
        "personalities": [{"id": k, "label": v[0], "desc": v[1]} for k, v in settings.PERSONALITIES.items()],
    }


@app.put("/api/settings")
async def put_settings(changes: dict):
    before = settings.get().get("engine")
    try:
        out = await asyncio.to_thread(settings.update, changes)
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    if out.get("engine") != before:
        # Gemini Live: o modelo local sai da memoria; motor proprio: volta a carregar (e aquecer) em segundo plano
        asyncio.create_task(llm.unload_local() if out["engine"] == "live" else brain.warm_up())
    return {"settings": out}


@app.get("/api/conversations")
def list_conversations():
    return conversations.list_all()


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str):
    return conversations.messages(conv_id)


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: str):
    conversations.delete(conv_id)
    brain.reset(conv_id)
    return {"ok": True}


@app.get("/api/memory")
def mem(q: str = "", kind: str = ""):
    """Painel de memoria: lista (ou busca por significado) o que a Aura guardou."""
    items = memory.list_items(kind or None, q or None)
    titles = {c["id"]: c["title"] for c in conversations.list_all(1000)}
    for it in items:   # de qual conversa veio (quando foi aprendido numa conversa)
        it["conv_title"] = titles.get(it.get("conv_id"))
    return {"items": items, "counts": memory.counts(), "kinds": memory.KINDS}


@app.post("/api/actions/{aid}/undo")
def undo_action(aid: int, force: bool = False):
    try:
        res = actions.undo(aid, force)
    except KeyError:
        raise HTTPException(404, "acao nao encontrada")
    except actions.Conflict as e:
        raise HTTPException(409, str(e))       # a tela pergunta se quer desfazer mesmo assim
    except (ValueError, OSError) as e:
        raise HTTPException(400, f"Nao foi possivel desfazer: {e}")
    a = actions.get(aid)
    if a and a["conv_id"] and not res.get("already") and conversations.get(a["conv_id"]):   # conversa apagada nao renasce
        conversations.add(a["conv_id"], "notice", f"Desfeito: {a['summary']}")
        s = brain.SESSIONS.get(a["conv_id"])
        if s:   # o modelo fica sabendo, para nao contar com o que foi desfeito
            s.messages.append({"role": "user", "content": f"[sistema] O usuario desfez esta acao: {a['summary']}."})
    for s in brain.SESSIONS.values():
        s.recall_q = None
    return {**res, "conv_id": a["conv_id"] if a else None}


@app.delete("/api/memory/{note_id}")
def mem_delete(note_id: int):
    if not memory.delete(note_id):
        raise HTTPException(404, "memoria nao encontrada")
    for s in brain.SESSIONS.values():
        s.recall_q = None            # forca nova busca: o item apagado nao volta ao prompt
    return {"ok": True}


@app.delete("/api/memory")
def mem_delete_kind(kind: str):
    if kind not in memory.KINDS:
        raise HTTPException(400, "tipo desconhecido")
    n = memory.delete_kind(kind)
    for s in brain.SESSIONS.values():
        s.recall_q = None
    return {"ok": True, "deleted": n}


@app.get("/api/status")
async def status():
    ollama, models, gpu = False, [], None
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            r = await c.get(f"{OLLAMA_URL}/api/tags")
            ollama = r.status_code == 200
            models = [m["name"] for m in r.json().get("models", [])]
            # % do modelo carregado que esta na GPU (None = modelo nao carregado agora)
            for m in (await c.get(f"{OLLAMA_URL}/api/ps")).json().get("models", []):
                if m.get("size"):
                    gpu = round(100 * m.get("size_vram", 0) / m["size"])
    except httpx.HTTPError:
        pass
    return {
        "ollama": ollama,
        "gpu": gpu,
        "memories": memory.count(),
        "model": llm.describe(),
        # para o topo e o rodape: so o nome do modelo, e se ele roda no PC ou na nuvem
        "llm_model": llm.current()["model"], "llm_local": llm.current()["local"], "llm_provider": llm.current()["label"],
        "engine": settings.get().get("engine"), "live": live.available(),
        "agent": hostbridge.agent_online(),           # agente do Windows (controle do PC, desligar, abrir pastas)
        "model_ready": any(m == OLLAMA_MODEL or m.split(":")[0] == OLLAMA_MODEL for m in models),
        "claude": bool(shutil.which("claude")),
        "codex": bool(shutil.which("codex")),
        "tools": [{"name": t.name, "sensitive": t.sensitive} for t in REGISTRY.values()],
    }
