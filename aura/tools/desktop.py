"""Controle do computador, pelo agente do Windows.

Como o modelo local nao enxerga imagens, a Aura "le" a janela pela arvore de acessibilidade do
Windows (os mesmos nomes de botoes e campos que um leitor de tela usa) e age por eles.

Confirmacao real:
- sem confirmacao: listar/focar janelas, abrir programas e sites, ler a tela, print, volume/midia
- COM confirmacao (sensitive): clicar, digitar e atalhos de teclado, porque agem em qualquer programa
So aparece quando "Controle do computador" esta ligado nas configuracoes e o agente esta rodando.
"""
import base64
import time

from .. import actions, hostbridge, settings, workdir
from ..config import DB_PATH
from . import tool

SCREENS = DB_PATH.parent / "screens"
BLOCKED_EXT = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".js", ".msi", ".lnk", ".scr", ".com", ".jar", ".reg", ".hta"}


def _ready() -> bool:
    return bool(settings.get().get("desktop_control")) and hostbridge.agent_online()


async def _do(cmd: str, timeout: float = 20, **args) -> str:
    ok, out = await hostbridge.run(cmd, timeout=timeout, **args)
    return out if ok else f"Nao consegui: {out}"


@tool("Lista as janelas abertas no computador (programa e titulo).", available=_ready)
async def listar_janelas() -> str:
    return await _do("windows")


@tool("Traz uma janela para a frente, pelo titulo (ou parte dele).",
      {"titulo": {"type": "string", "description": "Parte do titulo da janela, ex.: 'Bloco de Notas'"}}, available=_ready)
async def focar_janela(titulo: str) -> str:
    return await _do("focus", title=titulo)


@tool(
    "Abre um programa instalado (ex.: 'Spotify', 'Word', 'calculadora'; inclui apps da Microsoft Store), um site "
    "(https://...), a pasta de trabalho ('pasta de trabalho') ou um arquivo dela (caminho relativo). Para abrir um "
    "programa passe so o NOME dele; so use https:// se o usuario pedir o site. Para YouTube use a ferramenta youtube.",
    {"alvo": {"type": "string", "description": "Nome do programa, endereco https://, 'pasta de trabalho' ou arquivo"}},
    available=_ready,
)
async def abrir(alvo: str) -> str:
    alvo = alvo.strip()
    if alvo.lower() in ("pasta de trabalho", "pasta", "workspace"):
        return await _do("open", path=workdir.to_windows(workdir.current()))
    root = workdir.current()
    candidate = (root / alvo).resolve()
    if candidate.exists() and (candidate == root or root in candidate.parents):
        if candidate.suffix.lower() in BLOCKED_EXT:
            return "Nao abro executaveis/scripts por aqui, por seguranca."
        return await _do("open", path=workdir.to_windows(candidate))
    return await _do("open", target=alvo)


YT_LIVE = "EgJAAQ%3D%3D"          # filtro "Ao vivo" da busca do YouTube


def _yt_first(query: str, live: bool) -> tuple[str, str] | None:
    """Melhor video (ou live) da busca do YouTube: (id, titulo). Sem chave de API: le os dados da pagina de
    resultados e, entre os primeiros, escolhe o que mais combina com o pedido (titulo + canal)."""
    import json
    import re
    import unicodedata
    from urllib.parse import quote_plus
    import httpx
    url = f"https://www.youtube.com/results?search_query={quote_plus(query)}" + (f"&sp={YT_LIVE}" if live else "")
    try:
        page = httpx.get(url, timeout=10, headers={"Accept-Language": "pt-BR,pt;q=0.9",
                                                   "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}).text
        m = re.search(r"var ytInitialData = (\{.*?\});</script>", page, re.S)
        data = json.loads(m.group(1)) if m else None
    except (httpx.HTTPError, ValueError):
        return None
    vids: list[dict] = []

    def walk(o):
        if len(vids) >= 10:
            return
        if isinstance(o, dict):
            if "videoRenderer" in o:
                vids.append(o["videoRenderer"])
            else:
                for v in o.values():
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(data)
    if not vids:
        return None

    def norm(s):
        return "".join(c for c in unicodedata.normalize("NFD", (s or "").lower()) if unicodedata.category(c) != "Mn")
    words = [w for w in re.findall(r"\w+", norm(query)) if len(w) > 2]

    def text(v, key):
        return "".join(r.get("text", "") for r in (v.get(key) or {}).get("runs", []))

    def score(i, v):
        hay = norm(text(v, "title") + " " + text(v, "ownerText"))
        return (sum(w in hay for w in words), -i)        # mais palavras do pedido; empate = o mais bem colocado
    best = max(enumerate(vids), key=lambda p: score(*p))[1]
    return best["videoId"], text(best, "title")


@tool(
    "YouTube: procura um video, musica, canal ou LIVE e ja toca o primeiro resultado, reaproveitando a aba do "
    "YouTube que ja estiver aberta (nao abre outra janela). Use para 'abre/toca/coloca X no YouTube', "
    "'abre uma live de X' (ao_vivo=true). Sem busca: so traz o YouTube para a frente. NAO use para pausar, "
    "continuar, pular ou volume do que ja esta tocando: para isso use midia.",
    {"busca": {"type": "string", "x-optional": True, "description": "o que procurar (vazio = pagina inicial)"},
     "ao_vivo": {"type": "boolean", "x-optional": True, "description": "true para lives/transmissoes ao vivo"},
     "so_resultados": {"type": "boolean", "x-optional": True,
                       "description": "true para mostrar a lista de resultados em vez de tocar o primeiro"}},
    available=_ready,
)
async def youtube(busca: str = "", ao_vivo: bool = False, so_resultados: bool = False) -> str:
    import asyncio
    from urllib.parse import quote_plus
    busca = (busca or "").strip()
    if not busca:
        # sem busca: se o YouTube ja esta aberto, so traz para a frente (nunca troca o video que esta tocando)
        out = await _do("focus", title="YouTube")
        if not out.startswith("Nao consegui"):
            return f"O YouTube ja estava aberto: trouxe para a frente ({out})."
        url, what = "https://www.youtube.com/", "o YouTube"
    else:
        hit = None if so_resultados else await asyncio.to_thread(_yt_first, busca, ao_vivo)
        if hit:
            url, what = f"https://www.youtube.com/watch?v={hit[0]}", f"'{hit[1]}'" + (" (ao vivo)" if ao_vivo else "")
        else:
            url = f"https://www.youtube.com/results?search_query={quote_plus(busca)}" + (f"&sp={YT_LIVE}" if ao_vivo else "")
            what = f"os resultados de '{busca}'" + (" ao vivo" if ao_vivo else "")
    out = await _do("open_in_tab", url=url, match="YouTube")
    return f"Abri {what} no YouTube. ({out})"


@tool(
    "Le a janela que esta em primeiro plano: lista os botoes, campos, links e menus, cada um com um numero "
    "[n] para usar em clicar. Use antes de clicar ou digitar.",
    available=_ready,
)
async def ler_tela() -> str:
    return await _do("ui", timeout=45)


@tool(
    "Clica em um item da janela atual, pelo numero que apareceu em ler_tela (ou pelo nome).",
    {"numero": {"type": "integer", "description": "Numero [n] do item em ler_tela", "x-optional": True},
     "nome": {"type": "string", "description": "Nome do botao/item, se nao souber o numero", "x-optional": True}},
    sensitive=True, available=_ready,
)
async def clicar(numero: int | None = None, nome: str | None = None) -> str:
    return await _do("click", index=numero, name=nome)


@tool(
    "Digita um texto na janela/campo que esta em foco.",
    {"texto": {"type": "string", "description": "Texto a digitar"}},
    sensitive=True, available=_ready,
)
async def digitar(texto: str) -> str:
    return await _do("type", text=texto)


@tool(
    "Aperta um atalho de teclado na janela em foco (ex.: 'ctrl+s', 'alt+tab', 'enter', 'win+d').",
    {"atalho": {"type": "string", "description": "Teclas separadas por +"}},
    sensitive=True, available=_ready,
)
async def teclas(atalho: str) -> str:
    return await _do("keys", combo=atalho)


@tool("Tira um print da tela e mostra no chat. So quando o usuario pedir um print/captura da tela.", available=_ready)
async def tirar_print() -> str:
    ok, out = await hostbridge.run("screenshot", timeout=30)
    if not ok or not out.startswith("data:image/jpeg;base64,"):
        return f"Nao consegui tirar o print: {out[:200]}"
    SCREENS.mkdir(parents=True, exist_ok=True)
    name = f"print-{time.strftime('%Y%m%d-%H%M%S')}.jpg"
    (SCREENS / name).write_bytes(base64.b64decode(out.split(",", 1)[1]))
    actions.add_media(f"/api/screens/{name}")
    return "Print tirado e mostrado na tela do chat. (Voce nao consegue ver a imagem; para saber o que ha na janela, use ler_tela.)"


@tool(
    "Pausa/continua (play_pause), pula (next) ou volta (previous) a musica ou video que esta tocando em QUALQUER "
    "programa (YouTube no navegador, Spotify, VLC...) e controla o volume do PC. Use para 'pausa a musica', "
    "'pausa o YouTube', 'continua', 'proxima', 'aumenta/abaixa o volume', 'muta'.",
    {"acao": {"type": "string", "enum": ["volume_up", "volume_down", "mute", "play_pause", "next", "previous"]},
     "vezes": {"type": "integer", "description": "Quantas vezes (volume), ate 10", "x-optional": True}},
    available=_ready,
)
async def midia(acao: str, vezes: int = 1) -> str:
    return await _do("media", action=acao, times=vezes)
