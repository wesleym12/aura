"""Pasta de trabalho ("cowork"): a pasta do seu Windows onde a Aura, o Claude e o Codex trabalham.

A pasta de usuario do Windows fica montada em /host. Dentro dela voce escolhe, pela tela, qual
pasta e a de trabalho. Tudo que mexe em arquivos (ferramentas, Claude, Codex, anexos) fica preso
dentro da pasta escolhida; pastas sensiveis (AppData, .ssh, credenciais...) nunca podem ser escolhidas.
"""
import contextvars
import os
from pathlib import Path, PurePosixPath

from .config import WORKSPACE

HOST = Path("/host")
_RAW = os.getenv("HOST_ROOT_WIN", "").strip()
# como os caminhos aparecem no computador: Windows (C:\Users\voce) ou Linux (/home/umbrel)
SEP = "/" if _RAW.startswith("/") else "\\"
HOST_WIN = _RAW.rstrip("/") if SEP == "/" else _RAW.replace("/", "\\").rstrip("\\")
BLOCKED = {"appdata", ".ssh", ".aws", ".azure", ".gnupg", ".docker", ".config", ".kube", "ntuser.dat",
           # atalhos antigos do Windows que apontam para AppData e pastas de sistema
           "application data", "local settings", "cookies", "nethood", "printhood", "recent", "sendto",
           "start menu", "templates", "my documents", "intelgraphicsprofiles"}


def _in_host(p: Path) -> bool:
    return HOST.is_dir() and (p == HOST or HOST in p.parents)


def _allowed(p: Path) -> bool:
    p = p.resolve()
    if p == WORKSPACE.resolve() or WORKSPACE.resolve() in p.parents:
        return True
    if not _in_host(p):
        return False
    return not any(part.lower() in BLOCKED for part in p.relative_to(HOST).parts)


# pasta do projeto da conversa atual (vale so dentro deste pedido; sem projeto = pasta geral)
_override: contextvars.ContextVar[str | None] = contextvars.ContextVar("workdir_override", default=None)


def use_conversation(conv_id: str | None, project_id: str | None = None):
    """Liga a pasta de trabalho ao projeto da conversa (ou ao projeto informado, numa conversa nova)."""
    from . import conversations
    conv = conversations.get(conv_id) if conv_id else None
    proj = conversations.project((conv or {}).get("project_id") or project_id)
    _override.set(proj["folder"] if proj else None)
    return proj


def current() -> Path:
    from . import settings
    over = _override.get()
    if over:
        p = Path(over)
        if p.is_dir() and _allowed(p) and p != HOST:
            return p.resolve()
    raw = settings.get().get("workdir") or str(WORKSPACE)
    p = Path(raw)
    return p.resolve() if p.is_dir() and _allowed(p) and p != HOST else WORKSPACE.resolve()


def to_windows(p: Path) -> str:
    """Como o caminho aparece no Windows (para mostrar na tela)."""
    p = Path(p)
    if _in_host(p):
        rel = str(PurePosixPath(p.relative_to(HOST))).replace("/", SEP)
        win = HOST_WIN or "pasta do usuario"
        return win + (SEP + rel if rel != "." else "")
    if p == WORKSPACE or WORKSPACE in p.parents:
        return f"aura{SEP}workspace" + (SEP + str(p.relative_to(WORKSPACE)).replace("/", SEP) if p != WORKSPACE else "")
    return str(p)


def from_windows(path: str) -> Path | None:
    """C:\\Users\\voce\\Projetos\\x.txt (ou /home/umbrel/x.txt) -> /host/... (so dentro da pasta de usuario)."""
    p = str(path or "").strip().strip('"').replace("/" if SEP == "\\" else "\\", SEP)
    w = HOST_WIN
    same = (lambda a, b: a.lower() == b.lower()) if SEP == "\\" else (lambda a, b: a == b)   # Linux diferencia maiusculas
    if w and HOST.is_dir() and (same(p, w) or same(p[:len(w) + 1], w + SEP)):
        rest = p[len(w):].lstrip(SEP)
        return HOST / PurePosixPath(*rest.split(SEP)) if rest else HOST
    return None


def validate(path: str) -> Path:
    p = Path(path).resolve()
    if not p.is_dir():
        raise ValueError("essa pasta nao existe")
    if p == HOST:
        raise ValueError("escolha uma pasta dentro dela, nao a pasta de usuario inteira")
    if not _allowed(p):
        raise ValueError("essa pasta nao pode ser usada (fora da pasta de usuario ou pasta protegida)")
    return p


def list_dirs(path: str | None) -> dict:
    """Subpastas para o navegador de pastas da tela (sem ocultas, sem as sensiveis). Sem caminho = pasta de usuario."""
    base = Path(path).resolve() if path else (HOST if HOST.is_dir() else WORKSPACE)
    if not (base == HOST or _allowed(base)):
        base = HOST if HOST.is_dir() else WORKSPACE
    items = []
    try:
        for c in sorted(base.iterdir(), key=lambda x: x.name.lower()):
            if c.is_dir() and not c.name.startswith((".", "$")) and _allowed(c):
                items.append({"path": str(c), "name": c.name})
    except (PermissionError, OSError):
        pass
    parent = str(base.parent) if base != HOST and (base.parent == HOST or _allowed(base.parent)) else None
    return {"path": str(base), "win": to_windows(base), "parent": parent,
            "dirs": items[:300], "can_use": base != HOST and _allowed(base)}


def make_dir(parent: str, name: str) -> Path:
    """Cria uma pasta nova (botao Nova pasta do seletor)."""
    import re
    name = (name or "").strip().rstrip(". ")
    if not name or name in (".", "..") or re.search(r'[\\/:*?"<>|]', name) or len(name) > 120:
        raise ValueError('nome invalido (nao use \\ / : * ? " < > |)')
    base = Path(parent).resolve()
    if not (base == HOST or _allowed(base)):
        raise ValueError("nao posso criar pasta aqui")
    p = base / name
    if not _allowed(p):
        raise ValueError("esse nome nao pode ser usado aqui")
    if p.exists():
        raise ValueError("ja existe uma pasta com esse nome")
    p.mkdir()
    return p
