"""O assistente ajusta a si mesmo quando o usuario pede ("muda sua voz", "fica mais formal").
Cada mudanca entra no diario de acoes e pode ser desfeita."""
from .. import actions, settings
from . import tool

EDITABLE = {
    "assistant_name": "nome do assistente",
    "user_name": "como chamar o usuario",
    "voice": "voz local (pf_dora, pm_alex ou pm_santa)",
    "voice_speed": "velocidade da fala (0.7 a 1.5)",
    "personality": "jeito de ser: " + ", ".join(settings.PERSONALITIES),
    "wake_word": "palavra de ativacao",
    "greeting_text": "texto da saudacao ao abrir",
    "live_voice": "voz do modo Gemini Live (ex.: Orus, Kore, Puck)",
    "quiet_mode": "modo so executar / silencioso: faz e nao fala a resposta (valor: ligado ou desligado)",
    "conversation_mode": "modo conversa: continua ouvindo depois de responder (valor: ligado ou desligado)",
    "city": "cidade do clima",
    "face_acc": "acessorio do rostinho (valor: nenhum, coroa, fones, natal, festa, cartola, bone, aureola, chifres, laco, flor, oculos, bigode)",
    "face_color": "cor do rostinho (valor: branco, grafite, azul, rosa, verde, lilas, amarelo)",
}
BOOLS = {"quiet_mode", "conversation_mode"}


@tool(
    "Altera uma configuracao do proprio assistente quando o usuario pedir. Chaves: "
    + "; ".join(f"{k} = {v}" for k, v in EDITABLE.items()) + ". Pode ser desfeito.",
    {
        "chave": {"type": "string", "enum": list(EDITABLE), "description": "Qual configuracao"},
        "valor": {"type": "string", "description": "Novo valor"},
    },
)
def alterar_configuracao(chave: str, valor: str) -> str:
    if chave not in EDITABLE:
        return f"Erro: '{chave}' nao pode ser alterada por aqui."
    old = settings.get()[chave]
    try:
        if chave == "face_acc":
            import unicodedata
            v = "".join(c for c in unicodedata.normalize("NFD", str(valor).lower()) if unicodedata.category(c) != "Mn").strip()
            valor = "" if v in ("nenhum", "sem", "tirar", "") else {"chifre": "chifres", "chifrinho": "chifres", "chifrinhos": "chifres",
                                                                  "oculos escuros": "oculos", "bone": "bone", "fone": "fones",
                                                                  "gorro": "natal", "auriola": "aureola"}.get(v, v)
        if chave == "face_color":
            import unicodedata
            valor = "".join(c for c in unicodedata.normalize("NFD", str(valor).lower()) if unicodedata.category(c) != "Mn").strip()
            valor = {"branca": "branco", "cinza": "grafite", "preto": "grafite", "verde": "verde", "menta": "verde", "roxo": "lilas"}.get(valor, valor)
        if chave in BOOLS:      # "ligado"/"sim"/"true" -> True (bool("false") seria True)
            valor = str(valor).strip().lower() in ("ligado", "liga", "ligar", "sim", "true", "1", "on", "ativado", "ativa")
        new = settings.update({chave: float(valor) if chave == "voice_speed" else valor})[chave]
    except (ValueError, TypeError) as e:
        return f"Erro: valor invalido para {EDITABLE[chave]}: {e}"
    if new == old:
        return f"{EDITABLE[chave]} ja era '{new}'."
    actions.record("alterar_configuracao", f"Mudou {EDITABLE[chave].split(' (')[0].split(':')[0]}: {old} → {new}",
                   "settings", {"old": {chave: old}, "new": {chave: new}})
    if chave in BOOLS:
        return f"Pronto: {EDITABLE[chave].split(':')[0]} {'ligado' if new else 'desligado'}."
    return f"Pronto: {EDITABLE[chave].split(' (')[0]} agora e '{new}'."
