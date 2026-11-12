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

CATEGORIES = ["Produtividade", "Comunicação", "Design", "Desenvolvimento", "Dados", "Finanças e vendas", "Referência", "Google"]

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
    # ---- Produtividade ----
    {"id": "notion", "name": "Notion", "cat": ["Produtividade"], "color": "#111111", "kind": "oauth",
     "url": "https://mcp.notion.com/mcp", "desc": "Páginas, bancos de dados e busca no seu workspace."},
    {"id": "linear", "name": "Linear", "cat": ["Produtividade", "Desenvolvimento"], "color": "#5e6ad2", "kind": "oauth",
     "url": "https://mcp.linear.app/mcp", "desc": "Issues, projetos e ciclos."},
    {"id": "atlassian", "name": "Atlassian", "cat": ["Produtividade"], "color": "#0052cc", "kind": "oauth",
     "url": "https://mcp.atlassian.com/v1/mcp", "desc": "Jira e Confluence: tickets, páginas e busca."},
    {"id": "asana", "name": "Asana", "cat": ["Produtividade"], "color": "#f06a6a", "kind": "oauth_app",
     "url": "https://mcp.asana.com/v2/mcp", "desc": "Tarefas, projetos e prazos.",
     "app_help": "Crie um app em app.asana.com/0/my-apps (OAuth, com o redirecionamento abaixo) e cole o Client ID e o Secret."},
    {"id": "monday", "name": "monday.com", "cat": ["Produtividade"], "color": "#ff3d57", "kind": "oauth",
     "url": "https://mcp.monday.com/mcp", "desc": "Quadros, itens e atualizações."},
    {"id": "clickup", "name": "ClickUp", "cat": ["Produtividade"], "color": "#7b68ee", "kind": "oauth",
     "url": "https://mcp.clickup.com/mcp", "desc": "Tarefas, listas e documentos."},
    {"id": "todoist", "name": "Todoist", "cat": ["Produtividade"], "color": "#e44332", "kind": "oauth",
     "url": "https://ai.todoist.net/mcp", "desc": "Suas tarefas e projetos pessoais."},
    {"id": "airtable", "name": "Airtable", "cat": ["Dados", "Produtividade"], "color": "#18bfff", "kind": "oauth",
     "url": "https://mcp.airtable.com/mcp", "desc": "Bases, tabelas e registros."},
    {"id": "zapier", "name": "Zapier", "cat": ["Produtividade"], "color": "#ff4f00", "kind": "oauth",
     "url": "https://mcp.zapier.com/api/mcp/mcp", "desc": "Milhares de apps através das suas ações do Zapier."},
    # ---- Arquivos ----
    {"id": "dropbox", "name": "Dropbox", "cat": ["Dados"], "color": "#0061ff", "kind": "oauth",
     "url": "https://mcp.dropbox.com/mcp", "desc": "Buscar, ler e organizar arquivos."},
    {"id": "box", "name": "Box", "cat": ["Dados"], "color": "#0061d5", "kind": "oauth_app",
     "url": "https://mcp.box.com/mcp", "desc": "Arquivos e pastas do Box.",
     "app_help": "Crie um app OAuth 2.0 em developer.box.com (com o redirecionamento abaixo) e cole o Client ID e o Secret."},
    # ---- Comunicacao ----
    {"id": "intercom", "name": "Intercom", "cat": ["Comunicação"], "color": "#1f8ded", "kind": "oauth",
     "url": "https://mcp.intercom.com/mcp", "desc": "Conversas e contatos de suporte."},
    # ---- Design ----
    {"id": "canva", "name": "Canva", "cat": ["Design"], "color": "#00c4cc", "kind": "oauth",
     "url": "https://mcp.canva.com/mcp", "desc": "Criar e editar designs."},
    {"id": "figma", "name": "Figma", "cat": ["Design"], "color": "#a259ff", "kind": "oauth",
     "url": "https://mcp.figma.com/mcp", "desc": "Ler arquivos e designs do Figma."},
    {"id": "webflow", "name": "Webflow", "cat": ["Design"], "color": "#146ef5", "kind": "oauth",
     "url": "https://mcp.webflow.com/mcp", "desc": "Sites, páginas e CMS."},
    {"id": "wix", "name": "Wix", "cat": ["Design"], "color": "#0c6efc", "kind": "oauth",
     "url": "https://mcp.wix.com/mcp", "desc": "Sites e lojas Wix."},
    # ---- Desenvolvimento ----
    {"id": "github", "name": "GitHub", "cat": ["Desenvolvimento"], "color": "#24292f", "kind": "token",
     "url": "https://api.githubcopilot.com/mcp/", "desc": "Repositórios, issues, PRs e Actions.",
     "token_help": "Crie um token em github.com/settings/personal-access-tokens (fine-grained, só os repositórios que quiser) e cole aqui."},
    {"id": "sentry", "name": "Sentry", "cat": ["Desenvolvimento"], "color": "#362d59", "kind": "oauth",
     "url": "https://mcp.sentry.dev/mcp", "desc": "Erros e problemas dos seus apps."},
    {"id": "supabase", "name": "Supabase", "cat": ["Desenvolvimento", "Dados"], "color": "#3ecf8e", "kind": "oauth",
     "url": "https://mcp.supabase.com/mcp", "desc": "Bancos de dados e projetos Supabase."},
    {"id": "vercel", "name": "Vercel", "cat": ["Desenvolvimento"], "color": "#000000", "kind": "oauth",
     "url": "https://mcp.vercel.com", "desc": "Projetos, deploys e logs."},
    {"id": "huggingface", "name": "Hugging Face", "cat": ["Desenvolvimento", "Referência"], "color": "#ffbd2e", "kind": "open",
     "url": "https://huggingface.co/mcp", "desc": "Modelos, datasets e Spaces."},
    {"id": "cloudflare-docs", "name": "Cloudflare Docs", "cat": ["Referência", "Desenvolvimento"], "color": "#f38020", "kind": "open",
     "url": "https://docs.mcp.cloudflare.com/mcp", "desc": "Documentação da Cloudflare."},
    {"id": "context7", "name": "Context7", "cat": ["Referência", "Desenvolvimento"], "color": "#059669", "kind": "open",
     "url": "https://mcp.context7.com/mcp", "desc": "Documentação atualizada de bibliotecas de programação."},
    {"id": "deepwiki", "name": "DeepWiki", "cat": ["Referência", "Desenvolvimento"], "color": "#4f46e5", "kind": "open",
     "url": "https://mcp.deepwiki.com/mcp", "desc": "Explicações de repositórios do GitHub."},
    # ---- Financas e vendas ----
    {"id": "stripe", "name": "Stripe", "cat": ["Finanças e vendas"], "color": "#635bff", "kind": "oauth",
     "url": "https://mcp.stripe.com", "desc": "Pagamentos, clientes e assinaturas."},
    {"id": "paypal", "name": "PayPal", "cat": ["Finanças e vendas"], "color": "#003087", "kind": "oauth",
     "url": "https://mcp.paypal.com/mcp", "desc": "Faturas, pedidos e transações."},
    {"id": "square", "name": "Square", "cat": ["Finanças e vendas"], "color": "#3e4348", "kind": "oauth",
     "url": "https://mcp.squareup.com/sse", "desc": "Vendas, pedidos e catálogo."},
    {"id": "hubspot", "name": "HubSpot", "cat": ["Finanças e vendas"], "color": "#ff7a59", "kind": "oauth_app",
     "url": "https://mcp.hubspot.com", "desc": "Contatos, negócios e CRM.",
     "app_help": "Crie um app em developers.hubspot.com (MCP auth app, com o redirecionamento abaixo) e cole o Client ID e o Secret."},
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
