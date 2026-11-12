"""Casa inteligente pelo Home Assistant (container `homeassistant` do docker-compose).

Conexao:
- Botao Conectar: login na tela do proprio Home Assistant (fluxo OAuth dele). A Aura guarda so o
  refresh token (em secrets) e renova o acesso sozinha.
- Ou um token de longa duracao (Perfil -> Seguranca no HA), util para um HA que ja exista em outra maquina.

Seguranca:
- A Aura so enxerga os aparelhos que voce deixa marcados (Plugins -> Nativos -> Casa inteligente).
- Fechadura, alarme, portao e garagem passam pela ferramenta que pede Autorizar.
- Cada mudanca guarda uma "foto" do estado anterior (scene.create) para o Desfazer.
"""
import re
import secrets as pysecrets
import time
import unicodedata

import httpx

from . import secrets, settings

DEFAULT_URL = "http://homeassistant:8123"          # dentro do Docker
PUBLIC_URL = "http://127.0.0.1:8123"               # no navegador do Windows

# o que a Aura controla/le (o resto do HA, como sun/zone/person/update, fica de fora)
DOMAINS = {"light", "switch", "fan", "climate", "cover", "media_player", "scene", "script", "lock", "alarm_control_panel",
           "vacuum", "humidifier", "water_heater", "input_boolean", "button", "sensor", "binary_sensor", "camera",
           "select", "number", "siren", "valve", "lawn_mower"}
SECURITY_DOMAINS = {"lock", "alarm_control_panel"}
SECURITY_COVERS = {"garage", "gate", "door"}
DOMAIN_PT = {"light": "luz", "switch": "tomada/interruptor", "fan": "ventilador", "climate": "ar/clima", "cover": "cortina/portão",
             "media_player": "mídia", "scene": "cena", "script": "rotina", "lock": "fechadura", "alarm_control_panel": "alarme",
             "vacuum": "aspirador", "humidifier": "umidificador", "water_heater": "aquecedor", "input_boolean": "chave",
             "button": "botão", "sensor": "sensor", "binary_sensor": "sensor", "camera": "câmera", "select": "seleção",
             "number": "número", "siren": "sirene", "valve": "válvula", "lawn_mower": "cortador"}

_access = {"token": "", "exp": 0.0}
_oauth_states: dict[str, dict] = {}                  # state -> {client_id, redirect, t}


class HAError(ValueError):
    pass


# ---------------- configuracao e login ----------------
def base_url() -> str:
    return (settings.get().get("ha_url") or DEFAULT_URL).rstrip("/")


def public_url() -> str:
    u = base_url()
    return PUBLIC_URL if u == DEFAULT_URL else u


def configured() -> bool:
    return bool(secrets.get("ha_refresh") or secrets.get("ha_token"))


def auth_url(origin: str) -> str:
    """Tela de login do HA; volta para /api/casa/callback (mesmo endereco do client_id, como o HA exige)."""
    origin = origin.rstrip("/")
    state = pysecrets.token_urlsafe(16)
    cid, redirect = origin + "/", origin + "/api/casa/callback"
    now = time.time()
    for k in [k for k, v in _oauth_states.items() if now - v["t"] > 900]:
        _oauth_states.pop(k, None)
    _oauth_states[state] = {"client_id": cid, "redirect": redirect, "t": now}
    from urllib.parse import urlencode
    return f"{public_url()}/auth/authorize?" + urlencode({"client_id": cid, "redirect_uri": redirect, "state": state})


def finish(code: str, state: str):
    st = _oauth_states.pop(state, None)
    if not st:
        raise HAError("login expirado ou invalido; clique em Conectar de novo")
    r = httpx.post(f"{base_url()}/auth/token", data={"grant_type": "authorization_code", "code": code,
                                                    "client_id": st["client_id"]}, timeout=20)
    if r.status_code != 200:
        raise HAError(f"o Home Assistant recusou o login ({r.status_code})")
    j = r.json()
    secrets.put("ha_refresh", j["refresh_token"])
    secrets.put("ha_client_id", st["client_id"])
    secrets.put("ha_token", None)
    _access.update(token=j["access_token"], exp=time.time() + int(j.get("expires_in", 1800)) - 60)


def set_token(url: str, token: str) -> dict:
    """Token de longa duracao (e, opcionalmente, outro endereco de HA)."""
    url = (url or "").strip().rstrip("/") or DEFAULT_URL
    if not url.startswith(("http://", "https://")):
        raise HAError("o endereco precisa comecar com http:// ou https://")
    token = (token or "").strip()
    try:
        r = httpx.get(f"{url}/api/", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    except httpx.HTTPError as e:
        raise HAError(f"nao consegui falar com {url}: {e}")
    if r.status_code != 200:
        raise HAError("token recusado pelo Home Assistant" if r.status_code == 401 else f"resposta {r.status_code} de {url}")
    settings.update({"ha_url": "" if url == DEFAULT_URL else url})
    secrets.put("ha_token", token)
    secrets.put("ha_refresh", None)
    _access.update(token="", exp=0)
    return status()


def disconnect():
    for k in ("ha_refresh", "ha_client_id", "ha_token"):
        secrets.put(k, None)
    _access.update(token="", exp=0)


def _bearer() -> str:
    tok = secrets.get("ha_token")
    if tok:
        return tok
    if _access["token"] and time.time() < _access["exp"]:
        return _access["token"]
    refresh = secrets.get("ha_refresh")
    if not refresh:
        raise HAError("Casa inteligente nao conectada (Configuracoes -> Plugins -> Nativos -> Casa inteligente)")
    r = httpx.post(f"{base_url()}/auth/token", data={"grant_type": "refresh_token", "refresh_token": refresh,
                                                    "client_id": secrets.get("ha_client_id")}, timeout=15)
    if r.status_code != 200:
        raise HAError("o acesso ao Home Assistant expirou ou foi revogado; conecte de novo")
    j = r.json()
    _access.update(token=j["access_token"], exp=time.time() + int(j.get("expires_in", 1800)) - 60)
    return _access["token"]


def api(method: str, path: str, **kw):
    try:
        r = httpx.request(method, base_url() + path, headers={"Authorization": f"Bearer {_bearer()}"}, timeout=20, **kw)
    except httpx.HTTPError as e:
        raise HAError(f"Home Assistant fora do ar ({type(e).__name__}). Ele sobe junto com o Docker; aguarde ou veja: docker compose logs homeassistant")
    if r.status_code == 401:
        _access.update(token="", exp=0)
        raise HAError("acesso recusado pelo Home Assistant; conecte de novo")
    if r.status_code >= 400:
        raise HAError(f"Home Assistant respondeu {r.status_code}: {r.text[:200]}")
    return r.json() if "json" in r.headers.get("content-type", "") else r.text


def online() -> bool:
    try:
        return httpx.get(base_url() + "/manifest.json", timeout=3).status_code == 200
    except httpx.HTTPError:
        return False


# ---------------- aparelhos ----------------
def _norm(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")


def _areas() -> dict:
    tpl = "{% for s in states %}{{ s.entity_id }}|{{ area_name(s.entity_id) or '' }}\n{% endfor %}"
    try:
        txt = api("POST", "/api/template", json={"template": tpl})
    except HAError:
        return {}
    return dict(line.split("|", 1) for line in str(txt).splitlines() if "|" in line)


def is_security(e: dict) -> bool:
    d = e["entity_id"].split(".")[0]
    return d in SECURITY_DOMAINS or (d == "cover" and e.get("attributes", {}).get("device_class") in SECURITY_COVERS)


def entities(include_hidden: bool = False) -> list[dict]:
    hidden = set(settings.get().get("ha_hidden") or [])
    areas = _areas()
    out = []
    for s in api("GET", "/api/states"):
        eid = s["entity_id"]
        dom = eid.split(".")[0]
        if dom not in DOMAINS:
            continue
        a = s.get("attributes", {})
        item = {"entity_id": eid, "domain": dom, "name": a.get("friendly_name") or eid, "state": s["state"],
                "area": areas.get(eid, ""), "unit": a.get("unit_of_measurement", ""), "security": is_security(s),
                "hidden": eid in hidden, "attributes": a}
        if include_hidden or not item["hidden"]:
            out.append(item)
    return sorted(out, key=lambda x: (x["area"] or "~", x["domain"], x["name"]))


def find(query: str) -> list[dict]:
    """Acha pelo id, nome ou comodo (sem acento, palavras em qualquer ordem)."""
    items = entities()
    q = _norm(query).strip()
    exact = [e for e in items if e["entity_id"] == query.strip() or _norm(e["name"]) == q]
    if exact:
        return exact
    stop = {"a", "o", "as", "os", "da", "do", "das", "dos", "de", "na", "no", "nas", "nos", "e"}
    words = [w for w in re.split(r"[^\w]+", q) if w and w not in stop] or q.split()

    def hay(e):   # palavras do nome, comodo, id e tipo; cada palavra da busca tem que comecar uma delas
        return re.split(r"[^\w]+", _norm(f"{e['name']} {e['area']} {e['entity_id']} {DOMAIN_PT.get(e['domain'], '')}"))
    def forms(w):  # plural simples: luzes -> luz, tomadas -> tomada
        out = {w}
        if len(w) > 3 and w.endswith("es"):
            out.add(w[:-2])
        if len(w) > 3 and w.endswith("s"):
            out.add(w[:-1])
        return out
    return [e for e in items if all(any(h.startswith(f) for h in hay(e) for f in forms(w)) for w in words)]


def call(domain: str, service: str, data: dict) -> list:
    return api("POST", f"/api/services/{domain}/{service}", json=data)


def snapshot(entity_id: str) -> str:
    """Foto do estado atual (cena temporaria no HA) para o Desfazer."""
    sid = "aura_undo_" + pysecrets.token_hex(4)
    try:
        call("scene", "create", {"scene_id": sid, "snapshot_entities": [entity_id]})
        return "scene." + sid
    except HAError:
        return ""


def status() -> dict:
    ok_conf = configured()
    out = {"online": online(), "configured": ok_conf, "url": public_url(), "external": base_url() != DEFAULT_URL,
           "error": "", "count": 0, "location": ""}
    if ok_conf and out["online"]:
        try:
            cfg = api("GET", "/api/config")
            out["location"] = cfg.get("location_name", "")
            out["count"] = len(entities())
        except HAError as e:
            out["error"] = str(e)
    return out
