from datetime import datetime

from . import tool

DIAS = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]


@tool("Retorna a data e hora atuais.")
def data_hora() -> str:
    now = datetime.now()
    return f"{DIAS[now.weekday()]}, {now:%d/%m/%Y %H:%M}"
