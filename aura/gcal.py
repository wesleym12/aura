"""Google Agenda: login OAuth com a SUA credencial do Google Cloud e chamadas diretas a API REST.

Fluxo (uma vez so):
1. Voce cria um "ID do cliente OAuth" (tipo Aplicativo da Web) no Google Cloud, com o endereco de
   redirecionamento http://localhost:8765/api/google/callback, e cola ID + chave secreta na tela.
2. Clica em "Conectar com o Google": o navegador vai para o Google, voce autoriza, e o Google
   devolve para a Aura um codigo que vira um "refresh token" (guardado no banco local).
Dai em diante a Aura renova o acesso sozinha. Nada passa por servidores de terceiros.
"""
import os
import secrets as _rnd
import time
import urllib.parse
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import secrets

TZ = ZoneInfo(os.getenv("TZ") or "America/Sao_Paulo")
REDIRECT = "http://localhost:8765/api/google/callback"
_G = "https://www.googleapis.com/auth/"
# permissoes pedidas por servico (so quando voce conecta aquele servico; as outras continuam valendo)
SERVICES = {
    "calendar": [_G + "calendar.events", _G + "calendar.readonly"],
    "gmail": [_G + "gmail.readonly", _G + "gmail.compose"],          # ler + rascunhar/enviar (enviar pede Autorizar)
    "drive": [_G + "drive.readonly", _G + "drive.file"],             # ler tudo; criar/apagar so o que a Aura criou
    "docs": [_G + "documents", _G + "drive.file"],
    "sheets": [_G + "spreadsheets", _G + "drive.file"],
}
# API do Google que precisa estar ativada no projeto do Google Cloud de cada servico
SERVICE_API = {"calendar": "calendar-json.googleapis.com", "gmail": "gmail.googleapis.com", "drive": "drive.googleapis.com",
               "docs": "docs.googleapis.com", "sheets": "sheets.googleapis.com"}
SCOPES = ["openid", "email", *SERVICES["calendar"]]
API = "https://www.googleapis.com/calendar/v3"

_token = {"value": "", "exp": 0.0}
_states: dict[str, float] = {}          # protecao do retorno do login (state de uso unico)


class GoogleError(ValueError):        # ValueError: o Desfazer e as rotas ja tratam como erro "normal"
    pass


# ---------------- credenciais e login ----------------
def client() -> tuple[str, str]:
    return secrets.get("google_client_id"), secrets.get("google_client_secret")


def configured() -> bool:
    cid, cs = client()
    return bool(cid and cs)


def granted() -> set[str]:
    """Permissoes que voce ja deu (logins antigos, sem esse registro, tinham so a Agenda)."""
    raw = secrets.get("google_scopes")
    return set(raw.split()) if raw else set(SERVICES["calendar"])


def has(service: str) -> bool:
    """Servico conectado = login valido + todas as permissoes dele concedidas."""
    return configured() and bool(secrets.get("google_refresh")) and set(SERVICES[service]) <= granted()


def connected() -> bool:
    return has("calendar")


def status() -> dict:
    cid, _ = client()
    logged = configured() and bool(secrets.get("google_refresh"))
    return {"configured": configured(), "connected": connected(), "logged_in": logged, "email": secrets.get("google_email") or "",
            "client_id_end": cid[-24:] if cid else "", "redirect": REDIRECT,
            "services": [s for s in SERVICES if has(s)]}


def auth_url(services: list[str] | None = None) -> str:
    """Login no Google pedindo as permissoes dos servicos escolhidos + as que voce ja deu."""
    cid, _ = client()
    if not cid:
        raise GoogleError("cole antes o ID do cliente e a chave secreta")
    want = {"openid", "email"} | (granted() if secrets.get("google_refresh") else set())
    for s in services or ["calendar"]:
        want |= set(SERVICES.get(s, []))
    state = _rnd.token_urlsafe(24)
    now = time.time()
    for k in [k for k, t in _states.items() if now - t > 900]:
        _states.pop(k, None)
    _states[state] = now
    q = {"client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": " ".join(sorted(want)),
         "access_type": "offline", "prompt": "consent", "include_granted_scopes": "true", "state": state}
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(q)


def finish(code: str, state: str) -> str:
    if not state or _states.pop(state, None) is None:
        raise GoogleError("pedido de login expirado ou invalido; tente conectar de novo")
    cid, cs = client()
    r = httpx.post("https://oauth2.googleapis.com/token", timeout=20, data={
        "code": code, "client_id": cid, "client_secret": cs, "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
    j = r.json()
    if r.status_code >= 400 or "access_token" not in j:
        raise GoogleError(j.get("error_description") or j.get("error") or f"HTTP {r.status_code}")
    if j.get("refresh_token"):
        secrets.put("google_refresh", j["refresh_token"])
    if j.get("scope"):                                  # o que voce realmente concedeu (pode desmarcar itens na tela do Google)
        secrets.put("google_scopes", j["scope"])
    _token.update(value=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    try:
        info = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", timeout=15,
                         headers={"Authorization": f"Bearer {j['access_token']}"}).json()
        secrets.put("google_email", info.get("email", ""))
    except (httpx.HTTPError, ValueError):
        pass
    return secrets.get("google_email")


def disconnect():
    tok = secrets.get("google_refresh")
    if tok:
        try:
            httpx.post("https://oauth2.googleapis.com/revoke", data={"token": tok}, timeout=10)
        except httpx.HTTPError:
            pass
    for n in ("google_refresh", "google_email", "google_scopes"):
        secrets.put(n, None)
    _token.update(value="", exp=0)


def _access() -> str:
    if _token["value"] and time.time() < _token["exp"]:
        return _token["value"]
    cid, cs = client()
    rt = secrets.get("google_refresh")
    if not (cid and cs and rt):
        raise GoogleError("Google Agenda nao conectado (Configuracoes -> Conexoes)")
    r = httpx.post("https://oauth2.googleapis.com/token", timeout=20, data={
        "client_id": cid, "client_secret": cs, "refresh_token": rt, "grant_type": "refresh_token"})
    j = r.json()
    if r.status_code >= 400:
        if j.get("error") == "invalid_grant":     # revogado ou expirou (app em modo Teste expira em 7 dias)
            secrets.put("google_refresh", None)
            raise GoogleError("o acesso ao Google expirou ou foi revogado; conecte de novo em Configuracoes -> Conexoes")
        raise GoogleError(j.get("error_description") or j.get("error") or f"HTTP {r.status_code}")
    _token.update(value=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    return _token["value"]


def api(method: str, url: str, raw: bool = False, **kw):
    """Chamada a qualquer API do Google com o login guardado (Agenda, Gmail, Drive, Docs, Sheets)."""
    r = httpx.request(method, url, timeout=30, headers={"Authorization": f"Bearer {_access()}"}, **kw)
    if r.status_code >= 400:
        try:
            err = r.json().get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except ValueError:
            msg = ""
        msg = msg or f"HTTP {r.status_code}"
        api_name = next((a for s, a in SERVICE_API.items() if a.split(".")[0] in url), "")
        if "has not been used" in msg or "is disabled" in msg or "SERVICE_DISABLED" in r.text:
            msg = (f"a API {api_name} nao esta ativada no seu projeto do Google Cloud. Ative em "
                   f"https://console.cloud.google.com/apis/library/{api_name} e tente de novo.")
        elif r.status_code == 403 and "insufficient" in msg.lower():
            msg = "falta permissao para isso: conecte esse servico em Configuracoes -> Conectores"
        raise GoogleError(msg)
    if raw:
        return r
    if r.status_code == 204 or not r.content:
        return {}
    return r.json()


def _req(method: str, path: str, **kw) -> dict:
    return api(method, API + path, **kw)


# ---------------- agenda ----------------
def calendars() -> list[dict]:
    items = _req("GET", "/users/me/calendarList", params={"minAccessRole": "reader"}).get("items", [])
    return [{"id": c["id"], "name": c.get("summaryOverride") or c.get("summary", ""), "primary": bool(c.get("primary")),
             "color": c.get("backgroundColor", ""), "selected": bool(c.get("selected", c.get("primary"))),
             "writable": c.get("accessRole") in ("owner", "writer")} for c in items]


def _parse_when(v: dict) -> tuple[datetime, bool]:
    if "dateTime" in v:
        return datetime.fromisoformat(v["dateTime"].replace("Z", "+00:00")).astimezone(TZ), False
    return datetime.combine(date.fromisoformat(v["date"]), datetime.min.time(), TZ), True


def _event_out(e: dict, cal: dict) -> dict:
    start, all_day = _parse_when(e.get("start", {}))
    end, _ = _parse_when(e.get("end", e.get("start", {})))
    return {"id": e["id"], "calendar": cal["id"], "calendar_name": cal["name"], "color": cal.get("color", ""),
            "title": e.get("summary") or "(sem título)", "start": start.isoformat(), "end": end.isoformat(),
            "all_day": all_day, "location": e.get("location", ""), "description": (e.get("description") or "")[:500],
            "link": e.get("htmlLink", ""), "meet": e.get("hangoutLink", ""), "writable": cal.get("writable", False)}


def events(start: datetime, end: datetime, limit: int = 100) -> list[dict]:
    """Eventos de todas as agendas visiveis (as marcadas no Google Agenda), em ordem."""
    out = []
    for cal in [c for c in calendars() if c["selected"]]:
        j = _req("GET", f"/calendars/{urllib.parse.quote(cal['id'], safe='')}/events", params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true",
            "orderBy": "startTime", "maxResults": limit})
        out += [_event_out(e, cal) for e in j.get("items", []) if e.get("status") != "cancelled"]
    out.sort(key=lambda e: (e["start"], not e["all_day"]))
    return out[:limit]


def day_range(d: date, days: int = 1) -> tuple[datetime, datetime]:
    s = datetime.combine(d, datetime.min.time(), TZ)
    return s, s + timedelta(days=max(1, days))


def _body(title: str, start: datetime | date, end: datetime | date, location: str = "", description: str = "") -> dict:
    def when(x):
        return {"dateTime": x.isoformat(), "timeZone": str(TZ)} if isinstance(x, datetime) else {"date": x.isoformat()}
    b = {"summary": title, "start": when(start), "end": when(end)}
    if location:
        b["location"] = location
    if description:
        b["description"] = description
    return b


def create(title: str, start: datetime | date, end: datetime | date, location: str = "", description: str = "",
           calendar: str = "primary") -> dict:
    e = _req("POST", f"/calendars/{urllib.parse.quote(calendar, safe='')}/events",
             json=_body(title, start, end, location, description))
    return _event_out(e, _cal(calendar))


def _cal(calendar: str) -> dict:
    cals = calendars()
    return next((c for c in cals if c["id"] == calendar or (calendar == "primary" and c["primary"])),
                {"id": calendar, "name": "", "writable": True})


def get(calendar: str, event_id: str) -> dict:
    return _req("GET", f"/calendars/{urllib.parse.quote(calendar, safe='')}/events/{urllib.parse.quote(event_id, safe='')}")


def patch(calendar: str, event_id: str, changes: dict) -> dict:
    return _req("PATCH", f"/calendars/{urllib.parse.quote(calendar, safe='')}/events/{urllib.parse.quote(event_id, safe='')}",
                json=changes)


def delete(calendar: str, event_id: str):
    _req("DELETE", f"/calendars/{urllib.parse.quote(calendar, safe='')}/events/{urllib.parse.quote(event_id, safe='')}")


def restore(calendar: str, raw: dict) -> dict:
    """Recria um evento apagado (para o Desfazer)."""
    keep = {k: raw[k] for k in ("summary", "start", "end", "location", "description", "recurrence", "reminders", "colorId")
            if k in raw}
    return _req("POST", f"/calendars/{urllib.parse.quote(calendar, safe='')}/events", json=keep)
