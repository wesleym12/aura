"""Spotify pela API oficial (precisa de Spotify Premium para controlar o que toca).

Login: voce cria um app gratis em developer.spotify.com, cola o Client ID e entra com a sua conta (OAuth com
PKCE: nao precisa de segredo). A A.U.R.A. guarda so o refresh token (em secrets) e renova o acesso sozinha.
Ela toca em qualquer aparelho seu com Spotify aberto (PC, celular, Echo...); se nenhum estiver ativo e o
controle do computador estiver ligado, abre o Spotify do PC e toca nele.
"""
import base64
import hashlib
import secrets as pysecrets
import time
import unicodedata
from urllib.parse import urlencode

import httpx

from . import secrets

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
# o Spotify so aceita http em endereco de loopback por IP (127.0.0.1, nunca "localhost") ou HTTPS. Num servidor
# (umbrelOS) o endereco publico vem de AURA_PUBLIC_URL (ex.: https://umbrel.local:8765), ja em HTTPS.
import os as _os
REDIRECT = (_os.getenv("AURA_PUBLIC_URL", "").rstrip("/") or "http://127.0.0.1:8765") + "/api/spotify/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
          "playlist-read-private playlist-read-collaborative user-library-read user-read-private")

_access = {"token": "", "exp": 0.0}
_pending: dict[str, dict] = {}            # state -> {verifier, t}


class SpotifyError(ValueError):
    pass


# ---------------- login ----------------
def client_id() -> str:
    return secrets.get("spotify_client_id")


def configured() -> bool:
    return bool(secrets.get("spotify_refresh"))


def set_client(cid: str):
    cid = (cid or "").strip()
    if not cid or len(cid) != 32 or not cid.isalnum():
        raise SpotifyError("o Client ID tem 32 letras e numeros (copie em developer.spotify.com -> seu app -> Settings)")
    secrets.put("spotify_client_id", cid)


def auth_url(back: str = "") -> str:
    if not client_id():
        raise SpotifyError("cole primeiro o Client ID do seu app do Spotify")
    verifier = pysecrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = pysecrets.token_urlsafe(16)
    now = time.time()
    for k in [k for k, v in _pending.items() if now - v["t"] > 900]:
        _pending.pop(k, None)
    _pending[state] = {"verifier": verifier, "t": now, "back": back}
    return f"{ACCOUNTS}/authorize?" + urlencode({
        "client_id": client_id(), "response_type": "code", "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge, "state": state})


def _token(data: dict) -> dict:
    r = httpx.post(f"{ACCOUNTS}/api/token", data={**data, "client_id": client_id()}, timeout=20)
    if r.status_code != 200:
        raise SpotifyError(f"o Spotify recusou o login ({r.status_code}): {r.text[:150]}")
    j = r.json()
    _access.update(token=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 60)
    if j.get("refresh_token"):
        secrets.put("spotify_refresh", j["refresh_token"])
    return j


def back_for(state: str) -> str:
    """Endereco da pagina que iniciou o login (localhost ou 127.0.0.1), para voltar para a mesma aba."""
    return (_pending.get(state) or {}).get("back", "")


def finish(code: str, state: str):
    p = _pending.pop(state, None)
    if not p:
        raise SpotifyError("login expirado ou invalido; clique em Conectar de novo")
    _token({"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT, "code_verifier": p["verifier"]})


def disconnect():
    secrets.put("spotify_refresh", None)
    _access.update(token="", exp=0)


def _bearer() -> str:
    if _access["token"] and time.time() < _access["exp"]:
        return _access["token"]
    refresh = secrets.get("spotify_refresh")
    if not refresh:
        raise SpotifyError("Spotify nao conectado (Configuracoes -> Plugins -> Nativos -> Spotify)")
    _token({"grant_type": "refresh_token", "refresh_token": refresh})
    return _access["token"]


def api(method: str, path: str, **kw):
    try:
        r = httpx.request(method, API + path, headers={"Authorization": f"Bearer {_bearer()}"}, timeout=15, **kw)
    except httpx.HTTPError as e:
        raise SpotifyError(f"sem conexao com o Spotify ({type(e).__name__})")
    if r.status_code == 401:
        _access.update(token="", exp=0)
        raise SpotifyError("acesso ao Spotify expirou; conecte de novo")
    if r.status_code == 403 and "PREMIUM" in r.text.upper():
        raise SpotifyError("controlar o que toca exige Spotify Premium")
    if r.status_code == 404 and "/me/player" in path:
        raise SpotifyError("NO_DEVICE")
    if r.status_code >= 400:
        try:
            msg = r.json().get("error", {}).get("message", r.text)
        except ValueError:
            msg = r.text
        raise SpotifyError(f"Spotify respondeu {r.status_code}: {str(msg)[:150]}")
    return r.json() if r.content and "json" in r.headers.get("content-type", "") else {}


# ---------------- busca ----------------
def norm(s: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                            if unicodedata.category(c) != "Mn").split())


def my_playlists() -> list[dict]:
    out, url = [], "/me/playlists?limit=50"
    for _ in range(6):                                    # ate 300 playlists
        j = api("GET", url)
        out += [p for p in j.get("items", []) if p]
        nxt = j.get("next")
        if not nxt:
            break
        url = nxt.replace(API, "")
    return out


def find_playlist(name: str) -> dict | None:
    """Playlist SUA com esse nome (exato, depois 'comeca com', depois 'contem')."""
    q = norm(name)
    items = my_playlists()
    for test in (lambda n: n == q, lambda n: n.startswith(q), lambda n: q in n):
        hits = [p for p in items if test(norm(p.get("name", "")))]
        if hits:
            return hits[0]
    return None


def search(q: str, kind: str) -> dict | None:
    j = api("GET", "/search", params={"q": q, "type": kind, "limit": 1, "market": "from_token"})
    items = (j.get(kind + "s") or {}).get("items") or []
    return items[0] if items and items[0] else None


# ---------------- aparelhos e reproducao ----------------
def devices() -> list[dict]:
    return api("GET", "/me/player/devices").get("devices", [])


def pick_device() -> dict | None:
    ds = devices()
    return next((d for d in ds if d.get("is_active")), None) or \
        next((d for d in ds if d.get("type") == "Computer"), None) or (ds[0] if ds else None)


def play(device_id: str | None, context_uri: str | None = None, uris: list | None = None):
    body = {"context_uri": context_uri} if context_uri else ({"uris": uris} if uris else {})
    api("PUT", "/me/player/play", params={"device_id": device_id} if device_id else None, json=body)


def now_playing() -> dict | None:
    j = api("GET", "/me/player")
    return j or None


def me() -> dict:
    return api("GET", "/me")


def status() -> dict:
    out = {"client_id": bool(client_id()), "configured": configured(), "redirect": REDIRECT,
           "user": "", "premium": None, "devices": [], "error": ""}
    if out["configured"]:
        try:
            u = me()
            out.update(user=u.get("display_name") or u.get("id", ""), premium=u.get("product") == "premium")
            out["devices"] = [{"name": d["name"], "type": d["type"], "active": d["is_active"]} for d in devices()]
        except SpotifyError as e:
            out["error"] = str(e)
    return out
