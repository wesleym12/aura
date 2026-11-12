"""Diario de acoes + Desfazer.

Toda ferramenta que MUDA algo registra aqui o que fez e como voltar atras:
  file_write   -> arquivo criado ou sobrescrito (guarda a versao anterior, se havia)
  file_move    -> movido/renomeado (volta para o lugar)
  file_delete  -> apagado (foi para a lixeira interna; volta de la)
  dir_create   -> pasta criada (remove se ainda estiver vazia)
  snapshot     -> varias mudancas de uma vez (ex.: tarefa do Codex na pasta workspace)
  note         -> anotacao salva na memoria
  settings     -> configuracoes que o assistente alterou

Seguranca: antes de desfazer, confere se o arquivo mudou DEPOIS da acao (por voce ou por outra acao).
Se mudou, nao sobrescreve sem confirmacao (Conflict).
"""
import contextvars
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from .config import DB_PATH

UNDO_DIR = DB_PATH.parent / "undo"
current_conv: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_conv", default=None)
turn_actions: contextvars.ContextVar[list | None] = contextvars.ContextVar("turn_actions", default=None)
turn_media: contextvars.ContextVar[list | None] = contextvars.ContextVar("turn_media", default=None)


def add_media(url: str):
    """Imagem para mostrar no chat junto com a resposta (ex.: print da tela)."""
    acc = turn_media.get()
    if acc is not None:
        acc.append(url)


class Conflict(Exception):
    """O alvo mudou depois da acao: desfazer exige confirmacao (force=True)."""


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    with closing(_conn()) as c, c:
        c.execute("""CREATE TABLE IF NOT EXISTS actions(
            id INTEGER PRIMARY KEY,
            created TEXT DEFAULT (datetime('now','localtime')),
            conv_id TEXT, tool TEXT NOT NULL, summary TEXT NOT NULL,
            kind TEXT NOT NULL, data TEXT NOT NULL,
            undone_at TEXT)""")


def file_hash(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_dir(action_hint: str) -> Path:
    """Pasta para guardar copias de seguranca de uma acao."""
    d = UNDO_DIR / action_hint
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_slot() -> Path:
    import uuid
    return backup_dir(uuid.uuid4().hex)


def record(tool: str, summary: str, kind: str, data: dict) -> int:
    with closing(_conn()) as c, c:
        aid = c.execute("INSERT INTO actions(conv_id, tool, summary, kind, data) VALUES (?,?,?,?,?)",
                        (current_conv.get(), tool, summary, kind, json.dumps(data, ensure_ascii=False))).lastrowid
    acc = turn_actions.get()
    if acc is not None:
        acc.append({"id": aid, "summary": summary})
    return aid


def get(aid: int) -> dict | None:
    with closing(_conn()) as c:
        r = c.execute("SELECT * FROM actions WHERE id = ?", (aid,)).fetchone()
    return dict(r) if r else None


def last_undoable(conv_id: str | None) -> dict | None:
    with closing(_conn()) as c:
        if conv_id:
            r = c.execute("SELECT * FROM actions WHERE undone_at IS NULL AND conv_id = ? ORDER BY id DESC LIMIT 1",
                          (conv_id,)).fetchone()
        else:
            r = None
        r = r or c.execute("SELECT * FROM actions WHERE undone_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    return dict(r) if r else None


# ---------- foto de uma pasta (para tarefas que mexem em varios arquivos, ex.: Codex) ----------
SNAP_LIMIT = 200 * 1024 * 1024   # acima disso nao tira foto (avisa que nao da para desfazer)
# pastas pesadas e geradas automaticamente: ficam fora da foto (os agentes quase nunca as editam)
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next", ".cache",
             ".idea", ".vs", "target", "bin", "obj"}


def _files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in filenames:
            yield Path(dirpath) / f


def _walk(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)).replace("\\", "/"): file_hash(p) for p in _files(root)}


def snapshot_before(root: Path) -> dict | None:
    root = Path(root)
    size = 0
    for p in _files(root):
        size += p.stat().st_size
        if size > SNAP_LIMIT:
            return None
    slot = new_slot()
    before = _walk(root)
    for rel in before:
        dst = slot / "antes" / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / rel, dst)
    return {"root": str(root), "slot": str(slot), "before": before}


def snapshot_after(snap: dict | None, tool: str, summary: str) -> int | None:
    if not snap:
        return None
    root, slot = Path(snap["root"]), Path(snap["slot"])
    after = _walk(root)
    before = snap["before"]
    created = [r for r in after if r not in before]
    modified = [r for r in after if r in before and after[r] != before[r]]
    deleted = [r for r in before if r not in after]
    # so guarda as copias do que mudou
    for rel in set(before) - set(modified) - set(deleted):
        (slot / "antes" / rel).unlink(missing_ok=True)
    if not (created or modified or deleted):
        shutil.rmtree(slot, ignore_errors=True)
        return None
    parts = [f"{len(x)} {n}" for x, n in ((created, "criado(s)"), (modified, "alterado(s)"), (deleted, "apagado(s)")) if x]
    return record(tool, f"{summary} ({', '.join(parts)})", "snapshot",
                  {"root": str(root), "slot": str(slot), "created": created, "restore": modified + deleted,
                   "after": {r: after[r] for r in created + modified}})


# ---------- desfazer ----------
def _check(path: Path, expected: str | None, force: bool, what: str):
    if not force and file_hash(path) != expected:
        raise Conflict(f"'{what}' foi alterado depois dessa acao. Desfazer vai sobrescrever essa mudanca.")


def _trash(p: Path, slot: Path):
    """Nunca apaga de verdade ao desfazer: guarda o que seria perdido."""
    if p.exists():
        shutil.move(str(p), str(slot / ("descartado_" + p.name)))


def _undo_file_write(d: dict, force: bool):
    p = Path(d["path"])
    _check(p, d["after_hash"], force, d["rel"])
    if d.get("backup"):
        shutil.copy2(d["backup"], p)                  # volta a versao anterior
    else:
        _trash(p, Path(d["slot"]))                    # nao existia: some (guardado no slot)
        for nd in d.get("new_dirs", []):              # pastas que a acao criou e ficaram vazias
            q = Path(nd)
            if q.is_dir() and not any(q.iterdir()):
                q.rmdir()


def _undo_file_move(d: dict, force: bool):
    src, dst = Path(d["src"]), Path(d["dst"])
    if not dst.exists():
        raise ValueError(f"'{d['dst_rel']}' nao existe mais; nao ha o que trazer de volta.")
    if src.exists():
        if not force:
            raise Conflict(f"Ja existe outro '{d['src_rel']}' no lugar original.")
        _trash(src, Path(d["slot"]))
    src.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(dst), str(src))


def _undo_file_delete(d: dict, force: bool):
    p = Path(d["path"])
    if p.exists() and not force:
        raise Conflict(f"Ja existe um novo '{d['rel']}' no lugar.")
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        _trash(p, Path(d["slot"]))
    shutil.move(d["trashed"], str(p))


def _undo_dir_create(d: dict, force: bool):
    p = Path(d["path"])
    if p.exists():
        if any(p.iterdir()):
            raise Conflict(f"A pasta '{d['rel']}' nao esta vazia; nao vou apaga-la.")
        p.rmdir()


def _undo_snapshot(d: dict, force: bool):
    root = Path(d["root"])
    if not force:
        changed = [r for r, h in d["after"].items() if file_hash(root / r) != h]
        if changed:
            raise Conflict("Arquivos mudaram depois dessa acao: " + ", ".join(changed[:5]))
    slot = Path(d["slot"])
    for rel in d["created"]:
        _trash(root / rel, slot)
    for rel in d["restore"]:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(slot / "antes" / rel, dst)


def _undo_note(d: dict, force: bool):
    from . import memory
    memory.delete(d["note_id"])


def _undo_settings(d: dict, force: bool):
    from . import settings
    if not force:
        cur = settings.get()
        drift = [k for k, v in d["new"].items() if cur.get(k) != v]
        if drift:
            raise Conflict("Essas configuracoes mudaram de novo depois: " + ", ".join(drift))
    settings.update(d["old"])


def _undo_gcal_create(d: dict, force: bool):
    from . import gcal
    try:
        gcal.delete(d["calendar"], d["id"])
    except gcal.GoogleError as e:
        if "410" not in str(e) and "deleted" not in str(e).lower():   # ja apagado = ja desfeito
            raise ValueError(str(e))


def _undo_gcal_patch(d: dict, force: bool):
    from . import gcal
    gcal.patch(d["calendar"], d["id"], d["old"])


def _undo_gcal_delete(d: dict, force: bool):
    from . import gcal
    gcal.restore(d["calendar"], d["event"])


def _undo_gmail_draft(d: dict, force: bool):
    from . import gcal
    gcal.api("DELETE", f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{d['id']}")


def _undo_gdrive_create(d: dict, force: bool):
    """Doc/planilha criado pela Aura vai para a lixeira do Drive (da para recuperar la por 30 dias)."""
    from . import gcal
    gcal.api("PATCH", f"https://www.googleapis.com/drive/v3/files/{d['id']}", json={"trashed": True})


def _undo_ha_state(d: dict, force: bool):
    """Casa inteligente: volta a 'foto' tirada antes (cena temporaria); sem ela, so liga/desliga como estava."""
    from . import homeassistant as ha
    if d.get("scene"):
        try:
            ha.call("scene", "turn_on", {"entity_id": d["scene"]})
            try:
                ha.call("scene", "delete", {"entity_id": d["scene"]})
            except ha.HAError:
                pass
            return
        except ha.HAError:
            pass                                       # o HA reiniciou e a foto sumiu: plano B
    dom, prev = d["domain"], d.get("prev", "")
    if dom in ("cover", "valve"):
        svc = f"open_{dom}" if prev == "open" else f"close_{dom}"
    else:
        svc = "turn_off" if prev in ("off", "idle", "standby", "paused") else "turn_on"
    ha.call(dom, svc, {"entity_id": d["entity_id"]})


HANDLERS = {"ha_state": _undo_ha_state,"file_write": _undo_file_write, "file_move": _undo_file_move, "file_delete": _undo_file_delete,
            "dir_create": _undo_dir_create, "snapshot": _undo_snapshot, "note": _undo_note, "settings": _undo_settings,
            "gcal_create": _undo_gcal_create, "gcal_patch": _undo_gcal_patch, "gcal_delete": _undo_gcal_delete,
            "gmail_draft": _undo_gmail_draft, "gdrive_create": _undo_gdrive_create}


def undo(aid: int, force: bool = False) -> dict:
    a = get(aid)
    if not a:
        raise KeyError("acao nao encontrada")
    if a["undone_at"]:
        return {"ok": True, "already": True, "summary": a["summary"]}
    HANDLERS[a["kind"]](json.loads(a["data"]), force)
    with closing(_conn()) as c, c:
        c.execute("UPDATE actions SET undone_at = datetime('now','localtime') WHERE id = ?", (aid,))
    return {"ok": True, "summary": a["summary"], "kind": a["kind"]}
