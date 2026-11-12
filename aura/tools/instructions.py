"""Habilidades ligadas as instrucoes em markdown e as skills."""
import shutil

from .. import actions, instructions as ins
from . import tool


def _has_skills() -> bool:
    return bool(ins.skills(include_off=False))


@tool(
    "Carrega uma skill (guia sob demanda listado no seu prompt em 'Skills'). Chame ANTES de responder quando o "
    "pedido combinar com a descricao dela, e siga o que ela disser.",
    {"nome": {"type": "string", "description": "Nome da skill, exatamente como na lista"}},
    available=_has_skills,
)
def usar_skill(nome: str) -> str:
    s = ins.find_skill(nome)
    if not s:
        return f"Skill '{nome}' nao existe ou esta desligada. Disponiveis: " + ", ".join(x["name"] for x in ins.skills(False))
    _, body = ins._parse(ins.skill_source(s["id"]))
    extra = ("\n\nArquivos de apoio desta skill (leia com ler_arquivo_skill se precisar): " + ", ".join(s["files"])) if s["files"] else ""
    return f"[skill {s['name']}]\n{body.strip()[:12000]}{extra}"


@tool(
    "Le um arquivo de apoio de uma skill (modelos, exemplos, referencias que a skill citar).",
    {"nome": {"type": "string", "description": "Nome da skill"},
     "arquivo": {"type": "string", "description": "Caminho do arquivo dentro da pasta da skill"}},
    available=_has_skills,
)
def ler_arquivo_skill(nome: str, arquivo: str) -> str:
    s = ins.find_skill(nome)
    if not s:
        return f"Skill '{nome}' nao existe."
    base = ins.skill_dir(s["id"]).resolve()
    p = (base / arquivo).resolve()
    if base not in p.parents or not p.is_file():
        return f"Arquivo '{arquivo}' nao existe nessa skill."
    text = p.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= 8000 else text[:8000] + "\n[...cortado]"


@tool(
    "Anota algo permanente nos seus arquivos de memoria em markdown: 'instrucoes' (como voce deve agir: "
    "preferencias de resposta, regras), 'sobre' (fatos sobre o usuario) ou 'projeto' (instrucoes so da pasta/"
    "projeto atual, AURA.md). Use quando o usuario pedir para lembrar sempre / mudar seu comportamento. "
    "Acrescenta no fim por padrao. Pode ser desfeito.",
    {"arquivo": {"type": "string", "enum": ["instrucoes", "sobre", "projeto"]},
     "texto": {"type": "string", "description": "O que anotar (curto, em forma de item)"},
     "modo": {"type": "string", "enum": ["acrescentar", "substituir"], "x-optional": True}},
)
def anotar_instrucao(arquivo: str, texto: str, modo: str = "acrescentar") -> str:
    p = ins.project_file() if arquivo == "projeto" else ins.MD_DIR / ins.FILES[arquivo][0]
    slot = actions.new_slot()
    backup = None
    if p.is_file():
        backup = str(slot / ("antes_" + p.name))
        shutil.copy2(p, backup)
        old = p.read_text(encoding="utf-8", errors="replace")
    else:
        old = "# Instruções deste projeto\n" if arquivo == "projeto" else ""
    line = texto.strip()
    if modo == "substituir":
        new = line + "\n"
    else:
        new = old.rstrip("\n") + "\n" + (line if line.startswith(("-", "#", "*")) else f"- {line}") + "\n"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(new, encoding="utf-8")
    actions.record("anotar_instrucao", f"Anotou em {p.name}: {line[:60]}", "file_write",
                   {"path": str(p), "rel": p.name, "backup": backup, "slot": str(slot), "after_hash": actions.file_hash(p)})
    return f"Anotado em {p.name}. Vale a partir da proxima mensagem."
