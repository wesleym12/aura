"""Plugin de exemplo: sorteios.

Como criar um plugin:
1. Crie um arquivo .py nesta pasta (plugins/). Arquivos que comecam com "_" sao ignorados.
2. Use o decorador @tool, como abaixo. A descricao e o que a Aura le para decidir quando usar.
3. Comece uma conversa nova: a Aura carrega o plugin e passa a saber que tem essa habilidade.
   Apagou o arquivo? Na proxima conversa ele esquece.
"""
import random

from aura.tools import tool


@tool(
    "Sorteia um numero inteiro entre um minimo e um maximo (ex.: dado, sorteio, numero aleatorio).",
    {
        "minimo": {"type": "integer", "description": "Menor valor possivel"},
        "maximo": {"type": "integer", "description": "Maior valor possivel"},
    },
)
def sortear_numero(minimo: int = 1, maximo: int = 6) -> str:
    minimo, maximo = int(minimo), int(maximo)
    if minimo > maximo:
        minimo, maximo = maximo, minimo
    return f"Sorteado: {random.randint(minimo, maximo)} (entre {minimo} e {maximo})."


@tool(
    "Escolhe uma opcao aleatoria de uma lista (ex.: 'escolhe entre pizza, sushi ou hamburguer').",
    {"opcoes": {"type": "array", "items": {"type": "string"}, "description": "Lista de opcoes"}},
)
def escolher_opcao(opcoes: list) -> str:
    if not opcoes:
        return "Nenhuma opcao informada."
    return f"Escolhido: {random.choice(opcoes)}."
