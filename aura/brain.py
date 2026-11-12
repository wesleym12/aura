"""Loop do agente: o modelo escolhido (local ou de terceiros, via llm.py) conversa, chama
ferramentas e pausa pedindo confirmacao antes de qualquer ferramenta sensivel.

Eventos em tempo real (emit): antes de uma ferramenta demorada (slow=True) a Aura
gera na hora uma frase curta avisando que comecou ("vou pesquisar, um momento").
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import httpx

from . import actions, attachments, conversations, llm, memory, settings, workdir
from .textutil import strip_reasoning
from .tools import REGISTRY, active_tools, load_plugins, run_tool

log = logging.getLogger("uvicorn.error")
MAX_STEPS = 8
Emit = Callable[[dict], Awaitable[None]] | None


@dataclass
class Session:
    # messages[0] e o prompt de sistema; e regerado a cada chamada (nome, jeito, habilidades mudam)
    messages: list = field(default_factory=lambda: [{"role": "system", "content": ""}])
    pending: dict | None = None  # acao sensivel aguardando confirmacao
    trace: list = field(default_factory=list)  # ferramentas usadas no turno atual
    ctx: dict = field(default_factory=dict)    # contexto vindo do navegador (ex.: sistema operacional)
    recall_q: str | None = None                # pergunta da ultima busca na memoria
    recall_text: str = ""                      # memorias relevantes para essa pergunta
    lang: str | None = None                    # lingua detectada pelo Whisper neste turno
    model: str = ""                            # modelo/IA desta conversa ("" = padrao do Motor; ver llm.cfg_for)
    turn_cfg: dict | None = None               # Live: modelo que comecou o pedido atual (vai ate o fim dele)


SESSIONS: dict[str, Session] = {}


def get_session(sid: str) -> Session:
    if sid not in SESSIONS:
        load_plugins()   # conversa nova: pega plugins adicionados/alterados/removidos
        # conversa antiga (ex.: depois de reiniciar o container): recarrega o contexto do banco
        s = Session()
        for m in conversations.messages(sid):
            if m["role"] in ("user", "assistant"):
                s.messages.append({"role": m["role"], "content": m["content"]})
        s.model = (conversations.get(sid) or {}).get("model") or ""
        SESSIONS[sid] = s
    return SESSIONS[sid]


_EN = {"the", "and", "you", "what", "please", "my", "is", "are", "can", "how", "for", "this", "with", "to", "of", "it", "me", "your", "do"}
_ES = {"el", "los", "las", "que", "por", "favor", "como", "está", "esta", "para", "mi", "es", "una", "hola", "qué", "cuál"}
_PT = {"o", "os", "as", "que", "por", "favor", "como", "você", "voce", "para", "meu", "minha", "é", "uma", "não", "nao", "pra", "isso", "de", "do", "da"}


def _lang(text: str) -> str:
    """Idioma provavel da mensagem (pt/en/es), por palavras comuns. O modelo pequeno precisa dessa ajuda."""
    words = [w.strip(".,!?;:'\"()") for w in text.lower().split()]
    score = {"pt": sum(w in _PT for w in words), "en": sum(w in _EN for w in words), "es": sum(w in _ES for w in words)}
    best = max(score, key=score.get)
    return best if score[best] > score["pt"] else "pt"


LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "ja": "Japanese",
              "zh": "Chinese", "ru": "Russian", "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "uk": "Ukrainian",
              "ar": "Arabic", "hi": "Hindi", "ko": "Korean", "sv": "Swedish", "cs": "Czech", "el": "Greek",
              "ro": "Romanian", "hu": "Hungarian", "fi": "Finnish", "da": "Danish", "no": "Norwegian", "ca": "Catalan",
              "pt": "Brazilian Portuguese"}


def lang_rule(lang: str | None) -> str:
    if not lang or lang == "pt":
        return ""
    name = LANG_NAMES.get(lang, lang)
    return f"\nIMPORTANT: the user is speaking {name}. Reply ONLY in {name}."


def _last_user(s: Session) -> str:
    return next((m["content"] for m in reversed(s.messages)
                 if m["role"] == "user" and not str(m["content"]).startswith("[sistema]")), "")


def recall_block(query: str) -> str:
    """Memorias relevantes para esta pergunta, prontas para o prompt (o resto fica para buscar_memoria)."""
    hits = memory.recall(query)
    total = memory.count()
    if not hits:
        return f"\n\nMemoria: nada guardado parece relacionado a esta pergunta ({total} itens no total; use buscar_memoria se precisar)."
    label = {"fato": "fato sobre o usuario", "nota": "anotacao", "claude": "pesquisa", "codex": "tarefa de codigo"}
    lines = [f"- [{label.get(h['kind'], h['kind'])}, {h['created'][:10]}] {h['content'][:300]}" for h in hits]
    return ("\n\nO que voce lembra e pode ajudar agora (da sua memoria; fatos sobre o usuario sao sobre ELE, nao sobre voce;"
            " use se for relevante, nao invente alem disso):\n"
            + "\n".join(lines) + f"\n({total} itens guardados no total; para outros, use buscar_memoria.)")


def turn_lang(s: Session) -> str:
    """Lingua deste turno: a que o Whisper ouviu (voz) ou a estimada pelo texto digitado."""
    return s.lang or _lang(_last_user(s))


async def _think(s: Session) -> dict:
    q = _last_user(s)
    if s.recall_q != q:                       # uma busca por pergunta (o loop de ferramentas reaproveita)
        from .instructions import auto_skill_block
        s.recall_q, s.recall_text = q, await asyncio.to_thread(recall_block, q)
        s.recall_text += await asyncio.to_thread(auto_skill_block, q)   # skill que combina com o pedido
    cfg = llm.cfg_for(s.model)                 # o modelo escolhido nesta conversa (ou o padrao do Motor)
    # Desempenho: o prompt de sistema (+ lista de ferramentas, que o modelo recebe logo depois dele) fica IGUAL entre
    # perguntas, e o Ollama reaproveita o calculo (cache). O que muda a cada pedido (hora, memorias e skill que
    # combinam) vai junto da mensagem atual do usuario, so na copia enviada; o historico fica limpo.
    LAST_CTX.clear(); LAST_CTX.update(s.ctx)  # o aquecimento usa o mesmo contexto (prompt identico = cache valido)
    s.messages[0] = {"role": "system", "content": settings.system_prompt({**s.ctx, "brain": llm.describe(cfg)})}
    msgs = list(s.messages)
    i = _current_user_index(msgs)
    if i is not None:
        from .selfinfo import now_line
        extra = f"\n\n[contexto deste pedido: {now_line()}{s.recall_text}{lang_rule(turn_lang(s))}]"
        msgs[i] = {**msgs[i], "content": str(msgs[i].get("content") or "") + extra}
    tools = [t.schema() for t in active_tools()]
    if not s.model and llm.live_mode() and not cfg.get("local"):
        # Gemini com reservas (Flash -> Flash-Lite -> PC); quem comecou o pedido vai ate o fim dele
        msg, s.turn_cfg = await llm.chat_live_default(msgs, tools, getattr(s, "turn_cfg", None))
        return msg
    return await llm.chat(msgs, tools, cfg=cfg)


LAST_CTX: dict = {}       # contexto da pagina usado no ultimo pedido (ex.: host_os)


async def warm_up(quiet: bool = False):
    """Ao ligar: carrega o modelo local na GPU e deixa o prompt fixo (sistema + ferramentas) no cache do Ollama.
    Sem isso o primeiro pedido do dia pagava a carga do modelo (de segundos a 1-2 min com a RAM apertada)."""
    import logging
    log = logging.getLogger("uvicorn.error")
    cfg = llm.cfg_for(None)
    if not cfg.get("local") or llm.live_mode():
        return                                         # nuvem ou Gemini Live: o modelo local fica fora da memoria
    for _ in range(60):                                # o Ollama pode ainda estar subindo
        try:
            t0 = asyncio.get_running_loop().time()
            msgs = [{"role": "system", "content": settings.system_prompt({**LAST_CTX, "brain": llm.describe(cfg)})},
                    {"role": "user", "content": "oi"}]
            await llm.chat(msgs, [t.schema() for t in active_tools()], cfg=cfg, max_tokens=1)
            if not quiet:
                log.info("Modelo aquecido em %.1f s", asyncio.get_running_loop().time() - t0)
            return
        except Exception:
            if quiet:
                return
            await asyncio.sleep(5)


def _current_user_index(msgs: list) -> int | None:
    """Mensagem do usuario que abriu este turno (ignora os avisos internos '[sistema] ...')."""
    for i in range(len(msgs) - 1, 0, -1):
        m = msgs[i]
        if m.get("role") == "user" and not str(m.get("content") or "").startswith("[sistema]"):
            return i
    return None


def _agent_prompt(s: Session, text: str) -> str:
    """Pedido para o Claude/Codex quando ele e a IA da conversa: leva o historico recente junto."""
    cfg = settings.get()
    hist = [m for m in s.messages[1:-1] if m["role"] in ("user", "assistant") and m.get("content")
            and not str(m["content"]).startswith("[sistema]")][-12:]
    lines = [f"{'Usuario' if m['role'] == 'user' else 'Assistente'}: {str(m['content'])[:1500]}" for m in hist]
    lang = LANG_NAMES.get(turn_lang(s), "Brazilian Portuguese")
    return (f"Voce esta conversando com {cfg['user_name']} dentro do assistente pessoal dele ({cfg['assistant_name']}). "
            f"Responda em {lang}, de forma direta. A pasta atual e a pasta de trabalho dele.\n"
            + ("\nConversa ate aqui:\n" + "\n".join(lines) + "\n" if lines else "")
            + f"\nMensagem atual do usuario:\n{text}")


async def _agent_turn(s: Session, sid: str, text: str, emit: Emit) -> dict:
    from .tools.agents import claude_ready, codex_ready, direct
    agent = s.model.split(":", 1)[1]
    ready = claude_ready() if agent == "claude" else codex_ready()
    name = "Claude" if agent == "claude" else "Codex"
    if not ready:
        return {"status": "done", "trace": [],
                "reply": f"O {name} ainda nao esta conectado. Faca o login em Configuracoes -> Motor, ou troque de modelo no seletor."}
    if emit:
        await emit({"type": "tool", "tool": "perguntar_" + agent})
    reply = await direct(agent, _agent_prompt(s, text), text)
    s.messages.append({"role": "assistant", "content": reply})
    return {"status": "done", "reply": reply, "trace": ["perguntar_" + agent]}


# avisos prontos para tarefas de poucos segundos: gerar a frase com o modelo local custava mais que a propria
# tarefa e tirava o prompt do chat do cache do Ollama (a resposta final ficava ~4 s mais lenta)
QUICK_ACKS = {"tocar_musica": "Já vou colocar para tocar.", "criar_imagem": "Vou criar a imagem, só um instante.",
              "ler_tela": "Deixa eu ver a tela.", "ler_documento": "Vou ler o documento, um instante."}
LONG_TASKS = {"perguntar_claude", "perguntar_codex"}      # estas levam minutos: vale a frase personalizada


async def _ack(s: Session, tool_name: str, args: dict) -> str:
    """Frase curta dizendo que a tarefa demorada comecou (no idioma do usuario)."""
    lang = turn_lang(s)
    if tool_name not in LONG_TASKS:
        if lang in (None, "pt"):
            return QUICK_ACKS.get(tool_name, "Um instante.")
        return "One moment." if lang == "en" else "Un momento."
    cfg = settings.get()
    last_user = _last_user(s)
    desc = REGISTRY[tool_name].description.split(".")[0]
    lang = LANG_NAMES.get(turn_lang(s), "Brazilian Portuguese")
    payload = {
        "messages": [
            {"role": "system", "content":
                f"You are {cfg['assistant_name']}, a voice assistant. Write ONE short sentence (max 15 words) telling "
                "the user what you are about to do right now and that it may take a moment. Mention the concrete task "
                "in your own words. Write it in the SAME LANGUAGE as the user's request (Portuguese request -> Portuguese, "
                "English request -> English). Do not answer the task. No quotes, no emojis.\n"
                "Examples:\n"
                "Request: 'pesquisa os melhores notebooks de 2026' -> Vou pesquisar os melhores notebooks de 2026, só um instante.\n"
                "Request: 'write a python script to rename my photos' -> I'll write that photo-renaming script now, one moment."},
            {"role": "user", "content": f"Request: '{last_user[:400]}'\nTask you will run: {desc}.\nWrite the sentence in {lang}."},
        ],
    }
    try:
        msg = await llm.chat(payload["messages"], max_tokens=40, temperature=.6, internal=True, timeout=20)
        text = (msg.get("content") or "").strip().strip('"')
        return text.splitlines()[0] if text else "Certo, já estou cuidando disso. Um momento."
    except httpx.HTTPError:
        return "Certo, já estou cuidando disso. Um momento."


def _args(call: dict) -> dict:
    a = call.get("function", {}).get("arguments") or {}
    if isinstance(a, str):
        try:
            a = json.loads(a)
        except json.JSONDecodeError:
            a = {}
    return a


async def _run_calls(s: Session, calls: list, emit: Emit = None) -> dict | None:
    """Executa chamadas; para na primeira sensivel e devolve o pedido de confirmacao."""
    for i, call in enumerate(calls):
        name = call.get("function", {}).get("name", "")
        args = _args(call)
        t = REGISTRY.get(name)
        if t and t.sensitive:
            s.pending = {"name": name, "args": args, "id": call["id"], "remaining": calls[i + 1:]}
            return {"status": "confirm", "action": {"tool": name, "args": args}, "trace": s.trace}
        if t and t.slow and emit:
            await emit({"type": "ack", "text": await _ack(s, name, args), "tool": name})
        elif emit:
            await emit({"type": "tool", "tool": name})
        s.trace.append(name)
        result = await run_tool(name, args)
        s.messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": _clip(result)})
    return None


def _normalize_calls(calls: list) -> list:
    """Formato OpenAI completo (alguns servidores omitem id/type ou mandam argumentos como objeto)."""
    out = []
    for i, c in enumerate(calls or []):
        fn = dict(c.get("function") or {})
        if not isinstance(fn.get("arguments"), str):
            fn["arguments"] = json.dumps(fn.get("arguments") or {}, ensure_ascii=False)
        call = {"id": c.get("id") or f"call_{i}", "type": "function", "function": fn}
        # campos extras do provedor voltam intactos (Gemini 3 exige a thought_signature em extra_content)
        call.update({k: v for k, v in c.items() if k not in ("id", "type", "function", "index")})
        out.append(call)
    return out


def _clip(text: str, limit: int = 4000) -> str:
    # o contexto do modelo local e pequeno; a resposta completa do Claude/Codex fica na memoria
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[...cortado; resposta completa salva na memoria da Aura]"


# "criei o arquivo", "salvei", "abri"... sem ter chamado ferramenta nenhuma = o modelo inventou
def _did_this_round(s: Session) -> bool:
    """A resposta vem logo depois de um resultado de ferramenta? (entao ela pode dizer 'abri', 'toquei'...)"""
    for m in reversed(s.messages):
        if m.get("role") == "tool":
            return True
        if m.get("role") == "user" and not str(m.get("content") or "").startswith("[sistema]"):
            return False
    return False


# frases de quem diz que fez (ou esta fazendo) algo: sem ferramenta chamada no turno, e invencao
_CLAIM = re.compile(r"\b(criei|criado|salvei|salvo em|gravei|abri|foi abert[oa]|apaguei|movi|renomeei|escrevi o arquivo|"
                    r"toquei|coloquei (?:para|pra) tocar|est[aá] tocando|liguei|desliguei|enviei|abrindo|sintonizei|"
                    r"acabo de \w+|j[aá] (?:abri|coloquei|liguei|toquei|est[aá])|pronto,? (?:abri|est[aá])|"
                    r"estou (?:verificando|procurando|buscando|abrindo|tocando|checando|analisando)|verificando se|"
                    r"i (?:have )?(?:created|saved|opened|deleted|wrote)|i'?m (?:checking|looking|searching))\b", re.I)


async def _loop(s: Session, emit: Emit = None) -> dict:
    nudged = False
    for _ in range(MAX_STEPS):
        msg = await _think(s)
        calls = _normalize_calls(msg.get("tool_calls"))
        content = strip_reasoning(msg.get("content"))
        if not calls and not nudged and _CLAIM.search(content or "") and not _did_this_round(s):
            # da uma segunda chance: ou chama a ferramenta de verdade, ou admite que nao fez
            nudged = True
            s.messages.append({"role": "user", "content":
                "[sistema] Atencao: voce disse que fez (ou esta fazendo) uma acao, mas NAO chamou nenhuma ferramenta para "
                "isso, entao nada foi feito. Se existe ferramenta para isso, chame agora. Se nao existe, diga em uma frase, "
                "honestamente, que ainda nao consegue fazer isso. Nunca diga 'estou verificando' sem ferramenta."})
            continue
        s.messages.append({"role": "assistant", "content": content, **({"tool_calls": calls} if calls else {})})
        if not calls:
            if nudged:      # tira o aviso interno do historico
                s.messages[:] = [m for m in s.messages if not str(m.get("content") or "").startswith("[sistema] Atencao: voce disse")]
            return {"status": "done", "reply": content, "trace": s.trace}
        stop = await _run_calls(s, calls, emit)
        if stop:
            return stop
    return {"status": "done", "reply": "Parei: passos demais nesta tarefa.", "trace": s.trace}


async def chat(sid: str, text: str, emit: Emit = None, ctx: dict | None = None, lang: str | None = None,
               files: list[str] | None = None, project_id: str | None = None, model: str | None = None) -> dict:
    s = get_session(sid)
    if model is not None:
        s.model = model                                # trocou de modelo/IA no seletor: vale a partir desta mensagem
    workdir.use_conversation(sid, project_id)          # conversa de projeto = pasta do projeto
    if ctx:
        s.ctx.update({k: str(v)[:120] for k, v in ctx.items()})
    s.lang = lang if lang in LANG_NAMES else None      # lingua que o Whisper ouviu (so vale para este turno)
    # anexos: ficam valendo para as ferramentas deste turno (Claude/Codex recebem os caminhos)
    attachments.set_current(files or [])
    if files:
        text = text + await asyncio.to_thread(attachments.describe, attachments.current(), text)
    if s.pending:
        return {"status": "confirm", "action": {"tool": s.pending["name"], "args": s.pending["args"]}, "trace": s.trace}
    s.trace = []
    s.turn_cfg = None                                  # pedido novo: o padrao escolhe o modelo de novo
    s.messages.append({"role": "user", "content": text})
    acc = _track(sid)
    res = await (_agent_turn(s, sid, text, emit) if llm.is_agent(s.model) else _loop(s, emit))
    res["actions"] = acc            # o que foi feito neste turno (cada um com botao Desfazer)
    res["images"] = actions.turn_media.get() or []
    return res


def _track(sid: str) -> list:
    """Liga o diario de acoes a esta conversa e coleta as acoes (e imagens) do turno."""
    acc: list = []
    actions.current_conv.set(sid)
    actions.turn_actions.set(acc)
    actions.turn_media.set([])
    return acc


async def confirm(sid: str, approve: bool, emit: Emit = None) -> dict:
    s = get_session(sid)
    p = s.pending
    if not p:
        return {"status": "done", "reply": "Nada aguardando confirmacao.", "trace": []}
    s.pending = None
    workdir.use_conversation(sid)
    acc = _track(sid)
    if approve:
        s.trace.append(p["name"])
        result = await run_tool(p["name"], p["args"])
    else:
        result = "O usuario NAO autorizou esta acao. Nao tente de novo sem ele pedir."
    s.messages.append({"role": "tool", "tool_call_id": p["id"], "name": p["name"], "content": result})
    stop = await _run_calls(s, p["remaining"], emit)
    res = stop or await _loop(s, emit)
    res["actions"] = acc
    res["images"] = actions.turn_media.get() or []
    return res


def reset(sid: str):
    SESSIONS.pop(sid, None)
