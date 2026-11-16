"""Rotina do dia a dia: tarefas, timers/lembretes/cronometro/foco e habitos (agua, leitura...).

Fica tudo no banco local. Os timers guardam a hora de terminar (epoch): a tela conta o tempo, toca o alarme e
avisa; o servidor so guarda e marca como avisado. Assim um timer sobrevive a recarregar a pagina ou trocar de modo.
"""
import sqlite3
import time
import unicodedata
import uuid
from contextlib import closing
from datetime import date

from .config import DB_PATH

PRIORITIES = ("alta", "media", "baixa")
TIMER_KINDS = ("timer", "lembrete", "foco", "pausa", "cronometro")
DEFAULT_HABITS = [("Água", 8, "copos", "💧")]


def _db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with closing(_db()) as c, c:
        c.execute("""CREATE TABLE IF NOT EXISTS tasks(
            id TEXT PRIMARY KEY, title TEXT NOT NULL, done INTEGER DEFAULT 0,
            priority TEXT DEFAULT 'media', parent TEXT, due TEXT DEFAULT '',
            created REAL, done_at REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS timers(
            id TEXT PRIMARY KEY, label TEXT NOT NULL, kind TEXT NOT NULL,
            started REAL NOT NULL, ends REAL,          -- ends vazio = cronometro (conta para cima)
            then_break INTEGER DEFAULT 0,              -- foco: minutos de pausa que comecam quando ele acaba
            fired INTEGER DEFAULT 0, stopped REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS habits(
            id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, target INTEGER DEFAULT 1,
            unit TEXT DEFAULT '', icon TEXT DEFAULT '', created REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS habit_log(
            habit TEXT NOT NULL, day TEXT NOT NULL, count INTEGER DEFAULT 0, PRIMARY KEY(habit, day))""")
        c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        if not c.execute("SELECT 1 FROM meta WHERE key='habits_seeded'").fetchone():   # so na primeira vez
            for name, target, unit, icon in DEFAULT_HABITS:
                c.execute("INSERT OR IGNORE INTO habits(id,name,target,unit,icon,created) VALUES(?,?,?,?,?,?)",
                          (_id(), name, target, unit, icon, time.time()))
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('habits_seeded','1')")


def _n(s: str) -> str:
    """Minusculas e sem acento: 'agua' acha 'Água'."""
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").strip().lower()) if unicodedata.category(c) != "Mn")


def _id() -> str:
    return uuid.uuid4().hex[:8]


def _today() -> str:
    from .scheduler import now
    return now().strftime("%Y-%m-%d")


# ---------------- tarefas ----------------
def tasks(include_done: bool = False) -> list[dict]:
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM tasks ORDER BY done, CASE priority WHEN 'alta' THEN 0 "
                                           "WHEN 'media' THEN 1 ELSE 2 END, created")]
    for r in rows:
        r["done"] = bool(r["done"])
    # concluidas aparecem ate o fim do dia em que foram feitas (depois somem da lista principal)
    start = time.time() - 18 * 3600
    return [r for r in rows if include_done or not r["done"] or (r["done_at"] or 0) > start]


def find_task(ref: str) -> dict | None:
    ref = _n(ref)
    items = tasks(include_done=True)
    return next((t for t in items if t["id"] == ref), None) or \
        next((t for t in items if _n(t["title"]) == ref), None) or \
        next((t for t in items if ref and ref in _n(t["title"]) and not t["done"]), None)


def add_task(title: str, priority: str = "media", parent: str | None = None, due: str = "") -> dict:
    title = (title or "").strip()[:200]
    if not title:
        raise ValueError("a tarefa precisa de um titulo")
    priority = priority if priority in PRIORITIES else "media"
    if parent:
        p = find_task(parent)
        if not p:
            raise ValueError(f"nao achei a tarefa '{parent}' para colocar a subtarefa")
        parent = p["id"]
    t = {"id": _id(), "title": title, "priority": priority, "parent": parent, "due": (due or "")[:40],
         "created": time.time()}
    with closing(_db()) as c, c:
        c.execute("INSERT INTO tasks(id,title,priority,parent,due,created) VALUES(:id,:title,:priority,:parent,:due,:created)", t)
    return {**t, "done": False}


def set_done(tid: str, done: bool = True) -> dict | None:
    with closing(_db()) as c, c:
        if done:      # concluir a tarefa conclui as subtarefas dela
            c.execute("UPDATE tasks SET done=1, done_at=? WHERE id=? OR parent=?", (time.time(), tid, tid))
        else:
            c.execute("UPDATE tasks SET done=0, done_at=NULL WHERE id=?", (tid,))
    return next((t for t in tasks(True) if t["id"] == tid), None)


def update_task(tid: str, **kw) -> dict | None:
    allowed = {k: v for k, v in kw.items() if k in ("title", "priority", "due") and v is not None}
    if "priority" in allowed and allowed["priority"] not in PRIORITIES:
        allowed.pop("priority")
    if allowed:
        with closing(_db()) as c, c:
            c.execute(f"UPDATE tasks SET {', '.join(f'{k}=?' for k in allowed)} WHERE id=?", (*allowed.values(), tid))
    return next((t for t in tasks(True) if t["id"] == tid), None)


def delete_task(tid: str) -> bool:
    with closing(_db()) as c, c:
        return c.execute("DELETE FROM tasks WHERE id=? OR parent=?", (tid, tid)).rowcount > 0


# ---------------- timers ----------------
def timers() -> list[dict]:
    """Ativos (e os que acabaram de tocar, para a tela avisar). Cronometro parado some depois de 1 h."""
    now = time.time()
    with closing(_db()) as c, c:
        c.execute("DELETE FROM timers WHERE (stopped IS NOT NULL AND stopped < ?) OR (fired=1 AND ends < ?)",
                  (now - 3600, now - 600))
        rows = [dict(r) for r in c.execute("SELECT * FROM timers ORDER BY COALESCE(ends, 9e18), started")]
    for r in rows:
        r["running"] = r["stopped"] is None and (r["ends"] is None or r["ends"] > now)
        r["left"] = max(0, round(r["ends"] - now)) if r["ends"] else None
        r["elapsed"] = round((r["stopped"] or now) - r["started"])
    return rows


def add_timer(seconds: float, label: str = "", kind: str = "timer", then_break: int = 0) -> dict:
    seconds = max(1, min(int(seconds), 24 * 3600))
    kind = kind if kind in TIMER_KINDS else "timer"
    now = time.time()
    t = {"id": _id(), "label": (label or {"foco": "Foco", "pausa": "Pausa"}.get(kind, "Timer")).strip()[:80],
         "kind": kind, "started": now, "ends": now + seconds, "then_break": int(then_break or 0)}
    with closing(_db()) as c, c:
        c.execute("INSERT INTO timers(id,label,kind,started,ends,then_break) VALUES(:id,:label,:kind,:started,:ends,:then_break)", t)
    return t


def start_stopwatch(label: str = "") -> dict:
    t = {"id": _id(), "label": (label or "Cronômetro").strip()[:80], "kind": "cronometro", "started": time.time()}
    with closing(_db()) as c, c:
        c.execute("INSERT INTO timers(id,label,kind,started) VALUES(:id,:label,:kind,:started)", t)
    return t


def stop_timer(tid: str) -> dict | None:
    """Para (cronometro: guarda o tempo; timer: cancela)."""
    t = next((x for x in timers() if x["id"] == tid), None)
    if not t:
        return None
    with closing(_db()) as c, c:
        if t["kind"] == "cronometro" and t["stopped"] is None:      # 1o: para e guarda o tempo; 2o: tira da lista
            c.execute("UPDATE timers SET stopped=? WHERE id=?", (time.time(), tid))
        else:
            c.execute("DELETE FROM timers WHERE id=?", (tid,))
    return t


def find_timer(ref: str) -> dict | None:
    ref = _n(ref)
    items = [t for t in timers() if t["running"]]
    if not ref:
        return items[0] if items else None
    return next((t for t in items if t["id"] == ref), None) or next((t for t in items if ref in _n(t["label"])), None)


def fire(tid: str) -> dict | None:
    """A tela tocou o alarme: marca como avisado e, se era foco com pausa, comeca a pausa."""
    t = next((x for x in timers() if x["id"] == tid), None)
    if not t or t["fired"]:
        return None
    with closing(_db()) as c, c:
        c.execute("UPDATE timers SET fired=1 WHERE id=?", (tid,))
    nxt = add_timer(t["then_break"] * 60, "Pausa", "pausa") if t["kind"] == "foco" and t["then_break"] else None
    return {"timer": t, "next": nxt}


# ---------------- habitos ----------------
def habits() -> list[dict]:
    day = _today()
    with closing(_db()) as c:
        rows = [dict(r) for r in c.execute(
            "SELECT h.*, COALESCE(l.count,0) AS count FROM habits h LEFT JOIN habit_log l ON l.habit=h.id AND l.day=? "
            "ORDER BY h.created", (day,))]
    return rows


def find_habit(ref: str) -> dict | None:
    ref = _n(ref)
    items = habits()
    return next((h for h in items if h["id"] == ref or _n(h["name"]) == ref), None) or \
        next((h for h in items if ref and (ref in _n(h["name"]) or _n(h["name"]) in ref)), None)


def add_habit(name: str, target: int = 1, unit: str = "", icon: str = "") -> dict:
    name = (name or "").strip()[:40]
    if not name:
        raise ValueError("o habito precisa de um nome")
    h = {"id": _id(), "name": name, "target": max(1, min(int(target or 1), 1000)), "unit": (unit or "")[:20],
         "icon": (icon or "")[:4], "created": time.time()}
    with closing(_db()) as c, c:
        c.execute("INSERT INTO habits(id,name,target,unit,icon,created) VALUES(:id,:name,:target,:unit,:icon,:created)", h)
    return {**h, "count": 0}


def log_habit(hid: str, delta: int = 1) -> dict | None:
    day = _today()
    with closing(_db()) as c, c:
        c.execute("INSERT INTO habit_log(habit,day,count) VALUES(?,?,0) ON CONFLICT(habit,day) DO NOTHING", (hid, day))
        c.execute("UPDATE habit_log SET count=MAX(0, count+?) WHERE habit=? AND day=?", (int(delta), hid, day))
    return next((h for h in habits() if h["id"] == hid), None)


def delete_habit(hid: str) -> bool:
    with closing(_db()) as c, c:
        c.execute("DELETE FROM habit_log WHERE habit=?", (hid,))
        return c.execute("DELETE FROM habits WHERE id=?", (hid,)).rowcount > 0


def snapshot() -> dict:
    """Tudo que o entalhe mostra (uma chamada so, a cada poucos segundos)."""
    return {"now": time.time(), "timers": timers(), "tasks": tasks(), "habits": habits(), "today": date.today().isoformat()}


def fmt_secs(s: int) -> str:
    s = int(s)
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if h:
        return f"{h}h{m:02d}" if m else f"{h}h"
    return (f"{m} min {sec} s" if sec else f"{m} min") if m else f"{sec} s"
