"""Ferramentas de arquivos, restritas a PASTA DE TRABALHO escolhida na tela (padrao: aura\\workspace).

Tudo que muda algo entra no diario de acoes e pode ser desfeito. Apagar nunca apaga de verdade:
o arquivo vai para a lixeira interna da Aura e volta com "Desfazer".
"""
import shutil
from pathlib import Path

from .. import actions, workdir
from . import tool


def _root() -> Path:
    return workdir.current()


def _normalize(rel: str, root: Path) -> str:
    """Conserta os erros comuns do modelo ao montar o caminho:
    - caminho completo do Windows (C:\\Users\\...\\Projetos\\x.txt) ou do container (/host/..., /workspace/...)
    - nome da propria pasta de trabalho repetido no inicio ("Projetos/hello.txt" estando em ...\\Projetos)
    """
    r = str(rel or "").strip().strip('"').strip("'")
    win = workdir.from_windows(r)
    if win is not None:
        r = str(win)
    rp = r.replace("\\", "/")
    for base in (str(root), workdir.to_windows(root).replace("\\", "/")):
        if rp.lower() == base.lower():
            return "."
        if rp.lower().startswith(base.lower().rstrip("/") + "/"):
            return rp[len(base.rstrip("/")) + 1:]
    rp = rp.lstrip("/")
    first, _, rest = rp.partition("/")
    if first and first.lower() == root.name.lower() and not (root / first).exists():
        return rest or "."
    return rp


def _safe(rel: str) -> Path:
    """Caminho dentro da pasta de trabalho (bloqueia ../ e caminhos absolutos para fora)."""
    root = _root()
    p = (root / _normalize(rel, root)).resolve()
    if p != root and root not in p.parents:
        raise ValueError("so posso mexer em arquivos dentro da pasta de trabalho")
    return p


def _rel(p: Path) -> str:
    return str(p.relative_to(_root())).replace("\\", "/") or "."


@tool(
    "Cria ou escreve um arquivo de texto na pasta de trabalho. Se o arquivo existir, substitui "
    "o conteudo (ou acrescenta no fim, com modo='acrescentar'). Pode ser desfeito.",
    {
        "caminho": {"type": "string", "description": "Caminho relativo, ex.: 'notas/compras.txt'"},
        "conteudo": {"type": "string", "description": "Texto a gravar"},
        "modo": {"type": "string", "enum": ["substituir", "acrescentar"], "x-optional": True},
    },
)
def escrever_arquivo(caminho: str, conteudo: str, modo: str = "substituir") -> str:
    p = _safe(caminho)
    slot = actions.new_slot()
    existed = p.is_file()
    backup = None
    if existed:
        backup = str(slot / ("antes_" + p.name))
        shutil.copy2(p, backup)
    new_dirs = []                                  # pastas criadas agora (o Desfazer apaga se ficarem vazias)
    d = p.parent
    while not d.exists():
        new_dirs.append(str(d))
        d = d.parent
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a" if modo == "acrescentar" else "w", encoding="utf-8") as f:
        f.write(conteudo)
    verb = "Acrescentou texto em" if modo == "acrescentar" and existed else "Alterou" if existed else "Criou"
    actions.record("escrever_arquivo", f"{verb} {_rel(p)}", "file_write",
                   {"path": str(p), "rel": _rel(p), "backup": backup, "slot": str(slot),
                    "after_hash": actions.file_hash(p), "new_dirs": new_dirs})
    return f"{verb} '{_rel(p)}' ({len(conteudo)} caracteres) em {workdir.to_windows(p)}."


@tool(
    "Move ou renomeia um arquivo ou pasta dentro da pasta de trabalho. Pode ser desfeito.",
    {
        "origem": {"type": "string", "description": "Caminho atual, relativo a pasta de trabalho"},
        "destino": {"type": "string", "description": "Novo caminho/nome, relativo a pasta de trabalho"},
    },
)
def mover_arquivo(origem: str, destino: str) -> str:
    src, dst = _safe(origem), _safe(destino)
    if not src.exists():
        return f"Erro: '{origem}' nao existe."
    if dst.is_dir():
        dst = dst / src.name
    if dst.exists():
        return f"Erro: ja existe '{_rel(dst)}'. Escolha outro nome."
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    verb = "Renomeou" if src.parent == dst.parent else "Moveu"
    actions.record("mover_arquivo", f"{verb} {_rel(src)} → {_rel(dst)}", "file_move",
                   {"src": str(src), "dst": str(dst), "src_rel": _rel(src), "dst_rel": _rel(dst),
                    "slot": str(actions.new_slot())})
    return f"{verb} '{_rel(src)}' para '{_rel(dst)}'."


@tool(
    "Apaga um arquivo ou pasta da pasta de trabalho. Vai para a lixeira da Aura e pode ser desfeito.",
    {"caminho": {"type": "string", "description": "Caminho relativo a pasta de trabalho"}},
)
def apagar_arquivo(caminho: str) -> str:
    p = _safe(caminho)
    if p == _root():
        return "Erro: nao posso apagar a pasta de trabalho inteira."
    if not p.exists():
        return f"Erro: '{caminho}' nao existe."
    slot = actions.new_slot()
    trashed = slot / ("lixeira_" + p.name)
    shutil.move(str(p), str(trashed))
    actions.record("apagar_arquivo", f"Apagou {_rel(p)}", "file_delete",
                   {"path": str(p), "rel": _rel(p), "trashed": str(trashed), "slot": str(slot)})
    return f"Apagou '{_rel(p)}' (pode ser desfeito)."


@tool(
    "Cria uma pasta na pasta de trabalho. Pode ser desfeito.",
    {"caminho": {"type": "string", "description": "Caminho relativo da nova pasta"}},
)
def criar_pasta(caminho: str) -> str:
    p = _safe(caminho)
    if p.exists():
        return f"A pasta '{_rel(p)}' ja existe."
    p.mkdir(parents=True)
    actions.record("criar_pasta", f"Criou a pasta {_rel(p)}", "dir_create", {"path": str(p), "rel": _rel(p)})
    return f"Criou a pasta '{_rel(p)}'."


@tool(
    "Lista arquivos e pastas da pasta de trabalho.",
    {"pasta": {"type": "string", "description": "Pasta relativa (padrao: raiz)", "x-optional": True}},
)
def listar_arquivos(pasta: str = ".") -> str:
    p = _safe(pasta)
    if not p.is_dir():
        return f"Erro: '{pasta}' nao e uma pasta."
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:200]
    if not items:
        return f"A pasta '{_rel(p)}' esta vazia."
    return "\n".join(f"{'[pasta] ' if x.is_dir() else ''}{_rel(x)}" + ("" if x.is_dir() else f" ({x.stat().st_size} bytes)")
                     for x in items)


@tool(
    "Le o conteudo de um arquivo de texto da pasta de trabalho.",
    {"caminho": {"type": "string", "description": "Caminho relativo a pasta de trabalho"}},
)
def ler_arquivo(caminho: str) -> str:
    p = _safe(caminho)
    if not p.is_file():
        return f"Erro: '{caminho}' nao existe."
    text = p.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= 4000 else text[:4000] + "\n[...arquivo maior, cortado]"


@tool(
    "Le documentos e imagens da pasta de trabalho: PDF (inclusive escaneado), Word (.docx), Excel (.xlsx), "
    "PowerPoint (.pptx) e imagens (.png, .jpg, .webp...). Imagens sao descritas por um modelo com visao; "
    "use 'pergunta' para perguntar algo especifico sobre a imagem.",
    {
        "caminho": {"type": "string", "description": "Caminho relativo a pasta de trabalho"},
        "pergunta": {"type": "string", "description": "O que quer saber da imagem (opcional)", "x-optional": True},
    },
)
def ler_documento(caminho: str, pergunta: str = "") -> str:
    from .. import docreader
    p = _safe(caminho)
    if not p.is_file():
        return f"Erro: '{caminho}' nao existe."
    if p.suffix.lower() not in docreader.IMAGE_EXT | docreader.DOC_EXT:
        return ler_arquivo(caminho)
    try:
        return docreader.read(p, pergunta or None)
    except Exception as e:
        return f"Erro ao ler '{caminho}': {e}"


@tool(
    "Desfaz a ultima acao que o assistente fez (arquivo criado/alterado/movido/apagado, tarefa do Codex, "
    "anotacao ou configuracao alterada). Use quando o usuario pedir para desfazer ou voltar atras.",
)
def desfazer_ultima_acao() -> str:
    a = actions.last_undoable(actions.current_conv.get())
    if not a:
        return "Nao ha nada para desfazer."
    try:
        actions.undo(a["id"])
        return f"Desfeito: {a['summary']}."
    except actions.Conflict as e:
        return f"Nao desfiz '{a['summary']}': {e} Peca para o usuario confirmar no botao Desfazer da tela."
    except (ValueError, OSError) as e:
        return f"Nao foi possivel desfazer '{a['summary']}': {e}"
