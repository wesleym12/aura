"""Casa inteligente (Home Assistant): ver o estado, controlar aparelhos e rodar cenas.

- casa_ver: livre (so le).
- casa_controlar: luzes, tomadas, ar, cortinas, midia, cenas... age na hora e tem Desfazer.
- casa_seguranca: fechadura, alarme, portao e garagem: SEMPRE pede Autorizar (e nao tem Desfazer automatico,
  para que desfazer um "trancar" nunca destranque a porta sem a sua confirmacao).
"""
import re
import time

from .. import actions, homeassistant as ha
from . import tool

COLORS = {"vermelho": "red", "vermelha": "red", "azul": "blue", "verde": "green", "amarelo": "yellow", "amarela": "yellow",
          "branco": "white", "branca": "white", "laranja": "orange", "roxo": "purple", "roxa": "purple", "rosa": "pink",
          "ciano": "cyan", "lilas": "violet", "lilás": "violet", "dourado": "gold", "turquesa": "turquoise"}
HVAC = {"frio": "cool", "resfriar": "cool", "gelar": "cool", "quente": "heat", "aquecer": "heat", "calor": "heat",
        "automatico": "auto", "automático": "auto", "auto": "auto", "ventilar": "fan_only", "ventilacao": "fan_only",
        "ventilação": "fan_only", "seco": "dry", "desumidificar": "dry", "desligado": "off"}
ACOES = ["ligar", "desligar", "alternar", "brilho", "cor", "temperatura", "modo", "velocidade", "abrir", "fechar", "parar",
         "posicao", "volume", "play", "pausar", "proxima", "anterior", "ativar", "aspirar", "voltar_base", "valor"]
# que tipo de aparelho aceita cada acao (as demais: ligar/desligar/alternar/ativar servem para quase tudo)
COMPAT = {"brilho": {"light"}, "cor": {"light"}, "temperatura": {"climate", "water_heater"},
          "modo": {"climate", "select", "input_select", "fan", "humidifier"}, "velocidade": {"fan"},
          "abrir": {"cover", "valve"}, "fechar": {"cover", "valve"}, "parar": {"cover", "valve"}, "posicao": {"cover"},
          "volume": {"media_player"}, "play": {"media_player"}, "pausar": {"media_player"}, "proxima": {"media_player"},
          "anterior": {"media_player"}, "aspirar": {"vacuum"}, "voltar_base": {"vacuum"}, "valor": {"number", "input_number"}}
SEG_ACOES = ["trancar", "destrancar", "abrir", "fechar", "armar_casa", "armar_ausente", "armar_noite", "desarmar"]


def _num(v, lo=0.0, hi=100.0) -> float:
    m = re.search(r"-?\d+(?:[.,]\d+)?", str(v or ""))
    if not m:
        raise ha.HAError(f"faltou um numero em 'valor' (recebi '{v}')")
    return max(lo, min(hi, float(m.group().replace(",", "."))))


def _fmt(e: dict) -> str:
    a, st = e["attributes"], e["state"]
    extra = []
    if e["domain"] == "light" and st == "on" and a.get("brightness") is not None:
        extra.append(f"brilho {round(a['brightness'] / 2.55)}%")
    if e["domain"] in ("climate", "water_heater"):
        if a.get("current_temperature") is not None:
            extra.append(f"ambiente {a['current_temperature']}°")
        if a.get("temperature") is not None:
            extra.append(f"alvo {a['temperature']}°")
    if e["domain"] == "cover" and a.get("current_position") is not None:
        extra.append(f"posição {a['current_position']}%")
    if e["domain"] == "media_player" and a.get("media_title"):
        extra.append(f"tocando '{a['media_title']}'")
    if e["domain"] == "fan" and a.get("percentage") is not None and st == "on":
        extra.append(f"velocidade {a['percentage']}%")
    val = f"{st} {e['unit']}".strip()
    tag = " [segurança: pede Autorizar]" if e["security"] else ""
    return (f"- {e['name']} ({ha.DOMAIN_PT.get(e['domain'], e['domain'])}, {e['entity_id']}): {val}"
            + (f" · {', '.join(extra)}" if extra else "") + tag)


@tool("Mostra a casa inteligente: aparelhos, comodos e estados (luzes, tomadas, ar, sensores de temperatura, portas...). "
      "Use 'busca' para filtrar por nome, comodo ou tipo (ex.: 'sala', 'luz', 'temperatura quarto'). Sem busca: tudo.",
      {"busca": {"type": "string", "x-optional": True}}, available=ha.configured)
def casa_ver(busca: str = "") -> str:
    items = ha.find(busca) if busca.strip() else ha.entities()
    if not items:
        return f"Nada encontrado para '{busca}'." if busca else "Nenhum aparelho liberado para a Aura no Home Assistant."
    out, area = [], None
    for e in items[:80]:
        if e["area"] != area:
            area = e["area"]
            out.append(f"\n{area or 'Sem cômodo'}:")
        out.append(_fmt(e))
    more = f"\n(+{len(items) - 80} aparelhos; refine a busca)" if len(items) > 80 else ""
    return "Casa (Home Assistant):" + "\n".join(out) + more


def _service(e: dict, acao: str, valor: str) -> tuple[str, str, dict]:
    d, eid = e["domain"], e["entity_id"]
    data = {"entity_id": eid}
    v = (valor or "").strip().lower()
    if acao in ("ligar", "ativar"):
        if d == "button":
            return d, "press", data
        if d == "vacuum":
            return d, "start", data
        if d in ("cover", "valve"):
            return d, f"open_{d}", data
        return d, "turn_on", data
    if acao == "desligar":
        if d in ("cover", "valve"):
            return d, f"close_{d}", data
        if d == "vacuum":
            return d, "return_to_base", data
        return d, "turn_off", data
    if acao == "alternar":
        return d, "toggle", data
    if acao == "brilho":
        return "light", "turn_on", {**data, "brightness_pct": int(_num(v))}
    if acao == "cor":
        if "quente" in v:
            return "light", "turn_on", {**data, "color_temp_kelvin": 2700}
        if "frio" in v or "fria" in v:
            return "light", "turn_on", {**data, "color_temp_kelvin": 6000}
        m = re.fullmatch(r"#?([0-9a-f]{6})", v)
        if m:
            h = m.group(1)
            return "light", "turn_on", {**data, "rgb_color": [int(h[i:i + 2], 16) for i in (0, 2, 4)]}
        name = next((en for pt, en in COLORS.items() if pt in v), v)
        return "light", "turn_on", {**data, "color_name": name}
    if acao == "temperatura":
        return d, "set_temperature", {**data, "temperature": _num(v, 5, 40)}
    if acao == "modo":
        if d == "climate":
            return d, "set_hvac_mode", {**data, "hvac_mode": HVAC.get(v, v)}
        if d in ("select", "input_select"):
            return d, "select_option", {**data, "option": valor}
        return d, "set_preset_mode", {**data, "preset_mode": valor}
    if acao == "velocidade":
        return "fan", "set_percentage", {**data, "percentage": int(_num(v))}
    if acao in ("abrir", "fechar", "parar"):
        verb = {"abrir": "open", "fechar": "close", "parar": "stop"}[acao]
        return d, f"{verb}_{'valve' if d == 'valve' else 'cover'}", data
    if acao == "posicao":
        return "cover", "set_cover_position", {**data, "position": int(_num(v))}
    if acao == "volume":
        return "media_player", "volume_set", {**data, "volume_level": round(_num(v) / 100, 2)}
    if acao in ("play", "pausar", "proxima", "anterior"):
        svc = {"play": "media_play", "pausar": "media_pause", "proxima": "media_next_track", "anterior": "media_previous_track"}[acao]
        return "media_player", svc, data
    if acao == "aspirar":
        return "vacuum", "start", data
    if acao == "voltar_base":
        return "vacuum", "return_to_base", data
    if acao == "valor":
        return d, "set_value", {**data, "value": _num(v, -1e9, 1e9)}
    raise ha.HAError(f"acao desconhecida: {acao}")


def _targets(aparelho: str) -> list[dict]:
    found = ha.find(aparelho)
    if not found:
        raise ha.HAError(f"nao achei '{aparelho}' na casa. Use casa_ver para ver os nomes.")
    return found


def _after(eid: str) -> str:
    time.sleep(0.6)
    try:
        s = ha.api("GET", f"/api/states/{eid}")
        return s["state"]
    except ha.HAError:
        return "?"


@tool("Controla aparelhos da casa: luzes (ligar/desligar/brilho 0-100/cor), tomadas, ar-condicionado (temperatura, modo "
      "frio/quente/auto/ventilar/seco), ventilador (velocidade), cortinas (abrir/fechar/posicao), TV e som "
      "(play/pausar/volume 0-100), aspirador, cenas e rotinas (ativar). 'aparelho' = nome, comodo ou id (ex.: 'luz da sala', "
      "'sala' para tudo do comodo). Fechadura, alarme, portao e garagem: use casa_seguranca.",
      {"aparelho": {"type": "string"},
       "acao": {"type": "string", "enum": ACOES},
       "valor": {"type": "string", "x-optional": True, "description": "brilho/volume/posicao em %, temperatura em graus, cor, modo"}},
      available=ha.configured)
def casa_controlar(aparelho: str, acao: str, valor: str = "") -> str:
    found = _targets(aparelho)
    sec = [e for e in found if e["security"]]
    found = [e for e in found if not e["security"] and e["domain"] not in ("sensor", "binary_sensor", "camera")]
    if not found:
        if sec:
            return f"'{sec[0]['name']}' é de segurança: use casa_seguranca (pede Autorizar)."
        return f"'{aparelho}' é só um sensor: dá para ler (casa_ver), não controlar."
    ok = [e for e in found if acao not in COMPAT or e["domain"] in COMPAT[acao]]
    if not ok:                                        # ex.: 'brilho' numa tomada
        return f"'{acao}' não serve para {', '.join(e['name'] for e in found[:5])}."
    found = ok
    if len(found) > 8:
        return "Achei aparelhos demais: " + ", ".join(e["name"] for e in found[:12]) + "... Seja mais específico."
    done = []
    for e in found:
        domain, svc, data = _service(e, acao, valor)
        undoable = e["domain"] not in ("scene", "script", "button")
        scene = ha.snapshot(e["entity_id"]) if undoable else ""
        ha.call(domain, svc, data)
        if undoable:
            actions.record("casa_controlar", f"{e['name']}: {acao} {valor}".strip(), "ha_state",
                           {"entity_id": e["entity_id"], "domain": e["domain"], "scene": scene, "prev": e["state"]})
        done.append(f"{e['name']} → {_after(e['entity_id'])}" if undoable else f"{e['name']}: ativado")
    if not done:
        return f"Nenhum aparelho de '{aparelho}' aceita '{acao}'."
    return "Feito: " + "; ".join(done)


@tool("Fechadura, alarme, portao e garagem da casa: trancar/destrancar, abrir/fechar, armar (casa/ausente/noite) ou desarmar. "
      "SEMPRE pede Autorizar ao usuario.",
      {"aparelho": {"type": "string"}, "acao": {"type": "string", "enum": SEG_ACOES},
       "codigo": {"type": "string", "x-optional": True, "description": "codigo do alarme, so se o usuario disser"}},
      sensitive=True, available=ha.configured)
def casa_seguranca(aparelho: str, acao: str, codigo: str = "") -> str:
    found = [e for e in _targets(aparelho) if e["security"]]
    if len(found) != 1:
        names = ", ".join(e["name"] for e in found) or "nenhum aparelho de segurança"
        return f"Preciso de exatamente um aparelho de segurança para '{aparelho}' (achei: {names})."
    e = found[0]
    d, data = e["domain"], {"entity_id": e["entity_id"]}
    if codigo:
        data["code"] = codigo
    svc = {"lock": {"trancar": "lock", "destrancar": "unlock", "abrir": "open", "fechar": "lock"},
           "alarm_control_panel": {"armar_casa": "alarm_arm_home", "armar_ausente": "alarm_arm_away",
                                   "armar_noite": "alarm_arm_night", "desarmar": "alarm_disarm"},
           "cover": {"abrir": "open_cover", "fechar": "close_cover"}}.get(d, {}).get(acao)
    if not svc:
        return f"'{acao}' não serve para {e['name']} ({ha.DOMAIN_PT.get(d, d)})."
    ha.call(d, svc, data)                     # sem registro de Desfazer de proposito (ver docstring)
    return f"Feito: {e['name']} → {_after(e['entity_id'])}"
