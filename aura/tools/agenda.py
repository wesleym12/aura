"""Habilidades do Google Agenda: ver, criar, alterar e apagar compromissos.

Datas aceitam o jeito de falar ("hoje", "amanha", "sexta 14h", "10/12 9:30") ou ISO ("2026-12-10 09:30"),
porque modelos pequenos erram conta de data. Criar e alterar entram no diario (botao Desfazer);
apagar pede Autorizar e tambem pode ser desfeito (o evento e recriado).
"""
import re
import unicodedata
from datetime import date, datetime, time, timedelta

from .. import actions, gcal
from . import tool

WEEKDAYS = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6,
            "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", s.replace("-feira", "")).strip()


def parse_date(s: str, today: date | None = None) -> date | None:
    t = _norm(s)
    today = today or datetime.now(gcal.TZ).date()
    if not t or t in ("hoje", "today"):
        return today
    if "depois de amanha" in t:
        return today + timedelta(days=2)
    if "amanha" in t or "tomorrow" in t:
        return today + timedelta(days=1)
    if "ontem" in t or "yesterday" in t:
        return today - timedelta(days=1)
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        return date(int(m[1]), int(m[2]), int(m[3]))
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        y = int(m[3]) + (2000 if m[3] and len(m[3]) == 2 else 0) if m[3] else today.year
        d = date(y, int(m[2]), int(m[1]))
        return d.replace(year=d.year + 1) if not m[3] and d < today - timedelta(days=30) else d
    for name, wd in WEEKDAYS.items():
        if re.search(rf"\b{name}\b", t):
            ahead = (wd - today.weekday()) % 7
            if "proxima" in t or "que vem" in t or "next" in t:
                ahead = ahead or 7
            return today + timedelta(days=ahead)
    return None


def parse_time(s: str) -> time | None:
    t = _norm(s)
    m = re.search(r"\b(\d{1,2})(?::|h)(\d{2})\b", t) or re.search(r"\b(\d{1,2})\s*h\b", t) or \
        re.search(r"(?:\s|t)(\d{1,2}):(\d{2})", t)
    if not m:
        m = re.search(r"\bas (\d{1,2})\b", t)
    if not m:
        return None
    h, mi = int(m[1]), int(m[2]) if m.lastindex and m.lastindex >= 2 and m[2] else 0
    if ("tarde" in t or "noite" in t or "pm" in t) and h < 12:
        h += 12
    return time(h % 24, mi % 60)


def parse_dt(s: str) -> tuple[datetime | date, bool]:
    """(quando, dia_inteiro)."""
    d = parse_date(s)
    if d is None:
        raise ValueError(f"nao entendi a data '{s}'. Use AAAA-MM-DD HH:MM, DD/MM HH:MM, 'amanha 14h' ou 'sexta 9:30'")
    tm = parse_time(re.sub(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}(/\d{2,4})?", " ", s))
    if tm is None:
        return d, True
    return datetime.combine(d, tm, gcal.TZ), False


def _end(fim: str, start: datetime | date, default: timedelta) -> datetime | date:
    """Fim do evento: so hora ('15h') = mesmo dia do inicio; data completa; ou inicio + duracao padrao."""
    timed = isinstance(start, datetime)
    end = None
    if fim:
        if parse_date(fim) is None and timed and parse_time(fim):
            end = datetime.combine(start.date(), parse_time(fim), gcal.TZ)
        else:
            end, _ = parse_dt(fim)
            if timed != isinstance(end, datetime):     # misturou dia inteiro com horario: ignora o fim
                end = None
    if end is None or end <= start:
        end = start + (default if timed else timedelta(days=max(1, default.days or 1)))
    return end


def _fmt(e: dict, with_day: bool = True) -> str:
    s = datetime.fromisoformat(e["start"])
    en = datetime.fromisoformat(e["end"])
    day = f"{DIAS[s.weekday()]} {s:%d/%m}" if with_day else ""
    when = "dia inteiro" if e["all_day"] else f"{s:%H:%M}-{en:%H:%M}"
    extra = f" · {e['location']}" if e["location"] else ""
    cal = "" if not e.get("calendar_name") else f" [{e['calendar_name']}]"
    return f"- {day} {when}: {e['title']}{extra}{cal} (id: {e['id']})".replace("-  ", "- ")


def _connected() -> bool:
    return gcal.connected()


def _find(evento_id: str) -> tuple[str, dict]:
    """Acha o evento em qualquer agenda visivel."""
    for cal in gcal.calendars():
        try:
            return cal["id"], gcal.get(cal["id"], evento_id)
        except gcal.GoogleError:
            continue
    raise ValueError(f"evento '{evento_id}' nao encontrado; use ver_agenda para pegar o id")


@tool(
    "Mostra os compromissos do Google Agenda. 'quando' aceita 'hoje', 'amanha', 'sexta', '10/12' ou AAAA-MM-DD; "
    "'dias' = quantos dias a partir dessa data (padrao 1; use 7 para a semana).",
    {"quando": {"type": "string", "description": "Data inicial (padrao: hoje)", "x-optional": True},
     "dias": {"type": "integer", "description": "Quantos dias mostrar (1 a 31)", "x-optional": True}},
    available=_connected,
)
def ver_agenda(quando: str = "hoje", dias: int = 1) -> str:
    d = parse_date(quando or "hoje")
    if d is None:
        return f"Nao entendi a data '{quando}'."
    dias = max(1, min(31, int(dias or 1)))
    start, end = gcal.day_range(d, dias)
    evs = gcal.events(start, end)
    span = f"{d:%d/%m}" + (f" a {(end - timedelta(days=1)):%d/%m}" if dias > 1 else "")
    if not evs:
        return f"Nenhum compromisso em {span}."
    return f"Compromissos em {span} ({len(evs)}):\n" + "\n".join(_fmt(e) for e in evs)


@tool(
    "Cria um compromisso no Google Agenda (agenda principal). 'inicio' aceita 'amanha 14h', 'sexta 9:30', "
    "'10/12 15:00' ou AAAA-MM-DD HH:MM; so a data = dia inteiro. Pode ser desfeito.",
    {"titulo": {"type": "string", "description": "Nome do compromisso"},
     "inicio": {"type": "string", "description": "Data e hora de inicio"},
     "fim": {"type": "string", "description": "Data e hora de termino (opcional)", "x-optional": True},
     "duracao_min": {"type": "integer", "description": "Duracao em minutos, se nao houver fim (padrao 60)", "x-optional": True},
     "local": {"type": "string", "x-optional": True},
     "descricao": {"type": "string", "x-optional": True}},
    available=_connected,
)
def criar_evento(titulo: str, inicio: str, fim: str = "", duracao_min: int = 60, local: str = "", descricao: str = "") -> str:
    start, all_day = parse_dt(inicio)
    end = _end(fim, start, timedelta(minutes=int(duracao_min or 60)))
    e = gcal.create(titulo.strip()[:200], start, end, local, descricao)
    quando = f"{start:%d/%m %H:%M}" if isinstance(start, datetime) else f"{start:%d/%m}"
    actions.record("criar_evento", f"Criou o evento '{e['title']}' ({quando})", "gcal_create",
                   {"calendar": e["calendar"], "id": e["id"]})
    return "Criado: " + _fmt(e)[2:]


@tool(
    "Altera um compromisso do Google Agenda (titulo, horario, local). Pegue o id com ver_agenda. Pode ser desfeito.",
    {"evento_id": {"type": "string", "description": "id do evento (aparece em ver_agenda)"},
     "titulo": {"type": "string", "x-optional": True},
     "inicio": {"type": "string", "description": "Novo inicio", "x-optional": True},
     "fim": {"type": "string", "description": "Novo fim (se mudar so o inicio, a duracao e mantida)", "x-optional": True},
     "local": {"type": "string", "x-optional": True}},
    available=_connected,
)
def alterar_evento(evento_id: str, titulo: str = "", inicio: str = "", fim: str = "", local: str = "") -> str:
    cal, old = _find(evento_id)
    changes: dict = {}
    if titulo:
        changes["summary"] = titulo
    if local:
        changes["location"] = local
    if inicio:
        start, _ = parse_dt(inicio)
        os_, _ = gcal._parse_when(old["start"])
        oe, _ = gcal._parse_when(old["end"])
        dur = oe - os_ if isinstance(start, datetime) else timedelta(days=max(1, (oe - os_).days))
        end = _end(fim, start, dur)
        b = gcal._body("", start, end)
        changes["start"], changes["end"] = b["start"], b["end"]
    if not changes:
        return "Nada para alterar."
    new = gcal.patch(cal, evento_id, changes)
    prev = {k: old[k] for k in ("summary", "location", "start", "end") if k in old and k in changes}
    if "location" in changes and "location" not in old:
        prev["location"] = ""
    actions.record("alterar_evento", f"Alterou o evento '{old.get('summary', '')}'", "gcal_patch",
                   {"calendar": cal, "id": evento_id, "old": prev})
    return "Alterado: " + _fmt(gcal._event_out(new, gcal._cal(cal)))[2:]


@tool(
    "Apaga um compromisso do Google Agenda. Pegue o id com ver_agenda. Pede autorizacao; pode ser desfeito.",
    {"evento_id": {"type": "string", "description": "id do evento (aparece em ver_agenda)"}},
    sensitive=True, available=_connected,
)
def apagar_evento(evento_id: str) -> str:
    cal, old = _find(evento_id)
    gcal.delete(cal, evento_id)
    actions.record("apagar_evento", f"Apagou o evento '{old.get('summary', '')}'", "gcal_delete",
                   {"calendar": cal, "event": old})
    return f"Apagado: {old.get('summary', '')}."
