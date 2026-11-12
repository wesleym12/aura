"""Aprende fatos duradouros sobre o usuario a partir do que ele fala.

Roda em segundo plano DEPOIS da resposta (nao atrasa a conversa). So olha a mensagem do
usuario (nao a do assistente, para nao "aprender" algo que o modelo inventou), ignora
repeticoes e respeita a opcao "Aprender sozinho" do painel de memoria.
"""
import asyncio
import logging
import re

from . import llm, memory, settings

log = logging.getLogger("uvicorn.error")

PROMPT = """Voce extrai FATOS DURADOUROS sobre o usuario {user} a partir da mensagem dele.
Conta como fato: preferencias e gostos, pessoas proximas (com nomes), animais, trabalho e profissao, rotina,
lugares onde mora ou frequenta, objetivos, equipamentos e coisas que ele possui, datas importantes.
NAO conta: pedidos do momento ("que horas sao", "liga a luz"), perguntas, opinioes passageiras,
informacoes gerais do mundo, qualquer coisa sobre o assistente.
Escreva cada fato em portugues, em terceira pessoa, curto, comecando com "{user}".
Responda SOMENTE com JSON: {{"fatos": ["...", "..."]}}. Sem fatos: {{"fatos": []}}.

Exemplos:
"meu cachorro Thor ta doente, me lembra de dar o remedio" -> {{"fatos": ["{user} tem um cachorro chamado Thor"]}}
"que horas sao?" -> {{"fatos": []}}
"sou analista de dados e trabalho de casa as sextas" -> {{"fatos": ["{user} e analista de dados", "{user} trabalha de casa as sextas-feiras"]}}"""


# so vale a pena perguntar ao modelo quando a frase fala do proprio usuario (pedidos como "abre o spotify" ou
# "quanto e 12 x 8" nunca tem fato). Economiza uma chamada ao modelo e preserva o cache do chat.
PERSONAL = re.compile(r"\b(eu|meu|minha|meus|minhas|me chamo|moro|trabalho|sou|tenho|gosto|prefiro|adoro|odeio|"
                      r"nasci|estudo|casad[oa]|namor|filh[oa]|esposa|marido|cachorro|gato|aniversario|aniversário|"
                      r"i am|i'm|my|i live|i work|i like)\b", re.I)


async def learn(conv_id: str, user_text: str) -> list[str]:
    cfg = settings.get()
    if not cfg.get("auto_learn", True) or len(user_text.split()) < 4 or not PERSONAL.search(user_text):
        return []
    messages = [{"role": "system", "content": PROMPT.format(user=cfg["user_name"])},
                {"role": "user", "content": user_text[:1500]}]
    try:
        # tarefa interna: usa o Ollama local se estiver no ar (gratis e sem mandar nada extra para a nuvem)
        msg = await llm.chat(messages, max_tokens=200, temperature=0.1, json_mode=True, internal=True, timeout=60)
        found = llm.parse_json(msg.get("content") or "").get("fatos", [])
    except Exception as e:
        log.warning("Extracao de fatos falhou: %s", e)
        return []
    finally:
        # esta chamada ocupou o cache do Ollama com outro prompt: devolve o do chat para a proxima pergunta
        from . import brain
        asyncio.get_running_loop().create_task(brain.warm_up(quiet=True))
    saved = []
    for fact in found[:5]:
        fact = " ".join(str(fact).split()).rstrip(".")
        if len(fact) < 8 or len(fact) > 200:
            continue
        if await asyncio.to_thread(memory.is_duplicate, fact):
            continue
        await asyncio.to_thread(memory.save, "fato", fact, fact, conv_id)
        saved.append(fact)
    if saved:
        log.info("Fatos aprendidos: %s", saved)
    return saved


def learn_later(conv_id: str, user_text: str):
    """Agenda o aprendizado sem bloquear quem chamou."""
    try:
        asyncio.get_running_loop().create_task(learn(conv_id, user_text))
    except RuntimeError:
        pass
