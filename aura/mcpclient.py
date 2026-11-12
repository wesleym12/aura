"""Conexoes MCP (Model Context Protocol): plugue servidores MCP e as ferramentas deles viram habilidades.

Dois tipos:
- http:  servidor remoto ou local por URL (Streamable HTTP; SSE antigo tambem funciona com /sse no fim).
- stdio: um programa rodado DENTRO do container (ex.: "npx -y @modelcontextprotocol/server-memory"
         ou "uvx mcp-server-fetch"). Node (npx) e uv (uvx) ja estao instalados.

Cada servidor tem uma tarefa propria que mantem a sessao aberta e reconecta sozinha se cair.
Seguranca: ferramentas que o servidor NAO marca como somente-leitura pedem Autorizar, a menos que
voce marque o servidor como "confiavel". Variaveis e cabecalhos (tokens) ficam no banco local e
nunca voltam inteiros para a tela.
"""
import asyncio
import json
import logging
import re
import shlex
import sqlite3
import uuid
from contextlib import asynccontextmanager, closing

from .config import DB_PATH
from .tools import REGISTRY, Tool

log = logging.getLogger("uvicorn.error")
_conns: dict[str, "Conn"] = {}


# ---------------- configuracao (banco) ----------------
def _db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with closing(_db()) as c, c:
        c.execute("""CREATE TABLE IF NOT EXISTS mcp_servers(
            id TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,      -- http | stdio
            target TEXT NOT NULL,                                            -- URL ou linha de comando
            env TEXT DEFAULT '{}',                                           -- variaveis (stdio) ou cabecalhos (http)
            enabled INTEGER DEFAULT 1, trusted INTEGER DEFAULT 0,
            created TEXT DEFAULT (datetime('now','localtime')))""")
        cols = {r["name"] for r in c.execute("PRAGMA table_info(mcp_servers)")}
        if "oauth" not in cols:                # login OAuth (conectores do catalogo: Notion, Linear...)
            c.execute("ALTER TABLE mcp_servers ADD COLUMN oauth INTEGER DEFAULT 0")
        if "catalog_id" not in cols:           # de qual item do catalogo veio (vazio = conexao personalizada)
            c.execute("ALTER TABLE mcp_servers ADD COLUMN catalog_id TEXT DEFAULT ''")


def servers() -> list[dict]:
    with closing(_db()) as c:
        rows = c.execute("SELECT * FROM mcp_servers ORDER BY lower(name)").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["env"] = json.loads(d["env"] or "{}")
        d["enabled"], d["trusted"], d["oauth"] = bool(d["enabled"]), bool(d["trusted"]), bool(d.get("oauth"))
        d["catalog_id"] = d.get("catalog_id") or ""
        out.append(d)
    return out


def server(sid: str) -> dict | None:
    return next((s for s in servers() if s["id"] == sid), None)


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")[:20] or "mcp"


def save(data: dict, sid: str | None = None) -> dict:
    name = str(data.get("name", "")).strip()[:40]
    kind = data.get("kind")
    target = str(data.get("target", "")).strip()
    if not name or kind not in ("http", "stdio") or not target:
        raise ValueError("preencha nome, tipo e endereco/comando")
    if kind == "http" and not re.match(r"^https?://", target):
        raise ValueError("o endereco precisa comecar com http:// ou https://")
    if any(s["name"].lower() == name.lower() and s["id"] != sid for s in servers()):
        raise ValueError("ja existe uma conexao com esse nome")
    old = server(sid) if sid else None
    env = dict(old["env"]) if old else {}
    if "env" in data:                                   # texto "CHAVE=valor" por linha; valor vazio mantem o antigo
        new_env = {}
        for line in str(data["env"] or "").splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                if k:
                    new_env[k] = v.strip() if v.strip() or k not in env else env[k]
        env = new_env
    oauth = int(bool(data.get("oauth", old["oauth"] if old else False)))
    cat = str(data.get("catalog_id", old["catalog_id"] if old else "") or "")[:40]
    with closing(_db()) as c, c:
        if old:
            c.execute("UPDATE mcp_servers SET name=?, kind=?, target=?, env=?, enabled=?, trusted=?, oauth=?, catalog_id=? WHERE id=?",
                      (name, kind, target, json.dumps(env), int(data.get("enabled", old["enabled"])),
                       int(data.get("trusted", old["trusted"])), oauth, cat, sid))
        else:
            sid = uuid.uuid4().hex[:10]
            c.execute("INSERT INTO mcp_servers(id, name, kind, target, env, enabled, trusted, oauth, catalog_id) VALUES (?,?,?,?,?,?,?,?,?)",
                      (sid, name, kind, target, json.dumps(env), int(data.get("enabled", True)), int(data.get("trusted", False)), oauth, cat))
    if data.get("client_id"):                          # app proprio (servicos sem registro automatico: Asana, Box, HubSpot)
        TokenStore(sid).set_static_client(str(data["client_id"]).strip(), str(data.get("client_secret") or "").strip())
    return server(sid)


def set_flags(sid: str, **flags) -> dict | None:
    with closing(_db()) as c, c:
        for k in ("enabled", "trusted"):
            if k in flags:
                c.execute(f"UPDATE mcp_servers SET {k} = ? WHERE id = ?", (int(bool(flags[k])), sid))
    return server(sid)


def delete(sid: str):
    with closing(_db()) as c, c:
        c.execute("DELETE FROM mcp_servers WHERE id = ?", (sid,))
    TokenStore(sid).clear()                           # login OAuth vai junto


def public(s: dict) -> dict:
    """Para a tela: sem os valores das variaveis/tokens."""
    c = _conns.get(s["id"])
    return {**{k: v for k, v in s.items() if k != "env"}, "env_keys": list(s["env"].keys()),
            "status": c.status if c else ("off" if not s["enabled"] else "connecting"),
            "error": c.error if c else "", "tools": [t["name"] for t in (c.tools if c else [])],
            "auth_url": c.auth_url if c and c.status == "needs_auth" else ""}


# ---------------- login OAuth (conectores do catalogo) ----------------
OAUTH_REDIRECT = "http://localhost:8765/api/mcp/oauth/callback"


class TokenStore:
    """Guarda o login OAuth de cada conexao (tokens e o cadastro do app) no banco local, como as chaves."""

    def __init__(self, sid: str):
        self.key = f"mcp_oauth_{sid}"

    def _load(self) -> dict:
        from . import secrets
        try:
            return json.loads(secrets.get(self.key) or "{}")
        except ValueError:
            return {}

    def _save(self, d: dict):
        from . import secrets
        secrets.put(self.key, json.dumps(d) if d else None)

    # interface que o SDK do MCP usa
    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        t = self._load().get("tokens")
        return OAuthToken.model_validate(t) if t else None

    async def set_tokens(self, tokens):
        d = self._load(); d["tokens"] = tokens.model_dump(mode="json", exclude_none=True); self._save(d)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        ci = self._load().get("client")
        return OAuthClientInformationFull.model_validate(ci) if ci else None

    async def set_client_info(self, info):
        d = self._load(); d["client"] = info.model_dump(mode="json", exclude_none=True); self._save(d)

    def set_static_client(self, client_id: str, client_secret: str = ""):
        d = self._load()
        d["client"] = {"client_id": client_id, "redirect_uris": [OAUTH_REDIRECT],
                       "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"],
                       "token_endpoint_auth_method": "client_secret_post" if client_secret else "none",
                       **({"client_secret": client_secret} if client_secret else {})}
        d.pop("tokens", None)
        self._save(d)

    def has_tokens(self) -> bool:
        return bool(self._load().get("tokens"))

    def clear(self):
        self._save({})


_pending_auth: dict[str, "Conn"] = {}                 # state do OAuth -> conexao esperando o retorno


def finish_oauth(code: str, state: str) -> str | None:
    """Retorno do login (rota /api/mcp/oauth/callback): entrega o codigo a conexao que estava esperando."""
    conn = _pending_auth.pop(state, None)
    if not conn or not conn.auth_future or conn.auth_future.done():
        return None
    conn.auth_future.set_result((code, state))
    return conn.cfg["name"]


# ---------------- conexao ----------------
class Conn:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.status = "connecting"
        self.error = ""
        self.tools: list[dict] = []
        self.queue: asyncio.Queue = asyncio.Queue()
        self.task: asyncio.Task | None = None
        self.prefix = _slug(cfg["name"])
        self.auth_url = ""                                 # link de autorizacao (OAuth) para a tela
        self.auth_future: asyncio.Future | None = None

    def register(self, tools):
        self.unregister()
        self.tools = []
        for t in tools:
            ann = getattr(t, "annotations", None)
            read_only = bool(getattr(ann, "readOnlyHint", False)) if ann else False
            schema = t.inputSchema or {}
            req = set(schema.get("required", []))
            params = {k: ({**v, "x-optional": True} if k not in req else dict(v))
                      for k, v in (schema.get("properties") or {}).items() if isinstance(v, dict)}
            full = re.sub(r"[^a-zA-Z0-9_-]", "_", f"{self.prefix}__{t.name}")[:64]
            desc = (t.description or t.name).strip().split("\n\n")[0][:600]

            async def run(_tool=t.name, **kw):
                return await self.call(_tool, kw)

            REGISTRY[full] = Tool(full, f"[{self.cfg['name']}] {desc}", params, run,
                                  sensitive=not (read_only or self.cfg["trusted"]), slow=False,
                                  available=lambda: self.status == "ok", origin=f"mcp:{self.cfg['name']}")
            self.tools.append({"name": t.name, "full": full, "read_only": read_only})

    def unregister(self):
        for n in [n for n, t in REGISTRY.items() if t.origin == f"mcp:{self.cfg['name']}"]:
            del REGISTRY[n]

    async def call(self, tool: str, args: dict) -> str:
        if self.status != "ok":
            return f"Erro: a conexao MCP '{self.cfg['name']}' nao esta conectada ({self.error or self.status})."
        fut = asyncio.get_running_loop().create_future()
        await self.queue.put((tool, args, fut))
        res = await fut
        parts = []
        for c in getattr(res, "content", []) or []:
            if getattr(c, "type", "") == "text":
                parts.append(c.text)
            elif getattr(c, "type", "") == "image":
                parts.append("[imagem]")
            elif getattr(c, "type", "") == "resource":
                parts.append(str(getattr(c.resource, "text", "") or getattr(c.resource, "uri", "")))
        if not parts and getattr(res, "structuredContent", None):
            parts.append(json.dumps(res.structuredContent, ensure_ascii=False))
        text = "\n".join(parts) or "(sem resposta)"
        return ("Erro: " + text) if getattr(res, "isError", False) else text

    def _oauth(self):
        """Login OAuth (padrao do MCP): a Aura se cadastra no servico (ou usa o app que voce colou),
        mostra o link de autorizacao na tela e espera o retorno em /api/mcp/oauth/callback."""
        from urllib.parse import parse_qs, urlparse
        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata

        async def redirect_handler(url: str):
            state = (parse_qs(urlparse(url).query).get("state") or [""])[0]
            self.auth_future = asyncio.get_running_loop().create_future()
            _pending_auth[state] = self
            self.auth_url, self.status = url, "needs_auth"
            log.info("MCP %s: aguardando autorizacao do usuario", self.cfg["name"])

        async def callback_handler():
            try:
                res = await asyncio.wait_for(self.auth_future, 900)      # 15 min para clicar em Autorizar
            except asyncio.TimeoutError:
                raise RuntimeError("AUTH_TIMEOUT") from None
            self.status, self.auth_url = "connecting", ""             # autorizou: segue conectando
            return res

        meta = OAuthClientMetadata(client_name="Aura (assistente pessoal)", redirect_uris=[OAUTH_REDIRECT],
                                   grant_types=["authorization_code", "refresh_token"], response_types=["code"],
                                   token_endpoint_auth_method="none")
        return OAuthClientProvider(server_url=self.cfg["target"], client_metadata=meta, storage=TokenStore(self.cfg["id"]),
                                   redirect_handler=redirect_handler, callback_handler=callback_handler, timeout=900)

    @asynccontextmanager
    async def _transport(self):
        cfg = self.cfg
        if cfg["kind"] == "http":
            auth = self._oauth() if cfg.get("oauth") else None
            if cfg["target"].rstrip("/").endswith("/sse"):
                from mcp.client.sse import sse_client
                async with sse_client(cfg["target"], headers=cfg["env"] or None, auth=auth) as (r, w):
                    yield r, w
            else:
                from mcp.client.streamable_http import streamablehttp_client
                async with streamablehttp_client(cfg["target"], headers=cfg["env"] or None, auth=auth) as (r, w, _):
                    yield r, w
        else:
            import os
            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client
            parts = shlex.split(cfg["target"])
            env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "LANG", "TZ", "NODE_PATH", "USER")}
            env.update(cfg["env"])
            async with stdio_client(StdioServerParameters(command=parts[0], args=parts[1:], env=env, cwd="/workspace")) as (r, w):
                yield r, w

    async def run(self):
        from mcp import ClientSession
        delay = 5
        while True:
            self.status, self.error = "connecting", ""
            try:
                async with self._transport() as (r, w):
                    async with ClientSession(r, w) as s:
                        await asyncio.wait_for(s.initialize(), 90)
                        listed = await asyncio.wait_for(s.list_tools(), 60)
                        self.register(listed.tools)
                        self.status, delay = "ok", 5
                        log.info("MCP %s conectado: %d ferramenta(s)", self.cfg["name"], len(self.tools))
                        while True:
                            tool, args, fut = await self.queue.get()
                            try:
                                fut.set_result(await asyncio.wait_for(s.call_tool(tool, args or {}), 300))
                            except Exception as e:
                                if not fut.done():
                                    fut.set_exception(e)
                                if isinstance(e, (asyncio.TimeoutError,)):
                                    continue
                                raise
            except asyncio.CancelledError:
                self.unregister()
                self.status = "off"
                raise
            except BaseException as e:      # inclui ExceptionGroup do anyio
                task = asyncio.current_task()
                if task and task.cancelling():              # cancelamento embrulhado pelo anyio: para de vez
                    self.unregister()
                    self.status = "off"
                    raise
                msg = _reason(e)
                self.unregister()
                if "AUTH_TIMEOUT" in msg or self.status == "needs_auth":
                    # nao autorizou a tempo (ou o login falhou): para e espera o usuario clicar em Conectar de novo
                    self.status, self.auth_url = "needs_auth", ""
                    self.error = "" if "AUTH_TIMEOUT" in msg else msg[:300]
                    return
                self.status, self.error = "error", (msg or type(e).__name__)[:300]
                log.warning("MCP %s caiu: %s (tento de novo em %ss)", self.cfg["name"], self.error, delay)
                while not self.queue.empty():              # quem esperava recebe o erro
                    _, _, fut = self.queue.get_nowait()
                    if not fut.done():
                        fut.set_exception(RuntimeError(self.error))
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120)


def _reason(e: BaseException) -> str:
    """Causa real do erro (o anyio embrulha em grupos de excecoes, as vezes aninhados)."""
    while getattr(e, "exceptions", None):
        e = e.exceptions[0]
    text = str(e) or type(e).__name__
    if isinstance(e, FileNotFoundError):
        text = f"comando nao encontrado: {e.filename or text}"
    elif "Connection closed" in text or type(e).__name__ in ("McpError", "ClosedResourceError", "BrokenResourceError"):
        text += " (o servidor encerrou; veja se o comando roda e se faltam variaveis/chaves)"
    return text


def _start(cfg: dict):
    conn = Conn(cfg)
    _conns[cfg["id"]] = conn
    conn.task = asyncio.create_task(conn.run())


async def _stop(sid: str):
    conn = _conns.pop(sid, None)
    if conn and conn.task:
        conn.task.cancel()
        try:
            await conn.task
        except (asyncio.CancelledError, Exception):
            pass
        conn.unregister()


async def start_all():
    for s in servers():
        if s["enabled"]:
            _start(s)


async def restart(sid: str):
    await _stop(sid)
    s = server(sid)
    if s and s["enabled"]:
        _start(s)


async def remove(sid: str):
    await _stop(sid)
    delete(sid)
