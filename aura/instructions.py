"""Memoria e instrucoes em markdown + skills (formato das Agent Skills do Claude).

Pasta memoria\\ (no Windows, montada em /memoria):
- INSTRUCOES.md   como o assistente deve agir (vai SEMPRE no contexto)
- SOBRE-MIM.md    o que ele deve saber sobre voce (vai SEMPRE no contexto)
- skills/<nome>/SKILL.md   conhecimento/procedimento sob demanda. Cabecalho:
      ---
      name: nome-da-skill
      description: quando usar (isto vai no contexto; o resto so quando ele chama usar_skill)
      ---
E na pasta de trabalho/projeto: AURA.md = instrucoes so daquele projeto.

Tudo e texto puro: edite no Bloco de Notas, no VS Code ou na tela (Configuracoes -> Instrucoes).
"""
import os
import re
import shutil
from pathlib import Path

from . import settings, workdir

MD_DIR = Path(os.getenv("AURA_MEMORIA", "/memoria"))
FILES = {
    "instrucoes": ("INSTRUCOES.md", "Instruções gerais",
                   "# Instruções para o assistente\n\n"
                   "<!-- Escreva aqui como ele deve agir. Isto vai em TODA conversa. Exemplos (apague o <!-- para valer):\n"
                   "- Respostas curtas; detalhe só quando eu pedir.\n- Use tópicos quando houver mais de 3 itens.\n-->\n"),
    "sobre": ("SOBRE-MIM.md", "Sobre você",
              "# Sobre mim\n\n<!-- Fatos que ele deve sempre saber: trabalho, rotina, preferências, pessoas. -->\n"),
}
PROJECT_FILE = "AURA.md"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


def _budget() -> int:
    """Quanto texto de instrucoes cabe: o modelo local tem contexto pequeno."""
    from . import llm
    return 2500 if llm.current().get("local") else 12000


def init():
    MD_DIR.mkdir(parents=True, exist_ok=True)
    (MD_DIR / "skills").mkdir(exist_ok=True)
    for _, (name, _, template) in FILES.items():
        p = MD_DIR / name
        if not p.exists():
            p.write_text(template, encoding="utf-8")
    ex = MD_DIR / "skills" / "resumo-de-reuniao" / "SKILL.md"
    if not (MD_DIR / "skills").exists() or not any((MD_DIR / "skills").iterdir()):
        ex.parent.mkdir(parents=True, exist_ok=True)
        ex.write_text(
            "---\nname: resumo-de-reuniao\ndescription: Use quando o usuario pedir para resumir uma reuniao, "
            "transcricao ou anotacoes de call.\n---\n\n# Resumo de reuniao\n\nEntregue sempre nesta ordem:\n\n"
            "1. **Decisoes** tomadas (uma por linha).\n2. **Tarefas**: quem, o que e prazo.\n"
            "3. **Pendencias** e duvidas em aberto.\n4. Um paragrafo de contexto, no maximo.\n\n"
            "Nao invente nomes ou prazos que nao estejam no texto.\n", encoding="utf-8")


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


def read(key: str) -> str:
    name = FILES[key][0]
    p = MD_DIR / name
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


def write(key: str, text: str):
    MD_DIR.mkdir(parents=True, exist_ok=True)
    (MD_DIR / FILES[key][0]).write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def project_file() -> Path:
    p = workdir.current() / PROJECT_FILE
    old = workdir.current() / "JARVIS.md"                 # nome antigo: continua valendo ate ser renomeado
    return old if not p.exists() and old.exists() else p


def read_project() -> str:
    p = project_file()
    return p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""


# ---------------- skills ----------------
def _parse(md: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", md, re.S)
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip().lower()] = v.strip().strip("\"'")
        md = md[m.end():]
    return meta, md


def skills(include_off: bool = True) -> list[dict]:
    out = []
    base = MD_DIR / "skills"
    if not base.is_dir():
        return out
    off = set(settings.get().get("skills_off", []))
    for d in sorted(base.iterdir(), key=lambda x: x.name.lower()):
        f = d / "SKILL.md"
        if not (d.is_dir() and f.is_file()):
            continue
        meta, body = _parse(f.read_text(encoding="utf-8", errors="replace"))
        name = meta.get("name") or d.name
        item = {"id": d.name, "name": name, "description": meta.get("description", "")[:400],
                "enabled": d.name not in off, "files": sorted(str(x.relative_to(d)) for x in d.rglob("*") if x.is_file() and x.name != "SKILL.md")[:50],
                "size": len(body)}
        if include_off or item["enabled"]:
            out.append(item)
    return out


def skill_dir(sid: str) -> Path:
    if not NAME_RE.match(sid or ""):
        raise ValueError("nome de skill invalido (use letras minusculas, numeros e hifen)")
    return MD_DIR / "skills" / sid


def skill_source(sid: str) -> str:
    f = skill_dir(sid) / "SKILL.md"
    if not f.is_file():
        raise ValueError(f"skill '{sid}' nao existe")
    return f.read_text(encoding="utf-8", errors="replace")


def save_skill(sid: str, source: str):
    d = skill_dir(sid)
    meta, _ = _parse(source)
    if not meta.get("description"):
        raise ValueError("o SKILL.md precisa do cabecalho com 'description:' (quando usar a skill)")
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(source.replace("\r\n", "\n"), encoding="utf-8")


def delete_skill(sid: str):
    d = skill_dir(sid)
    if d.is_dir():
        shutil.rmtree(d)


def find_skill(name: str) -> dict | None:
    n = (name or "").strip().lower()
    return next((s for s in skills(include_off=False) if s["id"] == n or s["name"].lower() == n), None)


# ---------------- skill automatica (por significado) ----------------
# O modelo local pequeno nem sempre lembra de chamar usar_skill. Entao comparamos o pedido com a
# descricao de cada skill (embeddings, como a memoria) e, se combinar bem, a skill ja entra no contexto.
SKILL_MATCH = 0.42
_desc_cache: dict[str, tuple[str, list[float]]] = {}


def _head(text: str) -> str:
    """So o pedido em si (antes de ':' ou do primeiro ponto): textos colados junto diluem a comparacao."""
    return re.split(r"[:\n]|(?<=[.!?])\s", text.strip(), maxsplit=1)[0][:160]


def match_skill(query: str) -> dict | None:
    from . import memory
    sk = [s for s in skills(include_off=False) if s["description"]]
    if not sk or not query.strip():
        return None
    missing = [s for s in sk if _desc_cache.get(s["id"], ("",))[0] != s["description"]]
    if missing:
        vecs = memory.embed([s["description"] for s in missing])
        if not vecs:
            return None
        for s, v in zip(missing, vecs):
            _desc_cache[s["id"]] = (s["description"], v)
    q = memory.embed([_head(query)])
    if not q:
        return None
    best, score = None, 0.0
    for s in sk:
        sim = sum(a * b for a, b in zip(q[0], _desc_cache[s["id"]][1]))
        if sim > score:
            best, score = s, sim
    return best if score >= SKILL_MATCH else None


def auto_skill_block(query: str) -> str:
    s = match_skill(query)
    if not s:
        return ""
    _, body = _parse(skill_source(s["id"]))
    return (f"\n\nSkill '{s['name']}' carregada automaticamente porque combina com o pedido (siga estas instrucoes; "
            f"nao precisa chamar usar_skill para ela):\n{_clip(body.strip(), _budget(), 'skill')}")


# ---------------- contexto para o modelo ----------------
def _clip(text: str, limit: int, label: str) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n[...{label} cortado: grande demais para o modelo atual]"


def prompt_block() -> str:
    """Trecho do prompt de sistema: instrucoes, sobre voce, projeto e a lista de skills."""
    budget = _budget()
    parts = []
    inst = _strip_comments(read("instrucoes"))
    if inst and inst != "# Instruções para o assistente":
        parts.append("Instrucoes do usuario (INSTRUCOES.md; siga sempre, acima do jeito de ser):\n" + _clip(inst, budget, "INSTRUCOES.md"))
    sobre = _strip_comments(read("sobre"))
    if sobre and sobre != "# Sobre mim":
        parts.append("Sobre o usuario (SOBRE-MIM.md):\n" + _clip(sobre, budget // 2, "SOBRE-MIM.md"))
    proj = _strip_comments(read_project())
    if proj:
        parts.append(f"Instrucoes deste projeto/pasta ({PROJECT_FILE}):\n" + _clip(proj, budget, PROJECT_FILE))
    sk = skills(include_off=False)
    if sk:
        lines = "\n".join(f"- {s['name']}: {s['description'][:200]}" for s in sk[:40])
        parts.append("Skills (guias sob demanda): quando o pedido combinar com uma delas, chame usar_skill com o nome "
                     "ANTES de responder e siga o que ela disser.\n" + lines)
    return ("\n\n" + "\n\n".join(parts)) if parts else ""
