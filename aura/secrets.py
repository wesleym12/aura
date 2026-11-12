"""Chaves de API configuradas pela tela (OpenAI, Groq, Gemini...).

Ficam no banco da Aura, dentro do volume Docker desta maquina. Nunca voltam inteiras para o
navegador: a tela so ve se existe e os 4 ultimos caracteres.
"""
import os
import sqlite3
from contextlib import closing

from .config import DB_PATH

ENV_FALLBACK = {"gemini": "GEMINI_API_KEY", "openai": "OPENAI_API_KEY", "groq": "GROQ_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY", "mistral": "MISTRAL_API_KEY", "xai": "XAI_API_KEY",
                "openrouter": "OPENROUTER_API_KEY"}


def _conn():
    return sqlite3.connect(DB_PATH)


def init():
    with closing(_conn()) as c, c:
        c.execute("CREATE TABLE IF NOT EXISTS secrets(name TEXT PRIMARY KEY, value TEXT NOT NULL)")


def get(name: str) -> str:
    with closing(_conn()) as c:
        row = c.execute("SELECT value FROM secrets WHERE name = ?", (name,)).fetchone()
    return row[0] if row else os.getenv(ENV_FALLBACK.get(name, ""), "") or ""


def put(name: str, value: str | None):
    name = str(name)[:40]
    with closing(_conn()) as c, c:
        if value:
            c.execute("INSERT INTO secrets(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                      (name, value.strip()))
        else:
            c.execute("DELETE FROM secrets WHERE name = ?", (name,))


def masked() -> dict:
    """Para a tela: so 'configurada' e o final da chave."""
    out = {}
    for n in names():
        v = get(n)
        if v:
            out[n] = "••••" + v[-4:]
    return out


def names() -> list[str]:
    with closing(_conn()) as c:
        stored = [r[0] for r in c.execute("SELECT name FROM secrets")]
    return sorted(set(stored) | {n for n, env in ENV_FALLBACK.items() if os.getenv(env)})
