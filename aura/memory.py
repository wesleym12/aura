"""Memoria central da Aura.

Tipos (kind):
  fato   -> algo duradouro sobre o usuario, aprendido sozinho nas conversas ("Wesley torce para o Flamengo")
  nota   -> o que o usuario pediu para anotar (ferramenta `lembrar`)
  claude / codex -> resultados de pesquisas e tarefas delegadas

Busca hibrida: por significado (embeddings) + por palavra (SQLite FTS5). Os embeddings vem do Ollama local
(modelo multilingue) ou, na instalacao "so Gemini" (sem Ollama), do Gemini. Sem nenhum dos dois, fica so a busca
por palavra. Sem limite de tamanho: so o que e relevante para a pergunta entra no prompt; o resto fica consultavel.
"""
import array
import logging
import math
import os
import sqlite3
import threading
from contextlib import closing

import httpx

from .config import DB_PATH, LOCAL_LLM, OLLAMA_URL

log = logging.getLogger("uvicorn.error")
EMBED_MODEL = os.getenv("EMBED_MODEL", "paraphrase-multilingual")
GEMINI_EMBED = "gemini-embedding-001"
PROVIDER = "ollama" if LOCAL_LLM else "gemini"
EMBED_ID = f"ollama:{EMBED_MODEL}" if PROVIDER == "ollama" else f"gemini:{GEMINI_EMBED}:768"
# cortes de similaridade: cada modelo tem a sua escala (calibrados com perguntas reais em portugues)
CUTS = {"ollama": {"recall": 0.24, "list": 0.25, "search": 0.30, "dup": 0.86, "skill": 0.42},
        # Gemini: escala bem mais alta e mais separada (medido: relacionadas 0,77-0,82; ruido ate 0,74;
        # duplicatas 0,99 x parecidas-mas-diferentes ate 0,94; skill certa 0,85-0,86 x errada ate 0,75)
        "gemini": {"recall": 0.755, "list": 0.755, "search": 0.76, "dup": 0.97, "skill": 0.80}}[PROVIDER]
_warned = {"t": 0.0}
KINDS = {"fato": "Fatos sobre você", "nota": "Anotações", "claude": "Pesquisas (Claude)", "codex": "Tarefas (Codex)"}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with closing(_conn()) as c, c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes(
                id INTEGER PRIMARY KEY,
                created TEXT DEFAULT (datetime('now','localtime')),
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
                title, content, content='notes', content_rowid='id'
            );
            CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
                INSERT INTO notes_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
            END;
            CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
                INSERT INTO notes_fts(notes_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
            END;
            """
        )
        cols = {r["name"] for r in c.execute("PRAGMA table_info(notes)")}
        if "embedding" not in cols:
            c.execute("ALTER TABLE notes ADD COLUMN embedding BLOB")
        if "conv_id" not in cols:
            c.execute("ALTER TABLE notes ADD COLUMN conv_id TEXT")    # conversa onde foi aprendido
        # trocou o gerador de embeddings (ex.: local -> so Gemini)? os vetores antigos nao servem: refaz todos
        c.execute("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT)")
        old = c.execute("SELECT value FROM meta WHERE key = 'embed_id'").fetchone()
        if not old or old[0] != EMBED_ID:
            c.execute("UPDATE notes SET embedding = NULL")
            c.execute("INSERT OR REPLACE INTO meta(key, value) VALUES ('embed_id', ?)", (EMBED_ID,))
    threading.Thread(target=backfill, daemon=True).start()


# ---------- embeddings ----------
def _ollama(texts: list[str]) -> list[list[float]]:
    r = httpx.post(f"{OLLAMA_URL}/api/embed", json={"model": EMBED_MODEL, "input": texts}, timeout=60)
    r.raise_for_status()
    return r.json()["embeddings"]


def _gemini(texts: list[str]) -> list[list[float]] | None:
    from . import secrets
    key = secrets.get("gemini")
    if not key:
        return None                                   # sem chave: so a busca por palavra
    out = []
    for i in range(0, len(texts), 100):               # ate 100 por pedido
        r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_EMBED}:batchEmbedContents",
                       headers={"x-goog-api-key": key}, timeout=60,
                       json={"requests": [{"model": f"models/{GEMINI_EMBED}", "content": {"parts": [{"text": t}]},
                                           "taskType": "SEMANTIC_SIMILARITY", "outputDimensionality": 768}
                                          for t in texts[i:i + 100]]})
        r.raise_for_status()
        out += [e["values"] for e in r.json()["embeddings"]]
    return out


def embed(texts: list[str]) -> list[list[float]] | None:
    """Vetores normalizados (produto escalar = similaridade). None se o gerador nao responder (a busca segue
    so por palavra)."""
    import time
    try:
        vecs = _ollama(texts) if PROVIDER == "ollama" else _gemini(texts)
        if vecs is None:
            return None
        out = []
        for v in vecs:
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out
    except Exception as e:
        if time.time() - _warned["t"] > 300:          # avisa no log no maximo a cada 5 min
            _warned["t"] = time.time()
            log.warning("Embeddings indisponiveis (%s): %s", PROVIDER, e)
        return None


def _pack(v: list[float]) -> bytes:
    return array.array("f", v).tobytes()


def _unpack(b: bytes) -> array.array:
    a = array.array("f"); a.frombytes(b)
    return a


def _doc(title: str, content: str) -> str:
    return title if content.startswith(title) else f"{title}\n{content}"[:1500]


def backfill():
    """Gera embeddings que faltam (memorias antigas ou salvas com o Ollama fora do ar)."""
    with closing(_conn()) as c:
        rows = c.execute("SELECT id, title, content FROM notes WHERE embedding IS NULL").fetchall()
    for i in range(0, len(rows), 16):
        batch = rows[i:i + 16]
        vecs = embed([_doc(r["title"], r["content"]) for r in batch])
        if not vecs:
            return
        with closing(_conn()) as c, c:
            for r, v in zip(batch, vecs):
                c.execute("UPDATE notes SET embedding = ? WHERE id = ?", (_pack(v), r["id"]))


# ---------- gravar / apagar ----------
def save(kind: str, title: str, content: str, conv_id: str | None = None) -> int:
    vec = embed([_doc(title, content)])
    with closing(_conn()) as c, c:
        cur = c.execute("INSERT INTO notes(kind, title, content, conv_id, embedding) VALUES (?,?,?,?,?)",
                        (kind, title, content, conv_id, _pack(vec[0]) if vec else None))
        return cur.lastrowid


def delete(note_id: int) -> bool:
    with closing(_conn()) as c, c:
        return c.execute("DELETE FROM notes WHERE id = ?", (note_id,)).rowcount > 0


def delete_kind(kind: str) -> int:
    with closing(_conn()) as c, c:
        return c.execute("DELETE FROM notes WHERE kind = ?", (kind,)).rowcount


# ---------- buscar ----------
def _fts(query: str, limit: int) -> dict[int, float]:
    words = [w for w in "".join(ch if ch.isalnum() else " " for ch in query).split() if len(w) > 2]
    if not words:
        return {}
    terms = " OR ".join(f'"{w}"' for w in words)
    with closing(_conn()) as c:
        rows = c.execute("SELECT rowid FROM notes_fts WHERE notes_fts MATCH ? ORDER BY rank LIMIT ?",
                         (terms, limit)).fetchall()
    # quanto mais no topo do FTS, maior o bonus
    return {r[0]: 0.08 * (1 - i / max(1, len(rows))) for i, r in enumerate(rows)}


def search(query: str, limit: int = 5, kinds: tuple[str, ...] | None = None, min_score: float = 0.0) -> list[dict]:
    """Busca hibrida. Cada resultado traz 'score' (similaridade + bonus de palavra)."""
    if not query.strip():
        return []
    qv = embed([query])
    bonus = _fts(query, 50)
    where, args = ("WHERE kind IN (%s)" % ",".join("?" * len(kinds)), list(kinds)) if kinds else ("", [])
    with closing(_conn()) as c:
        rows = c.execute(f"SELECT id, created, kind, title, content, conv_id, embedding FROM notes {where}", args).fetchall()
    scored = []
    for r in rows:
        sim = 0.0
        if qv and r["embedding"]:
            sim = sum(a * b for a, b in zip(qv[0], _unpack(r["embedding"])))
        score = sim + bonus.get(r["id"], 0.0)
        if not qv and r["id"] not in bonus:
            continue
        if score >= min_score:
            d = {k: r[k] for k in ("id", "created", "kind", "title", "content", "conv_id")}
            d["score"] = round(score, 3)
            scored.append(d)
    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:limit]


def recall(query: str, k: int = 5, min_score: float | None = None) -> list[dict]:
    """O que entra no prompt para esta pergunta: so as memorias relacionadas.
    Corte calibrado por modelo (CUTS): acima dele ficam as perguntas relacionadas, abaixo o ruido.
    Um item a mais no prompt custa pouco; esquecer algo custa mais."""
    return search(query, k, min_score=CUTS["recall"] if min_score is None else min_score)


def is_duplicate(text: str, kind: str = "fato", threshold: float | None = None) -> bool:
    hits = search(text, 1, kinds=(kind,))
    return bool(hits) and hits[0]["score"] >= (CUTS["dup"] if threshold is None else threshold)


def list_items(kind: str | None = None, q: str | None = None, limit: int = 500) -> list[dict]:
    if q and q.strip():
        return search(q, limit, kinds=(kind,) if kind else None, min_score=CUTS["list"])
    where, args = ("WHERE kind = ?", [kind]) if kind else ("", [])
    with closing(_conn()) as c:
        rows = c.execute(f"SELECT id, created, kind, title, content, conv_id FROM notes {where} ORDER BY id DESC LIMIT ?",
                         args + [limit]).fetchall()
    return [dict(r) for r in rows]


def count(kind: str | None = None) -> int:
    with closing(_conn()) as c:
        if kind:
            return c.execute("SELECT count(*) FROM notes WHERE kind = ?", (kind,)).fetchone()[0]
        return c.execute("SELECT count(*) FROM notes").fetchone()[0]


def counts() -> dict:
    with closing(_conn()) as c:
        return {r[0]: r[1] for r in c.execute("SELECT kind, count(*) FROM notes GROUP BY kind")}


def recent(limit: int = 20) -> list[dict]:
    return [dict(d, content=d["content"][:300]) for d in list_items(limit=limit)]
