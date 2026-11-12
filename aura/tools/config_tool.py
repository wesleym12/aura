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
}


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
        new = settings.update({chave: float(valor) if chave == "voice_speed" else valor})[chave]
    except (ValueError, TypeError) as e:
        return f"Erro: valor invalido para {EDITABLE[chave]}: {e}"
    if new == old:
        return f"{EDITABLE[chave]} ja era '{new}'."
    actions.record("alterar_configuracao", f"Mudou {EDITABLE[chave].split(' (')[0].split(':')[0]}: {old} → {new}",
                   "settings", {"old": {chave: old}, "new": {chave: new}})
    return f"Pronto: {EDITABLE[chave].split(' (')[0]} agora e '{new}'."
