"""Tarefas, timers, lembretes, cronometro, foco (Pomodoro) e habitos: aparecem no entalhe e no app."""
import re
import time
from datetime import datetime, timedelta

from .. import gcal, rotina
from . import tool
from .agenda import _norm, parse_date, parse_time

PRIO = {"alta": "alta", "urgente": "alta", "importante": "alta", "media": "media", "normal": "media", "baixa": "baixa"}


def _secs_until(quando: str) -> int:
    """'em 30 minutos', 'daqui 2 horas', 'em 1h30', '15h', 'amanha 9h', 'sexta 14:30' -> segundos a partir de agora."""
    t = _norm(quando)
    m = re.search(r"(?:em|daqui(?: a)?|dentro de)?\s*(\d+)\s*(?:h|hora|horas)\s*(?:e\s*)?(\d+)?\s*(?:min|minuto|minutos)?", t)
    rel = re.search(r"(?:em|daqui(?: a)?|dentro de)\s+(\d+)\s*(seg|segundo|segundos|s|min|minuto|minutos|h|hora|horas)\b", t)
    if rel:
        n, u = int(rel[1]), rel[2]
        return n * (3600 if u.startswith("h") else 60 if u.startswith("m") else 1)
    if m and re.search(r"(?:em|daqui|dentro de)", t):
        return int(m[1]) * 3600 + int(m[2] or 0) * 60
    tm = parse_time(t)
    if tm is None:
        raise ValueError(f"nao entendi quando: '{quando}'. Ex.: 'em 30 minutos', 'daqui 2 horas', '15h', 'amanha 9h'")
    now = datetime.now(gcal.TZ)
    d = parse_date(t) if re.search(r"amanha|depois|segunda|terca|quarta|quinta|sexta|sabado|domingo|\d+/\d+", t) else now.date()
    when = datetime.combine(d, tm, gcal.TZ)
    if when <= now and d == now.date():
        when += timedelta(days=1)                         # "15h" ja passou hoje: amanha
    return int((when - now).total_seconds())


def _clock(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, gcal.TZ).strftime("%H:%M")


# ---------------- tarefas ----------------
@tool("Cria uma tarefa na lista de tarefas (aparece no entalhe). Use para 'anota/adiciona na minha lista', "
      "'tarefa: X', 'preciso comprar cafe'. Subtarefa: passe 'de' com o titulo da tarefa principal.",
      {"titulo": {"type": "string"},
       "prioridade": {"type": "string", "enum": ["alta", "media", "baixa"], "x-optional": True},
       "prazo": {"type": "string", "x-optional": True, "description": "ex.: 'hoje', 'amanha', 'sexta'"},
       "de": {"type": "string", "x-optional": True, "description": "titulo da tarefa principal (para subtarefa)"}})
def criar_tarefa(titulo: str, prioridade: str = "media", prazo: str = "", de: str = "") -> str:
    t = rotina.add_task(titulo, PRIO.get(_norm(prioridade or ""), "media"), de or None, prazo)
    return f"Tarefa criada: {t['title']}" + (f" (prioridade {t['priority']})" if t["priority"] != "media" else "") + \
        (f", prazo {t['due']}" if t["due"] else "") + "."


@tool("Mostra a lista de tarefas (pendentes primeiro, por prioridade).",
      {"concluidas": {"type": "boolean", "x-optional": True, "description": "true para incluir as ja feitas"}})
def ver_tarefas(concluidas: bool = False) -> str:
    items = rotina.tasks(include_done=concluidas)
    if not items:
        return "A lista de tarefas esta vazia."
    by_id = {t["id"]: t for t in items}
    out = []
    for t in items:
        if t["parent"] and t["parent"] in by_id:
            continue
        out.append(f"- [{'x' if t['done'] else ' '}] {t['title']} ({t['priority']}{', ' + t['due'] if t['due'] else ''})")
        out += [f"    - [{'x' if s['done'] else ' '}] {s['title']}" for s in items if s["parent"] == t["id"]]
    return "\n".join(out)


@tool("Marca uma tarefa como feita (pelo titulo ou parte dele). desfazer=true volta para pendente.",
      {"tarefa": {"type": "string"}, "desfazer": {"type": "boolean", "x-optional": True}})
def concluir_tarefa(tarefa: str, desfazer: bool = False) -> str:
    t = rotina.find_task(tarefa)
    if not t:
        return f"Nao achei a tarefa '{tarefa}'. Tarefas: " + ", ".join(x["title"] for x in rotina.tasks()[:15])
    rotina.set_done(t["id"], not desfazer)
    return f"{'Voltou para pendente' if desfazer else 'Feito'}: {t['title']}."


@tool("Apaga uma tarefa da lista (e as subtarefas dela).", {"tarefa": {"type": "string"}})
def apagar_tarefa(tarefa: str) -> str:
    t = rotina.find_task(tarefa)
    if not t:
        return f"Nao achei a tarefa '{tarefa}'."
    rotina.delete_task(t["id"])
    return f"Tarefa apagada: {t['title']}."


# ---------------- timers ----------------
@tool("Comeca um timer (contagem regressiva) que aparece no entalhe e toca um alarme no fim. Use para "
      "'timer de 10 minutos para a pizza', 'me avisa em 5 minutos'. Varios timers podem correr juntos.",
      {"minutos": {"type": "number", "description": "duracao em minutos (pode ter fracao: 0.5 = 30 s)"},
       "nome": {"type": "string", "x-optional": True, "description": "para que e o timer (ex.: 'pizza')"}})
def criar_timer(minutos: float, nome: str = "") -> str:
    t = rotina.add_timer(float(minutos) * 60, nome, "timer")
    return f"Timer '{t['label']}' de {rotina.fmt_secs(t['ends'] - t['started'])} comecou: toca as {_clock(t['ends'])}."


@tool("Lembrete: avisa (com alarme e fala) num horario. Use para 'me lembra de ligar pro cliente em 30 minutos', "
      "'me lembra as 15h de...', 'amanha 9h me lembra de...'.",
      {"texto": {"type": "string", "description": "do que lembrar"},
       "quando": {"type": "string", "description": "'em 30 minutos', 'daqui 2 horas', '15h', 'amanha 9h'"}})
def criar_lembrete(texto: str, quando: str) -> str:
    secs = _secs_until(quando)
    t = rotina.add_timer(secs, texto, "lembrete")
    return f"Combinado: te lembro de '{t['label']}' as {_clock(t['ends'])}" + \
        (f" (daqui a {rotina.fmt_secs(secs)})." if secs < 6 * 3600 else ".")


@tool("Mostra os timers, lembretes, cronometros e sessoes de foco que estao correndo, com o tempo que falta.")
def ver_timers() -> str:
    items = [t for t in rotina.timers() if t["running"]]
    if not items:
        return "Nenhum timer correndo."
    return "\n".join(f"- {t['label']} ({t['kind']}): " + (f"faltam {rotina.fmt_secs(t['left'])}, toca as {_clock(t['ends'])}"
                     if t["ends"] else f"{rotina.fmt_secs(t['elapsed'])} contando") for t in items)


@tool("Cancela um timer, lembrete ou sessao de foco (pelo nome; vazio = o mais proximo). todos=true cancela todos.",
      {"nome": {"type": "string", "x-optional": True}, "todos": {"type": "boolean", "x-optional": True}})
def cancelar_timer(nome: str = "", todos: bool = False) -> str:
    if todos:
        items = [t for t in rotina.timers() if t["running"] and t["kind"] != "cronometro"]
        for t in items:
            rotina.stop_timer(t["id"])
        return f"{len(items)} timer(s) cancelado(s)." if items else "Nenhum timer correndo."
    t = rotina.find_timer(nome)
    if not t or t["kind"] == "cronometro":
        return f"Nao achei timer '{nome}' correndo." if nome else "Nenhum timer correndo."
    rotina.stop_timer(t["id"])
    return f"Cancelado: {t['label']}."


@tool("Cronometro (conta para cima): acao=iniciar ou parar (parar diz o tempo).",
      {"acao": {"type": "string", "enum": ["iniciar", "parar"]}, "nome": {"type": "string", "x-optional": True}})
def cronometro(acao: str, nome: str = "") -> str:
    if acao == "iniciar":
        t = rotina.start_stopwatch(nome)
        return f"Cronometro '{t['label']}' iniciado."
    items = [t for t in rotina.timers() if t["kind"] == "cronometro" and t["running"]]
    t = next((x for x in items if nome and rotina._n(nome) in rotina._n(x["label"])), None) or (items[-1] if items else None)
    if not t:
        return "Nenhum cronometro correndo."
    rotina.stop_timer(t["id"])
    return f"Cronometro '{t['label']}' parado em {rotina.fmt_secs(time.time() - t['started'])}."


@tool("Sessao de foco no estilo Pomodoro: X minutos de foco e depois uma pausa (comeca sozinha). Use para "
      "'modo foco', 'modo estudo', 'pomodoro'.",
      {"minutos": {"type": "integer", "x-optional": True, "description": "foco (padrao 25)"},
       "pausa": {"type": "integer", "x-optional": True, "description": "pausa depois (padrao 5)"},
       "tema": {"type": "string", "x-optional": True, "description": "ex.: 'estudo', 'relatorio'"}})
def iniciar_foco(minutos: int = 25, pausa: int = 5, tema: str = "") -> str:
    t = rotina.add_timer(int(minutos or 25) * 60, f"Foco: {tema}" if tema else "Foco", "foco", int(pausa if pausa is not None else 5))
    return f"Foco de {int(minutos or 25)} min comecou (ate as {_clock(t['ends'])}), depois {t['then_break']} min de pausa. Bom trabalho!"


# ---------------- habitos ----------------
@tool("Registra um habito de hoje: 'bebi um copo de agua' (habito=agua), 'li 20 paginas' (habito=leitura, "
      "quantidade=20), 'fiz exercicio'. quantidade negativa desfaz.",
      {"habito": {"type": "string"}, "quantidade": {"type": "integer", "x-optional": True}})
def marcar_habito(habito: str, quantidade: int = 1) -> str:
    h = rotina.find_habit(habito)
    if not h:
        return f"Nao tenho o habito '{habito}'. Habitos: {', '.join(x['name'] for x in rotina.habits()) or 'nenhum'}. " \
               "Posso criar com criar_habito se o usuario quiser."
    h = rotina.log_habit(h["id"], int(quantidade if quantidade is not None else 1))
    done = h["count"] >= h["target"]
    return f"{h['name']}: {h['count']}/{h['target']} {h['unit']} hoje." + (" Meta do dia batida!" if done else "")


@tool("Mostra os habitos de hoje e quanto falta para a meta de cada um.")
def ver_habitos() -> str:
    items = rotina.habits()
    if not items:
        return "Nenhum habito cadastrado."
    return "\n".join(f"- {h['name']}: {h['count']}/{h['target']} {h['unit']}" for h in items)


@tool("Cria um habito para acompanhar todo dia (ex.: 'leitura' com meta 20 paginas, 'exercicio' meta 1).",
      {"nome": {"type": "string"}, "meta": {"type": "integer"},
       "unidade": {"type": "string", "x-optional": True, "description": "ex.: 'paginas', 'copos', 'min'"}})
def criar_habito(nome: str, meta: int, unidade: str = "") -> str:
    if rotina.find_habit(nome):
        return f"O habito '{nome}' ja existe."
    h = rotina.add_habit(nome, meta, unidade)
    return f"Habito criado: {h['name']} (meta {h['target']} {h['unit']} por dia)."
