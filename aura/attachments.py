"""Anexos: arquivos que voce manda junto com a mensagem (clipe, arrastar ou colar).

Ficam em <pasta de trabalho>/anexos/, onde o Claude e o Codex conseguem ler. O conteudo de arquivos
de texto pequenos tambem vai direto para o modelo local; os demais vao como caminho.
"""
import contextvars
import re
import time
from pathlib import Path

from . import workdir

MAX_BYTES = 25 * 1024 * 1024
TEXT_EXT = {".txt", ".md", ".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".csv", ".html", ".css", ".sql", ".java",
            ".cs", ".go", ".rs", ".c", ".cpp", ".h", ".yml", ".yaml", ".toml", ".ini", ".xml", ".sh", ".ps1", ".bat",
            ".kt", ".php", ".rb", ".swift", ".vue", ".env.example", ".log"}
INLINE_LIMIT = 12000            # caracteres de texto anexado que vao direto para o modelo

_current: contextvars.ContextVar[list] = contextvars.ContextVar("attachments", default=[])


def folder() -> Path:
    d = workdir.current() / "anexos"
    d.mkdir(parents=True, exist_ok=True)
    return d


def safe_name(name: str) -> str:
    name = Path(name).name
    name = re.sub(r"[^\w.\- ]", "_", name).strip() or "arquivo"
    return name[:120]


def save(name: str, data: bytes) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError("arquivo maior que 25 MB")
    dst = folder() / f"{time.strftime('%Y%m%d-%H%M%S')}-{safe_name(name)}"
    dst.write_bytes(data)
    rel = str(dst.relative_to(workdir.current())).replace("\\", "/")
    return {"path": rel, "name": safe_name(name), "size": len(data), "win": workdir.to_windows(dst)}


def resolve(rel: str) -> Path | None:
    root = workdir.current()
    p = (root / rel).resolve()
    return p if p.is_file() and (root in p.parents) else None


def set_current(paths: list[str]):
    _current.set([p for p in paths if resolve(p)])


def current() -> list[str]:
    return _current.get()


def describe(paths: list[str], question: str | None = None) -> str:
    """Texto que vai junto com a mensagem: lista dos anexos + conteudo deles (ate um limite).

    Texto puro vai direto; PDF/Word/Excel/PowerPoint viram texto; imagens sao descritas por um
    modelo com visao (docreader). Assim qualquer modelo, mesmo sem visao, "le" o anexo.
    """
    if not paths:
        return ""
    from . import docreader, llm
    # o modelo local tem contexto pequeno; na nuvem cabe bem mais
    budget = INLINE_LIMIT if llm.current().get("local") else INLINE_LIMIT * 4
    lines = ["\n\n[Anexos do usuario, na pasta de trabalho:]"]
    for rel in paths:
        p = resolve(rel)
        if not p:
            continue
        is_text = p.suffix.lower() in TEXT_EXT
        kind = docreader.kind(p)
        label = "" if is_text else ", imagem" if kind == "image" else ", documento" if kind else ", binario"
        lines.append(f"- {rel} ({p.stat().st_size} bytes{label})")
        if budget <= 0 or not (is_text or kind):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace") if is_text else docreader.read(p, question)
        except Exception as e:  # arquivo corrompido, sem modelo de visao... o modelo fica sabendo
            lines.append(f"[nao consegui ler {rel}: {e}]")
            continue
        chunk = text[:budget]
        budget -= len(chunk)
        tag = "descricao da imagem" if kind == "image" else "conteudo"
        lines.append(f"<{tag} de {rel}>\n{chunk}\n</{tag}>" + ("\n[...cortado]" if len(text) > len(chunk) else ""))
    return "\n".join(lines)
