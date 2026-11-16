"""Catalogo de conectores (como os do Claude e do ChatGPT): servidores MCP oficiais dos servicos.

Todos os enderecos foram testados (respondem como servidor MCP). Tipos:
- oauth: clica em Conectar -> autoriza no site do servico -> volta conectado (a Aura se cadastra sozinha).
- oauth_app: o servico nao aceita cadastro automatico: crie um app la (redirecionamento abaixo) e cole o ID.
- token: cole um token pessoal (ex.: GitHub).
- open: publico, sem login.
- builtin: integracao propria da Aura (Google).
Nada e instalado sozinho: so conecta quando voce clica.
"""
from .mcpclient import OAUTH_REDIRECT

CATEGORIES = ["Google"]       # so o Google por enquanto (os outros conectores sairam)

# id, nome, categoria(s), descricao, cor, tipo, endereco, extra
CATALOG = [
    # ---- Google (integracao propria) ----
    {"id": "google-calendar", "name": "Google Agenda", "cat": ["Google", "Produtividade"], "color": "#1a73e8",
     "desc": "Ver, criar e alterar compromissos.", "kind": "builtin", "service": "calendar"},
    {"id": "gmail", "name": "Gmail", "cat": ["Google", "Comunicação"], "color": "#ea4335",
     "desc": "Buscar, ler, rascunhar e enviar e-mails (enviar pede Autorizar).", "kind": "builtin", "service": "gmail"},
    {"id": "google-drive", "name": "Google Drive", "cat": ["Google", "Dados"], "color": "#0f9d58",
     "desc": "Buscar e ler arquivos (Docs, PDF, Word, Excel, imagens...).", "kind": "builtin", "service": "drive"},
    {"id": "google-docs", "name": "Google Docs", "cat": ["Google", "Produtividade"], "color": "#4285f4",
     "desc": "Criar documentos e acrescentar texto.", "kind": "builtin", "service": "docs"},
    {"id": "google-sheets", "name": "Google Sheets", "cat": ["Google", "Dados"], "color": "#0f9d58",
     "desc": "Ler, criar e preencher planilhas.", "kind": "builtin", "service": "sheets"},
]
BY_ID = {c["id"]: c for c in CATALOG}

# logo de cada produto (arquivo em web/icons; Simple Icons, CC0). Sem logo publico: iniciais.
ICONS = {"google-calendar": "googlecalendar", "gmail": "gmail", "google-drive": "googledrive", "google-docs": "googledocs",
         "google-sheets": "googlesheets", "notion": "notion", "linear": "linear", "atlassian": "atlassian", "asana": "asana",
         "monday": "monday", "clickup": "clickup", "todoist": "todoist", "airtable": "airtable", "zapier": "zapier",
         "dropbox": "dropbox", "box": "box", "intercom": "intercom", "canva": "canva", "figma": "figma",
         "webflow": "webflow", "wix": "wix", "github": "github", "sentry": "sentry", "supabase": "supabase",
         "vercel": "vercel", "huggingface": "huggingface", "cloudflare-docs": "cloudflare", "stripe": "stripe",
         "paypal": "paypal", "square": "square", "hubspot": "hubspot"}


def listing(servers: list[dict], google_status: dict) -> dict:
    """Catalogo com o estado de cada item (conectado, aguardando autorizacao, erro...)."""
    from . import mcpclient
    by_cat = {s["catalog_id"]: s for s in servers if s.get("catalog_id")}
    items = []
    for c in CATALOG:
        it = {k: v for k, v in c.items()}
        if c["id"] in ICONS:
            it["icon"] = f"/icons/{ICONS[c['id']]}.svg"
        if c["kind"] == "builtin":
            on = c.get("service") in google_status.get("services", [])
            it["state"] = "connected" if on else "available"
            it["account"] = google_status.get("email", "") if on else ""
            it["google_configured"] = google_status.get("configured", False)
        else:
            s = by_cat.get(c["id"])
            if s:
                p = mcpclient.public(s)
                it.update(server_id=s["id"], status=p["status"], error=p["error"], auth_url=p["auth_url"],
                          tools=p["tools"], enabled=s["enabled"], trusted=s["trusted"])
                it["state"] = ("connected" if p["status"] == "ok" else "needs_auth" if p["status"] == "needs_auth"
                               else "off" if p["status"] == "off" else "error" if p["status"] == "error" else "connecting")
            else:
                it["state"] = "available"
        items.append(it)
    custom = [mcpclient.public(s) for s in servers if not s.get("catalog_id")]
    return {"categories": CATEGORIES, "items": items, "custom": custom, "redirect": OAUTH_REDIRECT}
