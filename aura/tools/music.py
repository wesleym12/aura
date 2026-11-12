"""Spotify: tocar playlist/musica/artista, controlar (pausar, pular, volume...) e dizer o que esta tocando.

Usa a API oficial (aura/spotify.py). Toca no aparelho ativo; se nenhum estiver aberto e o controle do
computador estiver ligado, abre o Spotify do PC e espera ele aparecer.
"""
import asyncio

from .. import spotify as sp
from . import tool

TIPOS = ["auto", "playlist", "musica", "album", "artista", "curtidas"]


async def _device() -> dict | None:
    d = await asyncio.to_thread(sp.pick_device)
    if d:
        return d
    # nenhum Spotify aberto: abre o do PC (se o controle do computador estiver ligado) e espera ele se registrar
    from . import REGISTRY
    opener = REGISTRY.get("abrir")
    if not opener or not opener.is_available():
        return None
    await opener.fn("Spotify")
    for _ in range(12):
        await asyncio.sleep(1.5)
        d = await asyncio.to_thread(sp.pick_device)
        if d:
            return d
    return None


def _resolve(o_que: str, tipo: str) -> tuple[str, str, dict]:
    """Devolve (descricao, context_uri ou uri de faixa, extra)."""
    q = o_que.strip()
    if tipo == "curtidas" or sp.norm(q) in ("musicas curtidas", "curtidas", "minhas curtidas", "liked songs"):
        user = sp.me()
        return "suas Músicas Curtidas", f"spotify:user:{user['id']}:collection", {}
    if tipo in ("auto", "playlist"):
        p = sp.find_playlist(q)
        if p:
            return f"a sua playlist {p['name']}", p["uri"], {}
    if tipo == "auto":
        a = sp.search(q, "artist")
        if a and sp.norm(a["name"]) == sp.norm(q):
            return f"{a['name']} (artista)", a["uri"], {}
        t = sp.search(q, "track")
        if t:
            return f"{t['name']} — {', '.join(x['name'] for x in t['artists'])}", t["uri"], {"track": True}
        p = sp.search(q, "playlist")
        if p:
            return f"a playlist {p['name']}", p["uri"], {}
    kind = {"playlist": "playlist", "musica": "track", "album": "album", "artista": "artist"}.get(tipo, "track")
    item = sp.search(q, kind)
    if not item:
        raise sp.SpotifyError(f"nao achei '{q}' no Spotify")
    desc = item["name"] + (f" — {', '.join(x['name'] for x in item.get('artists', []))}" if item.get("artists") else "")
    return desc, item["uri"], {"track": kind == "track"}


@tool("Toca no Spotify: uma playlist do usuario (pelo nome, ex.: 'WFM'), musica, album, artista ou as musicas "
      "curtidas. Abre o Spotify do PC sozinho se nenhum estiver aberto. Use para 'toca/abre/coloca X no Spotify'.",
      {"o_que": {"type": "string", "description": "nome da playlist, musica, album ou artista"},
       "tipo": {"type": "string", "enum": TIPOS, "x-optional": True,
                "description": "auto (padrao: procura primeiro nas playlists do usuario)"}},
      slow=True, available=sp.configured)
async def tocar_musica(o_que: str, tipo: str = "auto") -> str:
    desc, uri, extra = await asyncio.to_thread(_resolve, o_que, tipo or "auto")
    dev = await _device()
    if not dev:
        return ("Nenhum aparelho com Spotify aberto. Peca para o usuario abrir o Spotify no PC ou no celular "
                "(ou ligar o controle do computador para eu abrir sozinha).")
    if extra.get("track"):
        await asyncio.to_thread(sp.play, dev["id"], None, [uri])
    else:
        await asyncio.to_thread(sp.play, dev["id"], uri)
    return f"Tocando {desc} no {dev['name']}."


@tool("Controla o Spotify: pausar, continuar, proxima, anterior, volume (0-100), aleatorio (liga/desliga) ou repetir.",
      {"acao": {"type": "string", "enum": ["pausar", "continuar", "proxima", "anterior", "volume", "aleatorio_liga",
                                            "aleatorio_desliga", "repetir_liga", "repetir_desliga"]},
       "valor": {"type": "integer", "x-optional": True, "description": "volume em %"}},
      available=sp.configured)
async def controlar_musica(acao: str, valor: int | None = None) -> str:
    calls = {"pausar": ("PUT", "/me/player/pause", None), "continuar": ("PUT", "/me/player/play", None),
             "proxima": ("POST", "/me/player/next", None), "anterior": ("POST", "/me/player/previous", None),
             "aleatorio_liga": ("PUT", "/me/player/shuffle", {"state": "true"}),
             "aleatorio_desliga": ("PUT", "/me/player/shuffle", {"state": "false"}),
             "repetir_liga": ("PUT", "/me/player/repeat", {"state": "context"}),
             "repetir_desliga": ("PUT", "/me/player/repeat", {"state": "off"})}
    if acao == "volume":
        v = max(0, min(100, int(valor if valor is not None else 50)))
        call = ("PUT", "/me/player/volume", {"volume_percent": v})
    else:
        call = calls.get(acao)
    if not call:
        return f"Acao desconhecida: {acao}"
    try:
        await asyncio.to_thread(sp.api, call[0], call[1], params=call[2])
    except sp.SpotifyError as e:
        if str(e) == "NO_DEVICE":
            return "Nada tocando agora: nenhum aparelho com Spotify ativo."
        raise
    return {"pausar": "Pausado.", "continuar": "Continuando.", "proxima": "Próxima música.",
            "anterior": "Música anterior."}.get(acao, f"Feito: {acao.replace('_', ' ')}" + (f" {valor}%" if acao == "volume" else "") + ".")


@tool("Diz o que esta tocando no Spotify agora (musica, artista, playlist e aparelho).", available=sp.configured)
async def musica_tocando() -> str:
    j = await asyncio.to_thread(sp.now_playing)
    if not j or not j.get("item"):
        return "Nada tocando no Spotify agora."
    it, dev = j["item"], j.get("device", {})
    who = ", ".join(a["name"] for a in it.get("artists", []))
    state = "tocando" if j.get("is_playing") else "pausado"
    return f"{state.capitalize()}: {it['name']} — {who} (no {dev.get('name', 'aparelho')}, volume {dev.get('volume_percent', '?')}%)."
