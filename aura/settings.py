"""Preferencias do usuario (nome, voz, jeito de ser...), salvas no SQLite."""
import json
import re
import sqlite3
from contextlib import closing

from .config import DB_PATH

DEFAULTS = {
    "assistant_name": "A.U.R.A.",
    "user_name": "Wesley",
    "voice": "pf_dora",         # voz local (so as nativas do portugues: pm_alex, pm_santa, pf_dora)
    "voice_speed": 1.05,
    "voice_names": {},          # apelidos que voce deu para as vozes: {"pm_alex": "Meu Aura"}
    "personality": "equilibrado",
    "greeting": True,           # saudacao falada ao abrir o Command Center
    # {saudacao} = Bom dia/Boa tarde/Boa noite, {usuario}, {assistente}
    "greeting_text": "{saudacao}, {usuario}. {assistente} online.",
    "wake_word": "Aura",        # palavra de ativacao (o Whisper procura no comeco da fala)
    "engine": "local",          # motor de voz: local (privado, offline) | live (Gemini Live, nuvem)
    "live_voice": "Kore",       # voz do Gemini Live (aba Microfone e som)
    "auto_learn": True,         # aprender fatos sobre o usuario sozinha (aba Memoria)
    # cerebro (aba Motor): qualquer servidor compativel com OpenAI
    "llm_provider": "ollama",
    "llm_model": "",            # vazio = modelo padrao do Ollama (OLLAMA_MODEL)
    "llm_base_url": "",         # vazio = endereco padrao do provedor
    "llm_favorites": [],        # modelos da nuvem que aparecem no seletor do chat ("provedor:modelo")
    "skills_off": [],           # skills desligadas (pastas em memoria/skills)
    "telegram_chats": [],       # conversas do Telegram aprovadas: [{id, name, sid}]
    "ha_url": "",               # Home Assistant (vazio = o container homeassistant do docker-compose)
    "ha_hidden": [],            # aparelhos do HA que a Aura NAO ve (entity_id)
    "orb_style": "esfera",      # modelo do orbe: esfera | aneis | galaxia | onda | enxame | holograma
    "orb_color": "",            # cor do orbe (#rrggbb); vazio = cor do tema
    "conversation_mode": False, # modo conversa: depois de responder continua ouvindo 2 min sem a palavra (desligado = pede "Aura" de novo)
    "follow_language": False,   # a voz te segue: detecta a lingua da fala (desligado = sempre portugues, mais preciso)
    "workdir": "",              # pasta de trabalho (vazio = aura/workspace)
    "desktop_control": False,   # controle do computador (desligado ate voce ligar)
}

NATIVE_VOICES = {"pm_alex", "pm_santa", "pf_dora"}

# instalacao "so Gemini": o cerebro padrao e o Gemini (o usuario ainda pode trocar em Configuracoes -> Modelos)
from .config import LOCAL_LLM  # noqa: E402
if not LOCAL_LLM:
    DEFAULTS.update(llm_provider="gemini", llm_model="gemini-flash-latest")

# Jeitos de ser: cada um vira um trecho do prompt de sistema
PERSONALITIES = {
    "equilibrado": ("Equilibrado", "Direto e cordial. O padrão.",
                    "Seja direto e cordial, com respostas curtas e claras."),
    "profissional": ("Profissional", "Formal, trata por senhor, zero piada.",
                     "Seja formal e objetivo. Trate o usuario por 'senhor'. Nada de piadas."),
    "mordomo": ("Mordomo", "Elegante, cerimonioso, com ironia fina.",
                "Fale como um mordomo britanico elegante e cerimonioso, com ironia fina e discreta. Trate o usuario por 'senhor'."),
    "amigo": ("Amigo", "Caloroso, pergunta de volta, se importa.",
              "Seja caloroso e proximo, como um amigo. Demonstre interesse e, quando fizer sentido, pergunte de volta."),
    "direto": ("Direto", "Só o dado. Nem uma palavra a mais.",
               "Responda apenas com a informacao pedida, no minimo de palavras possivel. Sem cumprimentos nem comentarios."),
    "brincalhao": ("Brincalhão", "Tira onda, faz piada em toda resposta.",
                   "Seja bem-humorado: faca uma piada leve ou tire onda em toda resposta, sem deixar de responder."),
    "motivador": ("Motivador", "Enérgico, empurra pra frente, comemora.",
                  "Seja energico e motivador: incentive, comemore conquistas e empurre o usuario para a acao."),
    "rigoroso": ("Rigoroso", "Cobra, aponta erro, não passa a mão na cabeça.",
                 "Seja exigente: aponte erros e pontos fracos com franqueza, sem suavizar."),
    "malandro": ("Malandro", "Gíria, ginga, chama de parceiro.",
                 "Fale de um jeito descontraido e malandro, com girias brasileiras, chamando o usuario de 'parceiro'."),
    "narrador": ("Narrador", "Narra tudo como locutor de futebol.",
                 "Responda como um locutor de futebol empolgado narrando o lance, mas entregue a informacao correta."),
    "sarcastico": ("Sarcástico", "Ácido, comenta o óbvio com desdém.",
                   "Seja sarcastico e acido, comentando o obvio com um leve desdem, mas sempre respondendo corretamente."),
}


def _conn():
    return sqlite3.connect(DB_PATH)


def init():
    with closing(_conn()) as c, c:
        c.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL)")


def get() -> dict:
    out = dict(DEFAULTS)
    with closing(_conn()) as c:
        for key, value in c.execute("SELECT key, value FROM settings"):
            if key in DEFAULTS:
                out[key] = json.loads(value)
    if out["voice"] not in NATIVE_VOICES:          # voz que saiu do projeto (Aura, com sotaque): volta para a padrao
        out["voice"] = DEFAULTS["voice"]
    return out


def _validate(key, value):
    if key in ("assistant_name", "user_name"):
        value = " ".join(str(value).split())[:30]
        if not value:
            raise ValueError(f"{key} nao pode ficar vazio")
    elif key == "voice":
        value = str(value)[:40]
    elif key == "voice_speed":
        value = min(1.5, max(0.7, round(float(value), 2)))
    elif key == "voice_names":
        if not isinstance(value, dict):
            raise ValueError("voice_names deve ser um objeto")
        value = {str(k)[:40]: " ".join(str(v).split())[:30] for k, v in value.items() if str(v).strip()}
    elif key == "personality":
        if value not in PERSONALITIES:
            raise ValueError("jeito desconhecido")
    elif key in ("greeting", "auto_learn", "follow_language", "desktop_control", "conversation_mode"):
        value = bool(value)
    elif key == "workdir":
        from .workdir import validate
        value = str(validate(str(value))) if value else ""
    elif key == "llm_provider":
        from .llm import PROVIDERS
        if value not in PROVIDERS:
            raise ValueError("provedor desconhecido")
    elif key == "llm_model":
        value = str(value).strip()[:120]
    elif key == "telegram_chats":
        if not isinstance(value, list):
            raise ValueError("telegram_chats deve ser uma lista")
        value = [{"id": int(c["id"]), "name": str(c.get("name", ""))[:80], "sid": str(c.get("sid", ""))[:80]}
                 for c in value if isinstance(c, dict) and "id" in c][:20]
    elif key == "ha_url":
        value = str(value or "").strip().rstrip("/")[:200]
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("o endereco precisa comecar com http:// ou https://")
    elif key == "ha_hidden":
        if not isinstance(value, list):
            raise ValueError("ha_hidden deve ser uma lista")
        value = sorted({str(v).strip()[:120] for v in value if "." in str(v)})[:2000]
    elif key == "orb_style":
        if value not in ("esfera", "aneis", "galaxia", "onda", "enxame", "holograma"):
            raise ValueError("modelo de orbe desconhecido")
    elif key == "orb_color":
        value = str(value or "").strip().lower()
        if value and not __import__("re").fullmatch(r"#[0-9a-f]{6}", value):
            raise ValueError("cor invalida (use #rrggbb)")
    elif key == "skills_off":
        if not isinstance(value, list):
            raise ValueError("skills_off deve ser uma lista")
        value = sorted({str(v).strip()[:48] for v in value if str(v).strip()})
    elif key == "llm_favorites":
        if not isinstance(value, list):
            raise ValueError("llm_favorites deve ser uma lista")
        value = list(dict.fromkeys(str(v).strip()[:160] for v in value if ":" in str(v)))[:30]
    elif key == "llm_base_url":
        value = str(value).strip()[:200]
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("o endereco precisa comecar com http:// ou https://")
    elif key == "greeting_text":
        value = " ".join(str(value).split())[:200]
        if not value:
            raise ValueError("a saudacao nao pode ficar vazia")
    elif key == "engine":
        if value not in ("local", "live"):
            raise ValueError("motor de voz desconhecido")
    elif key == "live_voice":
        value = str(value)[:30]
    elif key == "wake_word":
        value = " ".join(str(value).split())[:40]
        if len(value) < 3:
            raise ValueError("a palavra de ativacao precisa de pelo menos 3 letras")
    return value


def update(changes: dict) -> dict:
    clean = {k: _validate(k, v) for k, v in changes.items() if k in DEFAULTS}
    # modelo da nuvem salvo no Motor vira favorito do seletor do chat
    if ("llm_model" in clean or "llm_provider" in clean) and "llm_favorites" not in clean:
        cur = get()
        prov, model = clean.get("llm_provider", cur["llm_provider"]), clean.get("llm_model", cur["llm_model"])
        from .llm import PROVIDERS
        if model and not PROVIDERS.get(prov, {}).get("local"):
            clean["llm_favorites"] = list(dict.fromkeys([f"{prov}:{model}", *cur["llm_favorites"]]))[:30]
    with closing(_conn()) as c, c:
        for k, v in clean.items():
            c.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                      (k, json.dumps(v, ensure_ascii=False)))
    return get()


def system_prompt(ctx: dict | None = None) -> str:
    from .config import SYSTEM_PROMPT_TEMPLATE
    from .selfinfo import profile
    s = get()
    jeito = PERSONALITIES.get(s["personality"], PERSONALITIES["equilibrado"])[2]
    from .instructions import prompt_block
    name = s["assistant_name"]
    if re.sub(r"[^a-z]", "", name.lower()) == "aura":    # o nome padrao: sigla completa e como se fala
        name = "A.U.R.A. (Autonomous Utility and Response Assistant; pronuncia-se \"Aura\")"
    return SYSTEM_PROMPT_TEMPLATE.format(name=name, user=s["user_name"], personality=jeito,
                                         profile=profile(ctx)) + prompt_block()   # INSTRUCOES.md, SOBRE-MIM.md, AURA.md, skills
