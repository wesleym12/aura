"""Backup automatico do banco da Aura (conversas, projetos, memoria, configuracoes, diario de acoes, chaves).

- Ao ligar e a cada 6 horas, so se algo mudou desde o ultimo backup.
- Fica em aura\\backups no Windows (fora do volume Docker): sobrevive mesmo se o volume for apagado.
- Mantem os 20 mais recentes. Restaurar faz antes um backup do estado atual (da para voltar atras).
Usa a API de backup do SQLite, que copia com o banco em uso sem corromper nada.
"""
import hashlib
import logging
import os
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from .config import DB_PATH

log = logging.getLogger("uvicorn.error")
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "/backups"))
KEEP = int(os.getenv("BACKUP_KEEP", "20"))
INTERVAL = float(os.getenv("BACKUP_HOURS", "6")) * 3600
_lock = threading.Lock()


def _md5(p: Path) -> str:
    h = hashlib.md5()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _counts(p: Path) -> dict:
    out = {}
    try:
        with closing(sqlite3.connect(f"file:{p}?mode=ro", uri=True)) as c:
            for table, key in (("conversations", "conversas"), ("messages", "mensagens"), ("notes", "memorias"), ("projects", "projetos")):
                try:
                    out[key] = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                except sqlite3.Error:
                    out[key] = 0
    except sqlite3.Error:
        pass
    return out


def _copy(src: Path, dst: Path):
    with closing(sqlite3.connect(src)) as a, closing(sqlite3.connect(dst)) as b:
        a.backup(b)


def list_backups() -> list[dict]:
    if not BACKUP_DIR.is_dir():
        return []
    items = []
    for p in sorted(BACKUP_DIR.glob("aura-*.db"), reverse=True):
        st = p.stat()
        items.append({"name": p.name, "size": st.st_size,
                      "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
                      "reason": p.stem.split("-", 3)[-1] if p.stem.count("-") >= 3 else "", **_counts(p)})
    return items


def make(reason: str = "manual", force: bool = False) -> dict | None:
    """Faz um backup. Sem force, descarta se nada mudou desde o ultimo."""
    with _lock:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        dst = BACKUP_DIR / f"aura-{time.strftime('%Y%m%d-%H%M%S')}-{reason}.db"
        _copy(DB_PATH, dst)
        older = [p for p in sorted(BACKUP_DIR.glob("aura-*.db"), reverse=True) if p != dst]
        if not force and older and _md5(older[0]) == _md5(dst):
            dst.unlink()
            return None
        for old in sorted(BACKUP_DIR.glob("aura-*.db"), reverse=True)[KEEP:]:
            old.unlink(missing_ok=True)
        log.info("Backup feito: %s", dst.name)
        return {"name": dst.name, **_counts(dst)}


def restore(name: str) -> dict:
    src = BACKUP_DIR / Path(name).name
    if not src.is_file() or not src.name.startswith("aura-"):
        raise ValueError("backup nao encontrado")
    safety = make("antes-de-restaurar", force=True)       # da para desfazer a restauracao
    with _lock:
        _copy(src, DB_PATH)
    log.info("Restaurado: %s (estado anterior salvo em %s)", src.name, safety and safety["name"])
    return {"restored": src.name, "safety": safety and safety["name"], **_counts(DB_PATH)}


def remove(name: str):
    """Apaga um backup (so arquivos aura-*.db da pasta de backups)."""
    p = BACKUP_DIR / Path(name).name
    if not p.is_file() or not p.name.startswith("aura-") or p.suffix != ".db":
        raise ValueError("backup nao encontrado")
    with _lock:
        p.unlink()
    log.info("Backup apagado: %s", p.name)


def _loop():
    time.sleep(20)                                       # deixa a Aura terminar de ligar
    while True:
        try:
            make("auto")
        except Exception as e:
            log.warning("Backup automatico falhou: %s", e)
        time.sleep(INTERVAL)


def start():
    threading.Thread(target=_loop, daemon=True).start()
