"""Motor Vivo: ponte entre o navegador e o Gemini Live (audio -> audio em tempo real).

Navegador  <-- WebSocket /ws/live -->  Aura  <-- Live API -->  Gemini
 - o audio so chega aqui DEPOIS da ativacao local ("Aura", Ctrl+Espaco ou botao);
 - a chave de API fica no servidor (nunca vai para o navegador);
 - o Gemini usa as mesmas ferramentas da Aura; as sensiveis esperam o clique em Autorizar;
 - o que foi dito vira texto e fica no historico da conversa (o modo local continua de onde parou).

Protocolo com o navegador:
  navegador -> {"type":"start","session":..,"context":{..}} | audio PCM16 16 kHz (binario)
               {"type":"text","text":..} | {"type":"end"} | {"type":"confirm","approve":bool} | {"type":"stop"}
  servidor  -> {"type":"ready"} | audio PCM16 24 kHz (binario) | {"type":"input"|"output","text":..}
               {"type":"turn_complete"} | {"type":"interrupted"} | {"type":"tool","tool":..,"text":..}
               {"type":"confirm","action":{..}} | {"type":"error","detail":..}
"""
import asyncio
import json
import logging
import os

from fastapi import WebSocket, WebSocketDisconnect
from google import genai
from google.genai import types

from . import actions, brain, conversations, facts, memory, secrets, settings, workdir
from .tools import REGISTRY, active_tools, run_tool

log = logging.getLogger("uvicorn.error")

LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.1-flash-live-preview")
def api_key() -> str:
    """Chave do Gemini: a colocada na tela (Configuracoes -> Motor) ou, se nao houver, a do .env."""
    return secrets.get("gemini") or os.getenv("GOOGLE_API_KEY", "")

# vozes do Gemini Live (nome, genero, descricao)
VOICES = [
    ("Orus", "M", "Firme e decidida."), ("Charon", "M", "Grave e informativa."), ("Puck", "M", "Animada e para cima."),
    ("Fenrir", "M", "Empolgada, com energia."), ("Algieba", "M", "Macia e sem pressa."), ("Umbriel", "M", "Tranquila, de boa."),
    ("Iapetus", "M", "Clara e neutra."), ("Kore", "F", "Firme e segura."), ("Leda", "F", "Jovem e leve."),
    ("Aoede", "F", "Leve e arejada."), ("Despina", "F", "Macia e fluida."), ("Achernar", "F", "Suave e delicada."),
    ("Vindemiatrix", "F", "Calma e gentil."), ("Sulafat", "F", "Calorosa e próxima."),
]
VOICE_NAMES = {v[0] for v in VOICES}

_resume: dict[str, str] = {}   # sessao da Aura -> handle de retomada do Gemini (continuidade se a conexao cair)


def available() -> bool:
    return bool(api_key())


def status() -> dict:
    return {"available": available(), "model": LIVE_MODEL,
            "voices": [{"id": n, "name": n, "gender": g, "desc": d} for n, g, d in VOICES]}


def _declarations() -> list:
    decls = []
    for t in active_tools():
        params = t.schema()["function"]["parameters"]
        kw = {"parameters_json_schema": params} if params.get("properties") else {}
        decls.append(types.FunctionDeclaration(name=t.name, description=t.description, **kw))
    return [types.Tool(function_declarations=decls)] if decls else []


def _instructions(sid: str, s: "brain.Session") -> str:
    recent = [m for m in conversations.messages(sid) if m["role"] in ("user", "assistant")][-12:]
    history = "\n".join(f"{'Usuario' if m['role'] == 'user' else 'Voce'}: {m['content'][:300]}" for m in recent)
    # na voz ao vivo nao da para buscar antes de cada frase: leva os fatos mais recentes sobre o usuario
    known = memory.list_items("fato", limit=25)
    facts_txt = "\n".join(f"- {f['content']}" for f in known)
    from .selfinfo import now_line
    return (settings.system_prompt(s.ctx) + "\n" + now_line()
            + "\n\nVoce esta numa conversa POR VOZ em tempo real: fale de forma natural e curta, sem listas nem markdown."
            + " Antes de usar uma ferramenta demorada, avise em uma frase curta o que vai fazer."
            + (f"\n\nO que voce sabe sobre o usuario (memoria; para outras coisas use buscar_memoria):\n{facts_txt}" if known else "")
            + (f"\n\nConversa ate agora:\n{history}" if history else ""))


def _config(sid: str, s: "brain.Session") -> types.LiveConnectConfig:
    cfg = settings.get()
    voice = cfg.get("live_voice") if cfg.get("live_voice") in VOICE_NAMES else "Orus"
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=_instructions(sid, s),
        tools=_declarations(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        session_resumption=types.SessionResumptionConfig(handle=_resume.get(sid)),
    )


def _wav(pcm: bytes, rate: int = 24000) -> bytes:
    """PCM 16-bit mono -> WAV (o navegador toca direto)."""
    import struct
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


async def speak(text: str, voice: str | None = None, timeout: float = 45) -> bytes:
    """Le um texto em voz alta com a voz do Gemini (o mesmo modelo do Gemini Live, so como leitor).
    Usado na saudacao, no teste de voz e nas respostas faladas quando o motor e Gemini Live."""
    voice = voice if voice in VOICE_NAMES else (settings.get().get("live_voice") if settings.get().get("live_voice") in VOICE_NAMES else "Orus")
    config = types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        system_instruction=("Voce e um leitor de texto. Leia em voz alta, de forma natural, EXATAMENTE o texto que receber, "
                            "palavra por palavra, no idioma em que ele esta. Nao responda, nao comente, nao acrescente nada."),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice))),
    )
    client = genai.Client(api_key=api_key(), http_options=types.HttpOptions(api_version="v1beta"))
    pcm = bytearray()

    async def run():
        async with client.aio.live.connect(model=LIVE_MODEL, config=config) as session:
            await session.send_client_content(turns=types.Content(role="user", parts=[types.Part(text=text[:3000])]),
                                              turn_complete=True)
            async for m in session.receive():
                sc = m.server_content
                if sc and sc.model_turn:
                    for part in sc.model_turn.parts or []:
                        if part.inline_data and part.inline_data.data:
                            pcm.extend(part.inline_data.data)
                if sc and sc.turn_complete:
                    return

    await asyncio.wait_for(run(), timeout)
    if not pcm:
        raise RuntimeError("o Gemini nao devolveu audio")
    return _wav(bytes(pcm))


async def handle(sock: WebSocket):
    await sock.accept()
    if not available():
        await sock.send_json({"type": "error", "detail": "chave do Gemini nao configurada (Configuracoes -> Motor)"})
        await sock.close()
        return
    try:
        start = await sock.receive_json()
    except WebSocketDisconnect:
        return
    sid = str(start.get("session") or "")[:80]
    s = brain.get_session(sid)
    workdir.use_conversation(sid, start.get("project"))   # conversa de projeto = pasta do projeto
    s.ctx.update({k: str(v)[:120] for k, v in (start.get("context") or {}).items()})
    pending: dict = {"confirm": None}
    turn = {"in": [], "out": [], "trace": []}

    try:
        # a Live API so existe em v1beta/v1alpha (o SDK 3.x usa v1 por padrao, que da 404)
        client = genai.Client(api_key=api_key(), http_options=types.HttpOptions(api_version="v1beta"))
        async with client.aio.live.connect(model=LIVE_MODEL, config=_config(sid, s)) as session:
            await sock.send_json({"type": "ready", "model": LIVE_MODEL})

            async def upstream():
                while True:
                    msg = await sock.receive()
                    if msg["type"] == "websocket.disconnect":
                        return
                    if msg.get("bytes"):
                        await session.send_realtime_input(
                            audio=types.Blob(data=msg["bytes"], mime_type="audio/pcm;rate=16000"))
                        continue
                    cmd = json.loads(msg.get("text") or "{}")
                    if cmd.get("type") == "text" and cmd.get("text"):
                        turn["in"].append(str(cmd["text"])[:2000])      # pedido ja transcrito vai pro historico
                        await session.send_realtime_input(text=str(cmd["text"])[:2000])
                    elif cmd.get("type") == "end":
                        await session.send_realtime_input(audio_stream_end=True)
                    elif cmd.get("type") == "confirm" and pending["confirm"] and not pending["confirm"].done():
                        pending["confirm"].set_result(bool(cmd.get("approve")))
                    elif cmd.get("type") == "stop":
                        return

            def save_turn():
                user, bot = "".join(turn["in"]).strip(), "".join(turn["out"]).strip()
                if user:
                    conversations.add(sid, "user", user)
                    s.messages.append({"role": "user", "content": user})
                    facts.learn_later(sid, user)          # aprende fatos tambem no modo Live
                if bot:
                    conversations.add(sid, "assistant", bot, turn["trace"] or None)
                    s.messages.append({"role": "assistant", "content": bot})
                turn["in"], turn["out"], turn["trace"] = [], [], []

            async def run_call(fc) -> types.FunctionResponse:
                name, args = fc.name, dict(fc.args or {})
                t = REGISTRY.get(name)
                acc: list = []
                actions.current_conv.set(sid)
                actions.turn_actions.set(acc)
                if t and t.sensitive:
                    # o modelo NAO confirma sozinho: espera o clique do usuario
                    pending["confirm"] = asyncio.get_running_loop().create_future()
                    conversations.add(sid, "notice", f"Autorizacao solicitada: {name} {args}")
                    await sock.send_json({"type": "confirm", "action": {"tool": name, "args": args}})
                    approve = await pending["confirm"]
                    conversations.add(sid, "notice", "Autorizado" if approve else "Recusado")
                    result = await run_tool(name, args) if approve else \
                        "O usuario NAO autorizou esta acao. Nao tente de novo sem ele pedir."
                else:
                    await sock.send_json({"type": "tool", "tool": name, "slow": bool(t and t.slow)})
                    result = await run_tool(name, args)
                turn["trace"].append(name)
                for a in acc:      # cada acao feita ganha um botao Desfazer na tela
                    await sock.send_json({"type": "action", **a})
                return types.FunctionResponse(id=fc.id, name=name, response={"result": brain._clip(result)})

            async def downstream():
                while True:
                    async for m in session.receive():
                        upd = m.session_resumption_update
                        if upd and upd.resumable and upd.new_handle:
                            _resume[sid] = upd.new_handle
                        if m.go_away:
                            await sock.send_json({"type": "reconnect"})   # o navegador reconecta com o handle
                        sc = m.server_content
                        if sc:
                            if sc.model_turn:
                                for part in sc.model_turn.parts or []:
                                    if part.inline_data and part.inline_data.data:
                                        await sock.send_bytes(part.inline_data.data)
                            if sc.input_transcription and sc.input_transcription.text:
                                turn["in"].append(sc.input_transcription.text)
                                await sock.send_json({"type": "input", "text": sc.input_transcription.text})
                            if sc.output_transcription and sc.output_transcription.text:
                                turn["out"].append(sc.output_transcription.text)
                                await sock.send_json({"type": "output", "text": sc.output_transcription.text})
                            if sc.interrupted:
                                await sock.send_json({"type": "interrupted"})
                            if sc.turn_complete:
                                save_turn()
                                await sock.send_json({"type": "turn_complete"})
                        if m.tool_call and m.tool_call.function_calls:
                            responses = [await run_call(fc) for fc in m.tool_call.function_calls]
                            await session.send_tool_response(function_responses=responses)

            up, down = asyncio.create_task(upstream()), asyncio.create_task(downstream())
            done, rest = await asyncio.wait({up, down}, return_when=asyncio.FIRST_COMPLETED)
            for task in rest:
                task.cancel()
            save_turn()
            for task in done:
                if task.exception() and not isinstance(task.exception(), WebSocketDisconnect):
                    raise task.exception()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning("Gemini Live falhou: %s", e)
        _resume.pop(sid, None)          # handle pode ter expirado; a proxima tentativa comeca do zero
        try:
            await sock.send_json({"type": "error", "detail": str(e)[:300]})
            await sock.close()
        except Exception:
            pass
