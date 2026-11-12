"""Habilidades para agendar tarefas pelo chat ("todo dia as 8h me resume a agenda")."""
import re

from .. import scheduler
from . import tool
from .agenda import _norm, parse_date, parse_time

DAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}


def parse_when(quando: str) -> dict:
    """'todo dia 8h', 'segunda e quarta 9:30', 'dias uteis 7h', 'a cada 30 min', 'amanha 14h', '10/12 9h'."""
    t = _norm(quando)
    m = re.search(r"a cada (\d+)\s*(min|minuto|minutos|h|hora|horas)", t)
    if m:
        n = int(m.group(1)) * (60 if m.group(2).startswith("h") else 1)
        return {"kind": "interval", "every": n}
    tm = parse_time(t)
    hhmm = f"{tm.hour:02d}:{tm.minute:02d}" if tm else None
    if ("todo dia" in t or "todos os dias" in t or "diariamente" in t) and hhmm:
        return {"kind": "daily", "at": hhmm}
    if ("dias uteis" in t or "dia util" in t) and hhmm:
        return {"kind": "weekly", "at": hhmm, "days": [0, 1, 2, 3, 4]}
    if ("fim de semana" in t or "fins de semana" in t) and hhmm:
        return {"kind": "weekly", "at": hhmm, "days": [5, 6]}
    days = [v for k, v in DAYS.items() if re.search(rf"\b{k}", t)]
    if days and ("toda" in t or "todo" in t or "toda semana" in t or len(days) > 1) and hhmm:
        return {"kind": "weekly", "at": hhmm, "days": sorted(set(days))}
    d = parse_date(t)
    if d and hhmm:
        return {"kind": "once", "at": f"{d:%Y-%m-%d} {hhmm}"}
    raise ValueError(f"nao entendi quando: '{quando}'. Ex.: 'todo dia 8h', 'segunda e sexta 9h', 'dias uteis 7h', "
                     "'a cada 30 min', 'amanha 14h', '10/12 9h'")


@tool("Agenda uma tarefa para voce executar sozinha depois ou repetidamente (ex.: resumo diario da agenda, "
      "checar e-mails). 'quando': 'todo dia 8h', 'segunda e sexta 9h', 'dias uteis 7h', 'a cada 30 min', "
      "'amanha 14h', '10/12 9h'. 'pedido': o que fazer, escrito como se o usuario pedisse.",
      {"titulo": {"type": "string"}, "pedido": {"type": "string"}, "quando": {"type": "string"}})
def agendar_tarefa(titulo: str, pedido: str, quando: str) -> str:
    s = scheduler.save({"title": titulo, "prompt": pedido, **parse_when(quando)})
    nxt = s["next_run"][:16].replace("T", " ") if s["next_run"] else "?"
    return f"Agendado: '{s['title']}' ({s['when']}). Proxima execucao: {nxt}. Os resultados ficam na aba Agendados."


@tool("Lista as tarefas agendadas (id, titulo, quando, proxima execucao).")
def listar_agendados() -> str:
    items = scheduler.list_all()
    if not items:
        return "Nenhuma tarefa agendada."
    return "\n".join(f"- {s['title']} ({s['when']}){'' if s['enabled'] else ' [pausado]'} · proxima: "
                     f"{(s['next_run'] or '-')[:16].replace('T', ' ')} · id {s['id']}" for s in items)


@tool("Cancela (apaga) uma tarefa agendada pelo id ou titulo.", {"agendado": {"type": "string"}}, sensitive=True)
def cancelar_agendado(agendado: str) -> str:
    a = agendado.strip().lower()
    s = next((x for x in scheduler.list_all() if x["id"] == a or x["title"].lower() == a), None) or \
        next((x for x in scheduler.list_all() if a in x["title"].lower()), None)
    if not s:
        return f"Nao achei o agendamento '{agendado}'."
    scheduler.delete(s["id"])
    return f"Agendamento '{s['title']}' cancelado."
