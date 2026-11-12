"""Telegram: fale com a Aura pelo celular, de qualquer lugar.

- Sem endereco publico: a Aura busca as mensagens do bot (long polling); nada fica exposto na internet.
- Seguranca: so conversas APROVADAS por voce na tela respondem. Quem fala com o bot pela primeira vez recebe
  um codigo; voce confere o codigo e aprova em Configuracoes -> Plugins -> Nativos -> Telegram. Os demais sao ignorados.
- Texto, audio (transcrito pelo Whisper local), fotos e documentos (viram anexos), botoes Autorizar/Recusar
  para acoes sensiveis e as imagens geradas voltam como foto.
"""
import asyncio
import json
import logging
import random
import time
import uuid
from pathlib import Path

import httpx

from . import attachments, brain, conversations, secrets, settings, workdir

log = logging.getLogger("uvicorn.error")
API = "https://api.telegram.org"
VOICE_URL = "http://voice:8767"

_state = {"task": None, "running": False, "bot": "", "error": "", "offset": 0, "last_ok": 0.0}
_pending: dict[int, dict] = {}            # chat_id -> {code, name, user, t}: pedidos de acesso esperando aprovacao


# ---------------- configuracao ----------------
def token() -> str:
    return secrets.get("telegram_token")


def chats() -> list[dict]:
    return list(settings.get().get("telegram_chats") or [])


def _save_chats(items: list[dict]):
    settings.update({"telegram_chats": items})


def _chat(chat_id: int) -> dict | None:
    return next((c for c in chats() if int(c["id"]) == int(chat_id)), None)


def status() -> dict:
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["t"] > 1800]:
        _pending.pop(k, None)
    return {"configured": bool(token()), "running": _state["running"], "bot": _state["bot"], "error": _state["error"],
            "chats": [{"id": c["id"], "name": c.get("name", "")} for c in chats()],
            "pending": [{"id": k, **{x: v[x] for x in ("code", "name", "user")}} for k, v in _pending.items()]}


# ---------------- API do Telegram ----------------
async def _call(client: httpx.AsyncClient, method: str, **data):
    files = data.pop("_files", None)
    r = await client.post(f"{API}/bot{token()}/{method}", data=data if files else None, json=None if files else data,
                          files=files, timeout=70)
    j = r.json()
    if not j.get("ok"):
        raise RuntimeError(j.get("description") or f"HTTP {r.status_code}")
    return j["result"]


async def check_token(tok: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.get(f"{API}/bot{tok}/getMe")
    j = r.json()
    if not j.get("ok"):
        raise ValueError("token invalido (confira com o @BotFather)")
    return j["result"]


async def _send(client, chat_id: int, text: str, **extra):
    text = (text or "").strip() or "(sem resposta)"
    for i in range(0, len(text), 4000):                  # limite do Telegram: 4096 caracteres por mensagem
        await _call(client, "sendMessage", chat_id=chat_id, text=text[i:i + 4000], **(extra if i + 4000 >= len(text) else {}))


async def _typing(client, chat_id: int, stop: asyncio.Event):
    while not stop.is_set():
        try:
            await _call(client, "sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), 4.5)
        except asyncio.TimeoutError:
            pass


async def _download(client, file_id: str) -> tuple[bytes, str]:
    f = await _call(client, "getFile", file_id=file_id)
    r = await client.get(f"{API}/file/bot{token()}/{f['file_path']}", timeout=120)
    r.raise_for_status()
    return r.content, Path(f["file_path"]).name


# ---------------- conversa ----------------
def _session(chat_id: int) -> str:
    c = _chat(chat_id)
    if c and c.get("sid"):
        return c["sid"]
    return _new_session(chat_id)


def _new_session(chat_id: int) -> str:
    sid = f"tg-{chat_id}-{uuid.uuid4().hex[:6]}"
    items = chats()
    for c in items:
        if int(c["id"]) == int(chat_id):
            c["sid"] = sid
    _save_chats(items)
    return sid


def _persist(sid: str, res: dict):
    if res["status"] == "done":
        imgs = [u for u in res.get("images") or [] if u.startswith("/api/workfile")]
        conversations.add(sid, "assistant", res.get("reply", "") + "".join(f"\n\n![imagem]({u})" for u in imgs), res.get("trace"))
    elif res["status"] == "confirm":
        a = res["action"]
        conversations.add(sid, "notice", f"Autorizacao solicitada: {a['tool']} {a['args']}")


def _image_path(url: str) -> Path | None:
    from urllib.parse import parse_qs, unquote, urlparse
    if url.startswith("/api/workfile"):
        p = Path(unquote(parse_qs(urlparse(url).query).get("p", [""])[0]))
        return p if p.is_file() and workdir._allowed(p) else None
    if url.startswith("/api/screens/"):
        from .tools import desktop
        p = desktop.SCREENS / Path(url).name
        return p if p.is_file() else None
    return None


async def _deliver(client, chat_id: int, sid: str, res: dict):
    """Manda a resposta: texto, imagens geradas/prints e botoes de autorizacao."""
    _persist(sid, res)
    if res["status"] == "confirm":
        a = res["action"]
        args = json.dumps(a["args"], ensure_ascii=False)[:600]
        kb = {"inline_keyboard": [[{"text": "✅ Autorizar", "callback_data": f"ok:{sid}"}, {"text": "❌ Recusar", "callback_data": f"no:{sid}"}]]}
        await _send(client, chat_id, f"Preciso da sua autorização para:\n{a['tool']}\n{args}", reply_markup=kb)
        return
    await _send(client, chat_id, res.get("reply", ""))
    for url in res.get("images") or []:
        p = _image_path(url)
        if p:
            with open(p, "rb") as fh:
                await _call(client, "sendPhoto", chat_id=str(chat_id), _files={"photo": (p.name, fh.read())})


async def _ask(client, chat_id: int, text: str, files: list[str] | None = None, lang: str | None = None):
    sid = _session(chat_id)
    workdir.use_conversation(sid)
    s = brain.get_session(sid)
    if not s.pending:
        shown = text + ("\n📎 " + ", ".join(Path(f).name.split("-", 2)[-1] for f in files) if files else "")
        conversations.add(sid, "user", f"📱 {shown}", first_text=f"📱 {text[:50]}")
    stop = asyncio.Event()
    typing = asyncio.create_task(_typing(client, chat_id, stop))
    try:
        res = await brain.chat(sid, text, None, {"canal": "Telegram (celular): respostas curtas, sem tabelas largas"}, lang, files)
    except Exception as e:
        res = {"status": "done", "reply": f"Erro: {e}", "trace": []}
    finally:
        stop.set(); await typing
    await _deliver(client, chat_id, sid, res)


async def _handle_message(client, m: dict):
    chat_id = m["chat"]["id"]
    if m["chat"].get("type") != "private":
        return                                            # so conversas privadas
    who = m.get("from") or {}
    name = " ".join(x for x in (who.get("first_name"), who.get("last_name")) if x) or "?"
    if not _chat(chat_id):                                # desconhecido: pede aprovacao com codigo
        p = _pending.get(chat_id)
        if not p:
            p = _pending[chat_id] = {"code": f"{random.randint(0, 999999):06d}", "name": name,
                                     "user": who.get("username", ""), "t": time.time()}
            log.info("Telegram: pedido de acesso de %s (%s)", name, chat_id)
        await _send(client, chat_id, f"Olá! Para liberar este chat, abra a A.U.R.A. → Configurações → Plugins → Nativos → Telegram "
                                     f"e aprove o código {p['code']}.")
        return
    text = (m.get("text") or m.get("caption") or "").strip()
    if text in ("/start", "/ajuda", "/help"):
        await _send(client, chat_id, f"Oi, {name}! Pode falar comigo por texto ou áudio, mandar fotos e documentos.\n"
                                     "/nova — começa uma conversa nova")
        return
    if text == "/nova":
        _new_session(chat_id)
        await _send(client, chat_id, "Conversa nova. Pode mandar.")
        return
    lang = None
    if m.get("voice") or m.get("audio"):                  # audio: transcreve com o Whisper local
        au = m.get("voice") or m.get("audio")
        data, _ = await _download(client, au["file_id"])
        follow = settings.get().get("follow_language") is True
        r = await client.post(f"{VOICE_URL}/stt", params={"follow": str(follow).lower()}, content=data, timeout=180)
        j = r.json()
        heard = (j.get("text") or "").strip()
        if not heard:
            await _send(client, chat_id, "Não consegui entender o áudio. Pode repetir?")
            return
        lang = j.get("lang")
        await _send(client, chat_id, f"🎤 “{heard}”")
        text = heard if not text else f"{text}\n{heard}"
    files = []
    doc = m.get("document")
    photo = (m.get("photo") or [None])[-1]               # a maior resolucao
    if doc or photo:
        fid = (doc or photo)["file_id"]
        data, fname = await _download(client, fid)
        if doc and doc.get("file_name"):
            fname = doc["file_name"]
        sid = _session(chat_id)
        workdir.use_conversation(sid)
        saved = attachments.save(fname, data)
        files = [saved["path"]]
        text = text or ("O que tem nesta imagem?" if photo else "Leia este documento e me diga do que se trata.")
    if not text:
        return
    await _ask(client, chat_id, text, files, lang)


async def _handle_callback(client, cq: dict):
    chat_id = cq["message"]["chat"]["id"]
    await _call(client, "answerCallbackQuery", callback_query_id=cq["id"])
    if not _chat(chat_id):
        return
    action, _, sid = (cq.get("data") or "").partition(":")
    if not sid.startswith(f"tg-{chat_id}-"):
        return
    await _call(client, "editMessageReplyMarkup", chat_id=chat_id, message_id=cq["message"]["message_id"],
                reply_markup={"inline_keyboard": []})
    approve = action == "ok"
    conversations.add(sid, "notice", "Autorizado" if approve else "Recusado")
    workdir.use_conversation(sid)
    try:
        res = await brain.confirm(sid, approve)
    except Exception as e:
        res = {"status": "done", "reply": f"Erro: {e}", "trace": []}
    await _deliver(client, chat_id, sid, res)


async def _loop():
    _state.update(running=False, error="")
    tok = token()
    if not tok:
        return
    try:
        me = await check_token(tok)
        _state["bot"] = me.get("username", "")
    except Exception as e:
        _state["error"] = str(e)
        return
    _state["running"] = True
    log.info("Telegram: bot @%s ouvindo", _state["bot"])
    delay = 3
    async with httpx.AsyncClient(timeout=70) as client:
        while True:
            try:
                ups = await _call(client, "getUpdates", offset=_state["offset"], timeout=50,
                                  allowed_updates=["message", "callback_query"])
                _state.update(error="", last_ok=time.time()); delay = 3
                for u in ups:
                    _state["offset"] = u["update_id"] + 1
                    try:
                        if "message" in u:
                            asyncio.create_task(_handle_message(client, u["message"]))
                        elif "callback_query" in u:
                            asyncio.create_task(_handle_callback(client, u["callback_query"]))
                    except Exception as e:
                        log.warning("Telegram: erro tratando mensagem: %s", e)
            except asyncio.CancelledError:
                _state["running"] = False
                raise
            except Exception as e:
                _state["error"] = str(e)[:200]
                log.warning("Telegram: %s (tento de novo em %ss)", e, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)


def start():
    t = _state.get("task")
    if t and not t.done():
        t.cancel()
    _state["task"] = asyncio.create_task(_loop())


def approve(chat_id: int) -> bool:
    p = _pending.pop(int(chat_id), None)
    if not p:
        return False
    items = [c for c in chats() if int(c["id"]) != int(chat_id)]
    items.append({"id": int(chat_id), "name": p["name"] + (f" (@{p['user']})" if p["user"] else ""), "sid": ""})
    _save_chats(items)
    asyncio.create_task(_notify(int(chat_id), "Acesso liberado! Pode falar comigo por texto ou áudio. /nova começa outra conversa."))
    return True


def deny(chat_id: int):
    _pending.pop(int(chat_id), None)


def remove(chat_id: int):
    _save_chats([c for c in chats() if int(c["id"]) != int(chat_id)])


async def _notify(chat_id: int, text: str):
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            await _send(client, chat_id, text)
    except Exception as e:
        log.warning("Telegram: nao avisei %s: %s", chat_id, e)
