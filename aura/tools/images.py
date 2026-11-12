"""Habilidade de criar e editar imagens (Nano Banana). A imagem aparece no chat e fica na pasta de trabalho."""
import asyncio
import urllib.parse

from .. import actions, attachments, imagegen
from . import tool
from .files import _rel, _safe


def media_url(p) -> str:
    return "/api/workfile?p=" + urllib.parse.quote(str(p))


@tool(
    "Cria uma imagem a partir de uma descricao (Nano Banana, do Google), ou EDITA imagens existentes: passe em "
    "'editar' o caminho da imagem (anexo do usuario ou imagem criada antes, ex.: 'imagens/....png'). Escreva a "
    "descricao completa e detalhada (estilo, cores, composicao, texto que deve aparecer). A imagem aparece no chat "
    "e fica na pasta de trabalho. Pode ser desfeito.",
    {
        "descricao": {"type": "string", "description": "O que desenhar, ou o que mudar na imagem (se for edicao)"},
        "proporcao": {"type": "string", "enum": sorted(imagegen.RATIOS), "description": "Formato (padrao 1:1)", "x-optional": True},
        "editar": {"type": "string", "description": "Caminho(s) da(s) imagem(ns) a editar/usar como base, separados por virgula", "x-optional": True},
    },
    slow=True, available=imagegen.available,
)
async def criar_imagem(descricao: str, proporcao: str = "1:1", editar: str = "") -> str:
    inputs = []
    paths = [x.strip() for x in str(editar or "").split(",") if x.strip()]
    if not paths and attachments.current():
        # pediu para mexer "nessa imagem" e anexou: usa os anexos de imagem do turno
        paths = [a for a in attachments.current() if a.lower().endswith(tuple(imagegen.IMAGE_EXT))]
    for rel in paths[:3]:
        p = _safe(rel)
        if not p.is_file() or p.suffix.lower() not in imagegen.IMAGE_EXT:
            return f"Erro: '{rel}' nao e uma imagem da pasta de trabalho."
        inputs.append(p)
    try:
        dst, note = await asyncio.to_thread(imagegen.generate, descricao, proporcao or "1:1", inputs)
    except Exception as e:
        return f"Erro ao gerar a imagem: {e} Explique isso ao usuario com essas palavras, sem inventar outro motivo."
    slot = actions.new_slot()
    actions.record("criar_imagem", f"{'Editou' if inputs else 'Criou'} a imagem {_rel(dst)}", "file_write",
                   {"path": str(dst), "rel": _rel(dst), "backup": None, "slot": str(slot), "after_hash": actions.file_hash(dst)})
    actions.add_media(media_url(dst))
    return (f"Imagem {'editada' if inputs else 'criada'} e mostrada no chat: {_rel(dst)} "
            f"(para editar de novo, use editar='{_rel(dst)}'). Voce NAO ve a imagem; nao descreva detalhes que nao pediu."
            + (f" Nota do gerador: {note[:200]}" if note else ""))
