"""Historico de conversas e projetos (lista lateral do Command Center), salvo no SQLite.

Projeto = nome + pasta. Conversas de um projeto trabalham na pasta dele; as demais ficam em
"Conversas" e usam a pasta de trabalho geral. Excluir um projeto nao apaga as conversas.
"""
import json
import sqlite3
import uuid
from contextlib import closing

from .config import DB_PATH
from .textutil import strip_reasoning

NOW = "datetime('now','localtime')"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


def init():
    with closing(_conn()) as c, c:
        c.executescript(
            f"""
            CREATE TABLE IF NOT EXISTS conversations(
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                created TEXT DEFAULT ({NOW}),
                updated TEXT DEFAULT ({NOW})
            );
            CREATE TABLE IF NOT EXISTS messages(
                id INTEGER PRIMARY KEY,
                conv_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL,            -- user | assistant | notice
                content TEXT NOT NULL,
                trace TEXT,                    -- JSON com as ferramentas usadas
                created TEXT DEFAULT ({NOW})
            );
            CREATE INDEX IF NOT EXISTS messages_conv ON messages(conv_id, id);
            CREATE TABLE IF NOT EXISTS projects(
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                folder TEXT NOT NULL,          -- caminho no container (/host/...)
                created TEXT DEFAULT ({NOW})
            );
            CREATE TABLE IF NOT EXISTS sections(   -- secoes da lateral para agrupar projetos
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                pos INTEGER DEFAULT 0,
                created TEXT DEFAULT ({NOW})
            );
            """
        )
        cols = {r["name"] for r in c.execute("PRAGMA table_info(conversations)")}
        if "project_id" not in cols:
            c.execute("ALTER TABLE conversations ADD COLUMN project_id TEXT")
        if "model" not in cols:                       # modelo/IA escolhido nesta conversa ("" = padrao do Motor)
            c.execute("ALTER TABLE conversations ADD COLUMN model TEXT DEFAULT ''")
        pcols = {r["name"] for r in c.execute("PRAGMA table_info(projects)")}
        if "section_id" not in pcols:
            c.execute("ALTER TABLE projects ADD COLUMN section_id TEXT")


def _title(text: str) -> str:
    t = " ".join(text.split())
    return t if len(t) <= 60 else t[:57].rstrip() + "..."


def add(conv_id: str, role: str, content: str, trace: list | None = None, first_text: str | None = None,
        project_id: str | None = None):
    if role == "assistant":
        content = strip_reasoning(content)      # raciocinio nunca entra no historico (custaria contexto depois)
    with closing(_conn()) as c, c:
        c.execute(
            "INSERT OR IGNORE INTO conversations(id, title, project_id) VALUES (?, ?, ?)",
            (conv_id, _title(first_text or content), project_id),
        )
        c.execute(
            "INSERT INTO messages(conv_id, role, content, trace) VALUES (?,?,?,?)",
            (conv_id, role, content, json.dumps(trace) if trace else None),
        )
        c.execute(f"UPDATE conversations SET updated = {NOW} WHERE id = ?", (conv_id,))


def list_all(limit: int = 500) -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute(
            "SELECT id, title, created, updated, project_id, model FROM conversations ORDER BY updated DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get(conv_id: str) -> dict | None:
    with closing(_conn()) as c:
        r = c.execute("SELECT id, title, project_id, model FROM conversations WHERE id = ?", (conv_id,)).fetchone()
    return dict(r) if r else None


def set_model(conv_id: str, choice: str):
    with closing(_conn()) as c, c:
        c.execute("UPDATE conversations SET model = ? WHERE id = ?", (choice or "", conv_id))


def messages(conv_id: str) -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute(
            "SELECT role, content, trace, created FROM messages WHERE conv_id = ? ORDER BY id", (conv_id,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["trace"] = json.loads(d["trace"]) if d["trace"] else []
        out.append(d)
    return out


def delete(conv_id: str):
    with closing(_conn()) as c, c:
        c.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))


def rename(conv_id: str, title: str):
    with closing(_conn()) as c, c:
        c.execute("UPDATE conversations SET title = ? WHERE id = ?", (_title(title), conv_id))


def move(conv_id: str, project_id: str | None):
    with closing(_conn()) as c, c:
        c.execute("UPDATE conversations SET project_id = ? WHERE id = ?", (project_id, conv_id))


# ---------- projetos ----------
def projects() -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute(
            """SELECT p.id, p.name, p.folder, p.created, p.section_id,
                      (SELECT max(updated) FROM conversations WHERE project_id = p.id) AS last_used
               FROM projects p ORDER BY lower(p.name)""").fetchall()
    return [dict(r) for r in rows]


def project(pid: str | None) -> dict | None:
    if not pid:
        return None
    with closing(_conn()) as c:
        r = c.execute("SELECT id, name, folder, section_id FROM projects WHERE id = ?", (pid,)).fetchone()
    return dict(r) if r else None


def create_project(name: str, folder: str) -> dict:
    pid = uuid.uuid4().hex[:12]
    with closing(_conn()) as c, c:
        c.execute("INSERT INTO projects(id, name, folder) VALUES (?, ?, ?)", (pid, name.strip()[:60], folder))
    return project(pid)


def update_project(pid: str, name: str | None = None, folder: str | None = None, section_id=...) -> dict | None:
    with closing(_conn()) as c, c:
        if section_id is not ...:                       # None = tira da secao
            c.execute("UPDATE projects SET section_id = ? WHERE id = ?", (section_id or None, pid))
        if name is not None:
            c.execute("UPDATE projects SET name = ? WHERE id = ?", (name.strip()[:60], pid))
        if folder is not None:
            c.execute("UPDATE projects SET folder = ? WHERE id = ?", (folder, pid))
    return project(pid)


def delete_project(pid: str):
    """Exclui o projeto; as conversas dele voltam para 'Conversas' (nao sao apagadas)."""
    with closing(_conn()) as c, c:
        c.execute("UPDATE conversations SET project_id = NULL WHERE project_id = ?", (pid,))
        c.execute("DELETE FROM projects WHERE id = ?", (pid,))


# ---------- secoes (agrupam projetos na lateral) ----------
def sections() -> list[dict]:
    with closing(_conn()) as c:
        rows = c.execute("SELECT id, name, pos FROM sections ORDER BY pos, lower(name)").fetchall()
    return [dict(r) for r in rows]


def section(sid: str | None) -> dict | None:
    if not sid:
        return None
    with closing(_conn()) as c:
        r = c.execute("SELECT id, name, pos FROM sections WHERE id = ?", (sid,)).fetchone()
    return dict(r) if r else None


def create_section(name: str) -> dict:
    sid = uuid.uuid4().hex[:12]
    with closing(_conn()) as c, c:
        pos = c.execute("SELECT coalesce(max(pos), 0) + 1 FROM sections").fetchone()[0]
        c.execute("INSERT INTO sections(id, name, pos) VALUES (?, ?, ?)", (sid, name.strip()[:40], pos))
    return section(sid)


def update_section(sid: str, name: str | None = None, move: int = 0) -> dict | None:
    """Renomeia e/ou sobe (move=-1) / desce (move=1) a secao na lista."""
    with closing(_conn()) as c, c:
        if name:
            c.execute("UPDATE sections SET name = ? WHERE id = ?", (name.strip()[:40], sid))
        if move:
            order = [r[0] for r in c.execute("SELECT id FROM sections ORDER BY pos, lower(name)")]
            if sid in order:
                i = order.index(sid); j = max(0, min(len(order) - 1, i + move))
                order[i], order[j] = order[j], order[i]
                for n, x in enumerate(order):
                    c.execute("UPDATE sections SET pos = ? WHERE id = ?", (n, x))
    return section(sid)


def delete_section(sid: str):
    """Exclui so a secao: os projetos dela voltam para 'Projetos'."""
    with closing(_conn()) as c, c:
        c.execute("UPDATE projects SET section_id = NULL WHERE section_id = ?", (sid,))
        c.execute("DELETE FROM sections WHERE id = ?", (sid,))
