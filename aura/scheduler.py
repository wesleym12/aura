"""Tarefas agendadas: um pedido que o assistente executa sozinho num horario (uma vez, todo dia, em dias
da semana ou a cada N minutos). Ex.: "todo dia as 8h, resume minha agenda e os e-mails nao lidos".

Cada agendamento tem a sua conversa ("⏱ titulo"): os resultados ficam la, com as mesmas habilidades e o
Desfazer. Acoes sensiveis continuam pedindo Autorizar: a execucao para e espera voce abrir a conversa.
"""
import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta

from .config import DB_PATH

log = logging.getLogger("uvicorn.error")
KINDS = ("once", "daily", "weekly", "interval")
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sab", "dom"]
_events: list[dict] = []                     # resultados recentes (a tela mostra aviso e contador)
_running: set[str] = set()


def _db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def _tz():
    from .gcal import TZ
    return TZ


def now() -> datetime:
    return datetime.now(_tz())


def init():
    with closing(_db()) as c, c:
        c.execute("""CREATE TABLE IF NOT EXISTS schedules(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
            kind TEXT NOT NULL,                  -- once | daily | weekly | interval
            at TEXT DEFAULT '',                  -- HH:MM (daily/weekly) ou AAAA-MM-DD HH:MM (once)
            days TEXT DEFAULT '[]',              -- weekly: [0..6] (0 = segunda)
            every INTEGER DEFAULT 0,             -- interval: minutos
            project_id TEXT, enabled INTEGER DEFAULT 1,
            next_run TEXT, last_run TEXT, last_status TEXT DEFAULT '', last_summary TEXT DEFAULT '',
            created TEXT DEFAULT (datetime('now','localtime')))""")


def _row(r) -> dict:
    d = dict(r)
    d["days"] = json.loads(d["days"] or "[]")
    d["enabled"] = bool(d["enabled"])
    d["conv_id"] = conv_id(d["id"])
    d["when"] = describe(d)
    d["running"] = d["id"] in _running
    return d


def conv_id(sid: str) -> str:
    return f"sched-{sid}"


def list_all() -> list[dict]:
    with closing(_db()) as c:
        rows = c.execute("SELECT * FROM schedules ORDER BY enabled DESC, next_run").fetchall()
    return [_row(r) for r in rows]


def get(sid: str) -> dict | None:
    with closing(_db()) as c:
        r = c.execute("SELECT * FROM schedules WHERE id = ?", (sid,)).fetchone()
    return _row(r) if r else None


# ---------------- quando roda ----------------
def describe(s: dict) -> str:
    k, at = s["kind"], s.get("at") or ""
    if k == "once":
        try:
            dt = datetime.strptime(at, "%Y-%m-%d %H:%M")
            return f"uma vez, {dt:%d/%m} às {dt:%H:%M}"
        except ValueError:
            return "uma vez"
    if k == "daily":
        return f"todo dia às {at}"
    if k == "weekly":
        days = s.get("days") or []
        names = ", ".join(WEEKDAYS[d] for d in sorted(days)) if days else "?"
        return f"{names} às {at}"
    if k == "interval":
        m = int(s.get("every") or 0)
        return f"a cada {m // 60} h" if m and m % 60 == 0 else f"a cada {m} min"
    return k


def next_run(s: dict, after: datetime | None = None) -> datetime | None:
    after = after or now()
    k, at = s["kind"], s.get("at") or ""
    tz = _tz()
    if k == "once":
        try:
            dt = datetime.strptime(at, "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            return None
        return dt if dt > after - timedelta(minutes=1) and not s.get("last_run") else None
    if k == "interval":
        m = max(5, int(s.get("every") or 60))
        last = s.get("last_run")
        base = datetime.fromisoformat(last) if last else after
        nxt = base + timedelta(minutes=m) if last else after + timedelta(minutes=1)
        return max(nxt, after + timedelta(seconds=30))
    try:
        hh, mm = (int(x) for x in at.split(":"))
    except ValueError:
        return None
    days = set(range(7)) if k == "daily" else set(s.get("days") or [])
    if not days:
        return None
    for i in range(0, 8):
        d = (after + timedelta(days=i)).date()
        cand = datetime(d.year, d.month, d.day, hh, mm, tzinfo=tz)
        if d.weekday() in days and cand > after:
            return cand
    return None


def _validate(data: dict, old: dict | None = None) -> dict:
    s = {**(old or {}), **{k: v for k, v in data.items() if k in ("title", "prompt", "kind", "at", "days", "every", "project_id", "enabled")}}
    s["title"] = str(s.get("title") or "").strip()[:80]
    s["prompt"] = str(s.get("prompt") or "").strip()[:4000]
    if not s["prompt"]:
        raise ValueError("escreva o que ele deve fazer")
    if not s["title"]:
        s["title"] = s["prompt"][:50]
    if s.get("kind") not in KINDS:
        raise ValueError("frequencia invalida")
    if s["kind"] in ("daily", "weekly"):
        try:
            hh, mm = (int(x) for x in str(s.get("at", "")).split(":"))
            assert 0 <= hh < 24 and 0 <= mm < 60
            s["at"] = f"{hh:02d}:{mm:02d}"
        except (ValueError, AssertionError):
            raise ValueError("horario invalido (use HH:MM)")
    if s["kind"] == "weekly":
        s["days"] = sorted({int(d) for d in (s.get("days") or []) if 0 <= int(d) <= 6})
        if not s["days"]:
            raise ValueError("escolha pelo menos um dia da semana")
    if s["kind"] == "once":
        try:
            datetime.strptime(str(s.get("at", "")), "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("data/hora invalida (AAAA-MM-DD HH:MM)")
    if s["kind"] == "interval":
        s["every"] = max(5, min(7 * 24 * 60, int(s.get("every") or 60)))
    return s


def save(data: dict, sid: str | None = None) -> dict:
    old = get(sid) if sid else None
    s = _validate(data, old)
    if old and any(old.get(k) != s.get(k) for k in ("kind", "at", "days", "every")):
        s["last_run"] = None if s["kind"] == "once" else old.get("last_run")
    nxt = next_run(s) if s.get("enabled", True) else None
    with closing(_db()) as c, c:
        if old:
            c.execute("""UPDATE schedules SET title=?, prompt=?, kind=?, at=?, days=?, every=?, project_id=?, enabled=?,
                         next_run=?, last_run=? WHERE id=?""",
                      (s["title"], s["prompt"], s["kind"], s.get("at", ""), json.dumps(s.get("days") or []), int(s.get("every") or 0),
                       s.get("project_id"), int(bool(s.get("enabled", True))), nxt.isoformat() if nxt else None, s.get("last_run"), sid))
        else:
            sid = uuid.uuid4().hex[:10]
            c.execute("""INSERT INTO schedules(id, title, prompt, kind, at, days, every, project_id, enabled, next_run)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (sid, s["title"], s["prompt"], s["kind"], s.get("at", ""), json.dumps(s.get("days") or []),
                       int(s.get("every") or 0), s.get("project_id"), 1, nxt.isoformat() if nxt else None))
    return get(sid)


def delete(sid: str):
    with closing(_db()) as c, c:
        c.execute("DELETE FROM schedules WHERE id = ?", (sid,))


# ---------------- execucao ----------------
async def run(sid: str, manual: bool = False) -> dict:
    """Executa o pedido agora, na conversa do agendamento."""
    from . import brain, conversations, workdir
    s = get(sid)
    if not s or sid in _running:
        return {"ok": False}
    _running.add(sid)
    cid = s["conv_id"]
    started = now()
    status, summary = "ok", ""
    try:
        if not conversations.get(cid):
            conversations.add(cid, "notice", f"Conversa do agendamento “{s['title']}” ({s['when']}). Os resultados aparecem aqui.",
                              first_text=f"⏱ {s['title']}", project_id=s.get("project_id"))
        workdir.use_conversation(cid, s.get("project_id"))
        prompt = (f"[Tarefa agendada “{s['title']}”, {s['when']}, executada em {started:%d/%m %H:%M}. "
                  f"O usuario nao esta olhando agora: faca a tarefa e entregue o resultado completo, sem perguntas.]\n{s['prompt']}")
        conversations.add(cid, "user", f"⏱ {s['prompt']}")
        res = await brain.chat(cid, prompt, None, None, None, None, s.get("project_id"))
        if res.get("status") == "confirm":
            status, summary = "confirm", f"Precisa de Autorizar: {res['action']['tool']}"
            conversations.add(cid, "notice", f"Autorizacao solicitada: {res['action']['tool']} {res['action']['args']}")
        else:
            summary = (res.get("reply") or "").strip()
            conversations.add(cid, "assistant", summary, res.get("trace"))
    except Exception as e:
        status, summary = "error", f"Erro: {e}"
        log.warning("Agendamento %s falhou: %s", s["title"], e)
        try:
            conversations.add(cid, "notice", summary)
        except Exception:
            pass
    finally:
        _running.discard(sid)
    s2 = get(sid) or s
    s2["last_run"] = started.isoformat()
    nxt = next_run(s2, now()) if s2["enabled"] and not (s2["kind"] == "once") else None
    with closing(_db()) as c, c:
        c.execute("UPDATE schedules SET last_run=?, last_status=?, last_summary=?, next_run=?, enabled=? WHERE id=?",
                  (started.isoformat(), status, summary[:300], nxt.isoformat() if nxt else None,
                   0 if s2["kind"] == "once" else int(s2["enabled"]), sid))
    _events.append({"t": time.time(), "id": sid, "title": s["title"], "status": status, "summary": summary[:200],
                    "conv_id": cid, "manual": manual})
    del _events[:-50]
    return {"ok": True, "status": status, "summary": summary}


def events(since: float) -> list[dict]:
    return [e for e in _events if e["t"] > since]


async def loop():
    """Confere a cada 20 s se algum agendamento venceu."""
    await asyncio.sleep(15)
    while True:
        try:
            t = now()
            for s in list_all():
                if s["enabled"] and s["next_run"] and datetime.fromisoformat(s["next_run"]) <= t and s["id"] not in _running:
                    asyncio.create_task(run(s["id"]))
        except Exception as e:
            log.warning("Agendador: %s", e)
        await asyncio.sleep(20)
