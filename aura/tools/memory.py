from .. import actions, memory
from . import tool


@tool(
    "Salva uma anotacao na memoria permanente da Aura (ideias, decisoes, lembretes, resultados de pesquisa).",
    {
        "titulo": {"type": "string", "description": "Titulo curto"},
        "conteudo": {"type": "string", "description": "Texto completo a guardar"},
    },
)
def lembrar(titulo: str, conteudo: str) -> str:
    nid = memory.save("nota", titulo, conteudo, actions.current_conv.get())
    actions.record("lembrar", f"Anotou: {titulo[:60]}", "note", {"note_id": nid})
    return f"Anotado (#{nid})."


@tool(
    "Busca na memoria da Aura por significado: fatos sobre o usuario, anotacoes e resultados de pesquisas "
    "anteriores do Claude e do Codex. Use quando o que voce ja sabe (no prompt) nao bastar.",
    {"consulta": {"type": "string", "description": "O que procurar, em palavras naturais"}},
)
def buscar_memoria(consulta: str) -> str:
    hits = memory.search(consulta, limit=6, min_score=0.3)
    if not hits:
        return "Nada encontrado na memoria."
    return "\n\n".join(
        f"#{h['id']} [{h['kind']}] {h['created']} - {h['title']}\n{h['content'][:1500]}" for h in hits
    )
