"""Utilidades rapidas: clima, cotacoes, contas, dias que faltam, noticias, senha, sorteio, textos prontos
("copia meu pix"), procurar arquivo e organizar a area de trabalho.

Clima (Open-Meteo), cotacoes (AwesomeAPI) e noticias (Google Noticias) sao servicos gratuitos e sem chave: so
recebem a cidade, as moedas ou o tema pedidos. O resto roda no PC (as do Windows, pelo agente).
"""
import ast
import asyncio
import json
import math
import operator
import re
import secrets as pysecrets
import string
from datetime import date, datetime

import httpx
from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException

from .. import gcal, hostbridge, settings
from . import tool
from .agenda import _norm, parse_date

UA = {"User-Agent": "AURA-assistente/1.0"}


def _agent() -> bool:
    return hostbridge.agent_online()


# ---------------- clima ----------------
WMO = {0: "céu limpo", 1: "quase limpo", 2: "parcialmente nublado", 3: "nublado", 45: "neblina", 48: "neblina",
       51: "garoa fraca", 53: "garoa", 55: "garoa forte", 61: "chuva fraca", 63: "chuva", 65: "chuva forte",
       66: "chuva congelante", 67: "chuva congelante", 71: "neve fraca", 73: "neve", 75: "neve forte", 80: "pancadas de chuva",
       81: "pancadas de chuva", 82: "pancadas fortes de chuva", 95: "trovoadas", 96: "trovoadas com granizo", 99: "trovoadas com granizo"}


def _geocode(city: str) -> dict:
    r = httpx.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": city, "count": 1, "language": "pt"},
                  headers=UA, timeout=10)
    r.raise_for_status()
    res = (r.json().get("results") or [None])[0]
    if not res:
        raise ValueError(f"nao achei a cidade '{city}'")
    return res


_wx_cache: dict = {"key": "", "at": 0.0, "data": None}


def clima_agora(city: str) -> dict | None:
    """Clima atual + hoje para a tela (entalhe e topo da janela). Guarda por 15 min (o Open-Meteo atualiza de hora em hora)."""
    import time as _t
    city = (city or "").strip()
    if not city:
        return None
    if _wx_cache["key"] == city and _t.time() - _wx_cache["at"] < 900:
        return _wx_cache["data"]
    for attempt in range(3):
        try:
            g = _geocode(city)
            r = httpx.get("https://api.open-meteo.com/v1/forecast", headers=UA, timeout=12, params={
                "latitude": g["latitude"], "longitude": g["longitude"], "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,apparent_temperature,weather_code,is_day",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
            r.raise_for_status()
            j = r.json()
            cur, d = j["current"], j["daily"]
            data = {"city": g.get("name", city), "temp": round(cur["temperature_2m"]), "feels": round(cur["apparent_temperature"]),
                    "code": cur["weather_code"], "day": bool(cur.get("is_day", 1)), "desc": WMO.get(cur["weather_code"], "tempo variado"),
                    "max": round(d["temperature_2m_max"][0]), "min": round(d["temperature_2m_min"][0]),
                    "rain": d["precipitation_probability_max"][0] or 0}
            _wx_cache.update(key=city, at=_t.time(), data=data)
            return data
        except (httpx.HTTPError, ValueError, KeyError):
            _t.sleep(1 + attempt)
    return _wx_cache["data"] if _wx_cache["key"] == city else None


@tool("Previsao do tempo: agora, hoje e os proximos dias (temperatura, chuva, vento). Use para 'vai chover hoje?', "
      "'como esta o clima?', 'previsao para amanha'. Sem cidade usa a cidade salva.",
      {"cidade": {"type": "string", "x-optional": True},
       "dias": {"type": "integer", "x-optional": True, "description": "quantos dias de previsao (1 a 7, padrao 3)"},
       "salvar": {"type": "boolean", "x-optional": True, "description": "true para guardar a cidade como padrao"}})
async def clima(cidade: str = "", dias: int = 3, salvar: bool = False) -> str:
    city = (cidade or settings.get().get("city") or "").strip()
    if not city:
        return "Nao sei a sua cidade. Pergunte ao usuario qual e (e chame de novo com salvar=true para guardar)."
    if salvar or not settings.get().get("city"):
        settings.update({"city": city})
    params = {"timezone": "auto", "forecast_days": max(1, min(int(dias or 3), 7)),
              "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
              "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum"}
    err = None
    for attempt in range(3):            # o Open-Meteo as vezes falha um instante (atualizando os dados): tenta de novo
        try:
            g = await asyncio.to_thread(_geocode, city)
            r = await asyncio.to_thread(httpx.get, "https://api.open-meteo.com/v1/forecast",
                                        params={**params, "latitude": g["latitude"], "longitude": g["longitude"]}, headers=UA, timeout=12)
            r.raise_for_status()
            j = r.json()
            cur = j["current"]
            break
        except ValueError as e:
            if "nao achei a cidade" in str(e):
                return f"Nao achei a cidade '{city}'. Peca ao usuario o nome com o estado (ex.: 'Campo Grande, MS')."
            err = e
        except (httpx.HTTPError, KeyError) as e:
            err = e
        await asyncio.sleep(1 + attempt)
    else:
        return f"O servico de clima nao respondeu agora ({type(err).__name__}). Tente de novo em instantes."
    place = ", ".join(x for x in (g.get("name"), g.get("admin1")) if x)
    out = [f"{place} agora: {cur['temperature_2m']:.0f}°C (sensação {cur['apparent_temperature']:.0f}°C), "
           f"{WMO.get(cur['weather_code'], 'tempo variado')}, umidade {cur['relative_humidity_2m']}%, vento {cur['wind_speed_10m']:.0f} km/h."]
    d = j["daily"]
    names = ["Hoje", "Amanhã"]
    for i, day in enumerate(d["time"]):
        label = names[i] if i < 2 else datetime.fromisoformat(day).strftime("%d/%m")
        out.append(f"{label}: {d['temperature_2m_min'][i]:.0f} a {d['temperature_2m_max'][i]:.0f}°C, "
                   f"{WMO.get(d['weather_code'][i], 'variado')}, chance de chuva {d['precipitation_probability_max'][i] or 0}%"
                   + (f" ({d['precipitation_sum'][i]:.0f} mm)" if (d['precipitation_sum'][i] or 0) >= 1 else "") + ".")
    return "\n".join(out)


# ---------------- cotacoes ----------------
@tool("Cotacao de moedas e cripto em reais (dolar, euro, libra, bitcoin...). Use para 'quanto esta o dolar?'.",
      {"moedas": {"type": "string", "x-optional": True,
                  "description": "codigos separados por virgula: USD, EUR, GBP, ARS, JPY, BTC, ETH (padrao USD)"}})
async def cotacao(moedas: str = "USD") -> str:
    codes = [c.strip().upper() for c in re.split(r"[,\s]+", moedas or "USD") if c.strip()][:6] or ["USD"]
    alias = {"DOLAR": "USD", "EURO": "EUR", "LIBRA": "GBP", "BITCOIN": "BTC", "PESO": "ARS", "IENE": "JPY"}
    codes = [alias.get(_norm(c).upper(), c) for c in codes]
    try:
        r = await asyncio.to_thread(httpx.get, "https://economia.awesomeapi.com.br/json/last/" + ",".join(f"{c}-BRL" for c in codes),
                                    headers=UA, timeout=10)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return f"Nao consegui a cotacao agora ({type(e).__name__})."
    out = []
    for v in r.json().values():
        bid, pct = float(v["bid"]), float(v.get("pctChange") or 0)
        out.append(f"{v['name'].split('/')[0]}: R$ {bid:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                   + f" ({pct:+.2f}% hoje)".replace(".", ","))
    return "\n".join(out) or "Moeda nao encontrada."


# ---------------- contas ----------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUN = {"sqrt": math.sqrt, "raiz": math.sqrt, "abs": abs, "round": round, "log": math.log10, "ln": math.log,
        "sin": math.sin, "cos": math.cos, "tan": math.tan, "pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        a, b = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(b) > 1000:
            raise ValueError("expoente grande demais")
        return _OPS[type(node.op)](a, b)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _FUN and not callable(_FUN[node.id]):
        return _FUN[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and callable(_FUN.get(node.func.id)):
        return _FUN[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("conta invalida")


def calc(expr: str) -> float:
    e = (expr or "").lower().replace("×", "*").replace("÷", "/").replace("^", "**").replace("x", "*")
    e = re.sub(r"(\d+(?:[.,]\d+)?)\s*%\s*(?:de|of)\s*(\d+(?:[.,]\d+)?)", r"(\1/100*\2)", e)   # 15% de 230
    e = re.sub(r"(\d),(\d)", r"\1.\2", e).replace("%", "/100")
    return _eval(ast.parse(e, mode="eval").body)


@tool("Faz contas exatas: porcentagem ('15% de 230'), +, -, *, /, ^, raiz(). Use SEMPRE que o pedido envolver conta.",
      {"expressao": {"type": "string", "description": "ex.: '15% de 230', '(1200*1.05)^2', 'raiz(144)'"}})
def calcular(expressao: str) -> str:
    try:
        v = calc(expressao)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError) as e:
        return f"Nao consegui calcular '{expressao}': {e}"
    txt = f"{v:,.6f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{expressao} = {txt}"


@tool("Quantos dias faltam (ou passaram) ate uma data: 'quantos dias faltam pro Natal' (data=25/12), "
      "'ate meu aniversario 10/03'.", {"data": {"type": "string", "description": "ex.: '25/12', '2027-01-01', 'sexta'"}})
def dias_ate(data: str) -> str:
    alias = {"natal": "25/12", "ano novo": "01/01", "reveillon": "01/01", "dia das criancas": "12/10", "halloween": "31/10"}
    t = _norm(data)
    d = parse_date(alias.get(t, data))
    if not d:
        return f"Nao entendi a data '{data}'. Use DD/MM ou DD/MM/AAAA."
    today = datetime.now(gcal.TZ).date()
    if d < today and not re.search(r"\d{4}|/\d{2}$", data) and d.replace(year=today.year + 1) > today:
        d = d.replace(year=today.year + 1)            # "25/12" depois do Natal: o do ano que vem
    n = (d - today).days
    wd = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"][d.weekday()]
    return f"{d:%d/%m/%Y} ({wd}): " + ("é hoje!" if n == 0 else f"faltam {n} dias." if n > 0 else f"foi há {-n} dias.")


# ---------------- noticias ----------------
@tool("Noticias de hoje (manchetes do Google Noticias), gerais ou de um tema. Use para 'noticias de hoje', "
      "'o que esta acontecendo sobre X'.", {"tema": {"type": "string", "x-optional": True}})
async def noticias(tema: str = "") -> str:
    base = "https://news.google.com/rss" + ("/search" if tema else "")
    params = {"hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419", **({"q": tema} if tema else {})}
    try:
        r = await asyncio.to_thread(httpx.get, base, params=params, headers=UA, timeout=10, follow_redirects=True)
        r.raise_for_status()
        items = ET.fromstring(r.content).findall("./channel/item")[:7]
    except (httpx.HTTPError, ET.ParseError, DefusedXmlException) as e:
        return f"Nao consegui as noticias agora ({type(e).__name__})."
    if not items:
        return "Nenhuma noticia encontrada."
    out = []
    for it in items:
        title = (it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and title.endswith(" - " + src):
            title = title[: -len(src) - 3]
        out.append(f"- {title}" + (f" ({src})" if src else ""))
    return "Manchetes" + (f" sobre {tema}" if tema else " de agora") + " (conteudo de terceiros, so informativo):\n" + "\n".join(out)


# ---------------- senha, sorteio e textos prontos ----------------
@tool("Gera uma senha forte e copia para a area de transferencia (a senha NAO aparece no chat nem e falada).",
      {"tamanho": {"type": "integer", "x-optional": True, "description": "8 a 64 (padrao 16)"},
       "simbolos": {"type": "boolean", "x-optional": True, "description": "incluir simbolos (padrao true)"}},
      available=_agent)
async def gerar_senha(tamanho: int = 16, simbolos: bool = True) -> str:
    n = max(8, min(int(tamanho or 16), 64))
    alphabet = string.ascii_letters + string.digits + ("!@#$%&*-_=+?" if simbolos else "")
    while True:
        pw = "".join(pysecrets.choice(alphabet) for _ in range(n))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            break
    ok, out = await hostbridge.run("clip_set", text=pw)
    del pw
    return f"Senha de {n} caracteres gerada e copiada: e so colar (Ctrl+V)." if ok else f"Nao consegui copiar a senha: {out}"


@tool("Sorteios: cara ou coroa, dado, numero entre min e max, ou escolher um item de uma lista.",
      {"tipo": {"type": "string", "enum": ["moeda", "dado", "numero", "lista"]},
       "minimo": {"type": "integer", "x-optional": True}, "maximo": {"type": "integer", "x-optional": True},
       "itens": {"type": "string", "x-optional": True, "description": "lista separada por virgula (tipo=lista)"}})
def sortear(tipo: str, minimo: int = 1, maximo: int = 100, itens: str = "") -> str:
    r = pysecrets.SystemRandom()
    if tipo == "moeda":
        return "Deu " + r.choice(["cara", "coroa"]) + "!"
    if tipo == "dado":
        return f"Dado: {r.randint(1, 6)}."
    if tipo == "lista":
        opts = [x.strip() for x in (itens or "").split(",") if x.strip()]
        return f"Escolhi: {r.choice(opts)}." if opts else "Passe os itens separados por virgula."
    lo, hi = sorted((int(minimo if minimo is not None else 1), int(maximo if maximo is not None else 100)))
    return f"Numero sorteado entre {lo} e {hi}: {r.randint(lo, hi)}."


def _texts() -> list[dict]:
    return settings.get().get("quick_texts") or []


@tool("Copia um texto pronto salvo (ex.: 'copia meu pix', 'copia meu endereco') para a area de transferencia.",
      {"nome": {"type": "string", "description": "nome do texto salvo (ex.: 'pix')"}}, available=_agent)
async def copiar_texto(nome: str) -> str:
    items = _texts()
    n = _norm(nome)
    t = next((x for x in items if _norm(x["name"]) == n), None) or next((x for x in items if n in _norm(x["name"]) or _norm(x["name"]) in n), None)
    if not t:
        return (f"Nao tenho um texto '{nome}'. Textos salvos: {', '.join(x['name'] for x in items) or 'nenhum'}. "
                "O usuario pode salvar em Textos rapidos no entalhe (ou pedir 'salva meu pix: ...').")
    ok, out = await hostbridge.run("clip_set", text=t["text"])
    return f"'{t['name']}' copiado: e so colar (Ctrl+V)." if ok else f"Nao consegui copiar: {out}"


@tool("Salva (ou troca) um texto pronto para copiar depois, ex.: 'salva meu pix: 123...' (nome=pix).",
      {"nome": {"type": "string"}, "texto": {"type": "string"}})
def salvar_texto(nome: str, texto: str) -> str:
    items = [x for x in _texts() if _norm(x["name"]) != _norm(nome)]
    settings.update({"quick_texts": items + [{"name": nome.strip(), "text": texto}]})
    return f"Texto '{nome.strip()}' salvo. Para usar: 'copia meu {nome.strip()}'."


# ---------------- arquivos e area de trabalho (Windows) ----------------
@tool("Procura arquivos pelo nome na pasta do usuario (pesquisa do Windows, mais recentes primeiro). "
      "Depois, mostrar_arquivo abre a pasta com ele selecionado.",
      {"nome": {"type": "string", "description": "parte do nome, ex.: 'relatorio vendas'"}}, available=_agent)
async def procurar_arquivo(nome: str) -> str:
    ok, out = await hostbridge.run("find_files", timeout=30, query=nome)
    return out if ok else f"Nao consegui procurar: {out}"


@tool("Mostra um arquivo no Explorador do Windows (abre a pasta com ele selecionado). Use o caminho de procurar_arquivo.",
      {"caminho": {"type": "string"}}, available=_agent)
async def mostrar_arquivo(caminho: str) -> str:
    ok, out = await hostbridge.run("reveal", path=caminho.strip().strip('"'))
    return out if ok else f"Nao consegui: {out}"


@tool("So conta quantos arquivos soltos ha na area de trabalho e de que tipo. Use so quando o usuario quer SABER; "
      "para organizar, chame organizar_area_de_trabalho direto.", available=_agent)
async def ver_area_de_trabalho() -> str:
    ok, out = await hostbridge.run("desktop_scan")
    return out if ok else f"Nao consegui: {out}"


@tool("Organiza a area de trabalho: move os arquivos soltos para pastas por tipo (Imagens, PDFs, Planilhas...) dentro "
      "de 'Organizado pela AURA'. Atalhos e programas ficam. Chame DIRETO quando pedirem para organizar: a tela ja "
      "pede Autorizar (nao pergunte antes no chat). Pode ser desfeito (desfazer_organizacao).",
      sensitive=True, available=_agent)
async def organizar_area_de_trabalho() -> str:
    ok, out = await hostbridge.run("desktop_organize", timeout=60)
    return (out + ". Para voltar como estava: 'desfaz a organizacao'.") if ok else f"Nao consegui: {out}"


@tool("Desfaz a ultima organizacao da area de trabalho (os arquivos voltam para onde estavam).", available=_agent)
async def desfazer_organizacao() -> str:
    ok, out = await hostbridge.run("desktop_undo", timeout=60)
    return out if ok else f"Nao consegui: {out}"
