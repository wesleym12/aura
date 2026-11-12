"""Quem pode falar com a A.U.R.A.

Dois jeitos de rodar:
- So nesta maquina (padrao no Windows): porta presa em 127.0.0.1, sem senha. A protecao e aceitar so o
  host localhost/127.0.0.1 (contra DNS rebinding) e so pedidos da propria pagina (contra CSRF).
- Na rede (Linux/umbrelOS, AURA_PASSWORD definido): qualquer endereco (umbrel.local, IP...), mas tudo pede
  login com senha. O cookie de sessao vale so para o endereco onde voce entrou, entao um site malicioso
  nao consegue usa-lo (nem por DNS rebinding).

Em qualquer modo, pedidos que mudam algo (POST/PUT/DELETE) precisam vir da mesma origem da pagina.
"""
import hashlib
import hmac
import os
import time
from urllib.parse import urlparse

PASSWORD = os.getenv("AURA_PASSWORD", "").strip()
COOKIE = "aura_session"
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
EXTRA_HOSTS = {h.strip().lower() for h in os.getenv("AURA_ALLOWED_HOSTS", "").split(",") if h.strip()}
# rotas que funcionam sem login: a propria tela de login, o icone e o agente do Windows (que usa a chave dele)
OPEN_PATHS = ("/login", "/favicon.svg", "/api/host/next", "/api/host/result")
_fails = {"t": 0.0, "n": 0}


def _hostname(host: str) -> str:
    try:
        return (urlparse("//" + (host or "")).hostname or "").lower()
    except ValueError:
        return ""


def host_ok(host: str | None) -> bool:
    if PASSWORD:                       # na rede com senha: qualquer endereco (o login protege)
        return bool(host)
    h = _hostname(host or "")
    return h in LOCAL_HOSTS or h in EXTRA_HOSTS


def origin_ok(headers) -> bool:
    """O pedido veio da propria pagina? (sem Origin = nao e um navegador: agente, testes, curl)"""
    if not host_ok(headers.get("host")):
        return False
    origin = headers.get("origin")
    return origin is None or urlparse(origin).netloc.lower() == (headers.get("host") or "").lower()


def _token() -> str:
    # muda junto com a senha: trocar a senha derruba todas as sessoes
    return hmac.new(PASSWORD.encode(), b"aura-session-v1", hashlib.sha256).hexdigest()


def authed(cookies) -> bool:
    return not PASSWORD or hmac.compare_digest(cookies.get(COOKIE, ""), _token())


def needs_login(path: str, cookies) -> bool:
    return bool(PASSWORD) and not path.startswith(OPEN_PATHS) and not authed(cookies)


def check_password(given: str) -> str | None:
    """Confere a senha (com freio contra tentativas em sequencia). Devolve o valor do cookie ou None."""
    now = time.time()
    if _fails["n"] >= 5 and now - _fails["t"] < 60:
        return None                                   # 5 erros: espera 1 minuto
    if PASSWORD and hmac.compare_digest(given.encode(), PASSWORD.encode()):
        _fails.update(n=0)
        return _token()
    _fails.update(n=_fails["n"] + 1, t=now)
    return None


LOGIN_PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>A.U.R.A. · Entrar</title>
<link rel="icon" href="/favicon.svg">
<style>
:root{--bg:#eef1f5;--card:#ffffffd9;--text:#2f3640;--dim:#7d8794;--accent:#f08c00;--line:#d6dbe2}
@media (prefers-color-scheme:dark){:root{--bg:#12151b;--card:#1b2029e6;--text:#e6e9ef;--dim:#8d97a7;--line:#2b3240}}
*{box-sizing:border-box}body{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);
font:15px system-ui,sans-serif;color:var(--text);padding:16px}
form{width:100%;max-width:340px;background:var(--card);border:1px solid var(--line);border-radius:16px;padding:28px;
box-shadow:0 10px 40px #0002;display:flex;flex-direction:column;gap:14px}
h1{margin:0;font-size:22px;letter-spacing:.3em;text-align:center}h1 b{color:var(--accent)}
p{margin:0;color:var(--dim);font-size:13px;text-align:center}
input{padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:transparent;color:var(--text);font-size:15px}
input:focus{outline:none;border-color:var(--accent)}
button{padding:11px;border:0;border-radius:999px;background:var(--accent);color:#fff;font-weight:600;font-size:15px;cursor:pointer}
.err{color:#d9480f;font-size:13px;text-align:center}
</style></head><body><form method="post" action="/login">
<h1>A.U.R.A<b>.</b></h1><p>Digite a senha de acesso.</p>
<input type="password" name="senha" autocomplete="current-password" autofocus required aria-label="Senha">
__ERRO__<button type="submit">Entrar</button></form></body></html>"""
