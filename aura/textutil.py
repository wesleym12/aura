"""Raciocinio privado: modelos "thinking" pensam antes de responder, e varios servidores devolvem esse
raciocinio como texto comum. Sem filtro, o assistente LE o proprio raciocinio em voz alta ("o usuario
esta cumprimentando, devo reconhecer calorosamente...") e isso vai para o historico, onde custa
contexto a cada turno. Esta funcao e o UNICO filtro, usado em todo lugar que gera texto.
"""
import re

_TAGS = r"(?:think|thinking|thought|reasoning|reflection|analysis)"
_BLOCK = re.compile(rf"<{_TAGS}\b[^>]*>.*?</{_TAGS}\s*>", re.S | re.I)
_OPEN = re.compile(rf"<{_TAGS}\b[^>]*>", re.I)
_CLOSE = re.compile(rf"</{_TAGS}\s*>", re.I)
_SPECIAL = re.compile(r"<\|begin_of_(thought|reasoning)\|>.*?<\|end_of_\1\|>|<\|channel\|>analysis.*?<\|message\|>"
                      r"|<\|(?:begin|end)_of_(?:thought|reasoning)\|>", re.S | re.I)


def strip_reasoning(text: str | None) -> str:
    if not text:
        return ""
    text = _SPECIAL.sub("", text)
    text = _BLOCK.sub("", text)
    # fechamento sem abertura (o servidor engoliu o "<think>"): tudo antes dele era raciocinio
    m = list(_CLOSE.finditer(text))
    if m:
        text = text[m[-1].end():]
    # abertura sem fechamento (resposta cortada no meio do raciocinio): descarta dali em diante
    o = _OPEN.search(text)
    if o:
        text = text[:o.start()]
    return text.strip()
