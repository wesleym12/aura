"""Servico de voz da Aura.

- WebSocket /ws: o navegador manda audio do microfone (PCM 16 kHz, int16 mono).
  Com a escuta ligada, o Whisper procura a palavra de ativacao ("Aura") no comeco do que
  voce fala; depois grava ate voce parar de falar e devolve o texto transcrito.
- POST /tts: transforma a resposta em fala (WAV).
"""
import asyncio
import difflib
import io
import json
import logging
import os
import re
import unicodedata
import wave
from pathlib import Path

import httpx
import numpy as np
import webrtcvad
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from faster_whisper import WhisperModel
from kokoro_onnx import Kokoro
from piper import PiperVoice
from piper.config import SynthesisConfig
from pydantic import BaseModel

log = logging.getLogger("uvicorn.error")

SR = 16000
VAD_FRAME = 480                   # 30 ms para o webrtcvad
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "small")
TTS_VOICE = os.getenv("TTS_VOICE", "pf_dora")
TTS_SPEED = float(os.getenv("TTS_SPEED", "1.05"))
END_SILENCE = float(os.getenv("END_SILENCE", "0.9"))   # segundos de silencio que encerram a fala
LANG_MIN_PROB = float(os.getenv("LANG_MIN_PROB", "0.6"))  # certeza minima para trocar de lingua

log.info("Carregando Whisper '%s'...", WHISPER_MODEL)
whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8")
kokoro = Kokoro("/models/kokoro-v1.0.onnx", "/models/voices-v1.0.bin")
log.info("Voz pronta.")

app = FastAPI(title="Aura Voice")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8765", "http://127.0.0.1:8765"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# frases que o Whisper "inventa" em trechos sem fala (finais de video do YouTube, legendas...)
JUNK = {"legendas pela comunidade amara.org", "obrigado", "obrigada", "tchau", "e ai", "legenda adriana zanotto",
        "inscreva-se no canal", "sous-titres realises par la communaute d'amara.org", "bye", "thank you", "thanks", "you"}
JUNK_PARTS = ("thanks for watching", "thank you for watching", "next video", "subscribe", "amara.org", "legendas pela",
              "inscreva-se", "obrigado por assistir", "ate o proximo video", "ate a proxima", "like and subscribe",
              "see you next time", "legenda por", "transcricao por")
MIN_RMS = float(os.getenv("MIN_RMS", "0.004"))         # audio mais fraco que isso = silencio/ruido (nao transcreve)


def _is_junk(text: str) -> bool:
    t = norm(text)
    return not t or t in {norm(j) for j in JUNK} or any(p in t for p in (norm(x) for x in JUNK_PARTS))


def transcribe(pcm: np.ndarray, hint: str | None = None, follow: bool = False) -> tuple[str, str]:
    """Texto + lingua. Padrao: portugues fixo. Com follow=True o Whisper descobre a lingua; se nao tiver
    certeza, assume portugues. Trechos sem fala de verdade e frases-fantasma do Whisper sao descartados."""
    audio = pcm.astype(np.float32) / 32768.0
    if not len(audio) or float(np.sqrt(np.mean(audio ** 2))) < MIN_RMS:
        return "", "pt"                                   # so ruido/silencio: o Whisper inventaria algo
    # o "hint" ensina a grafia da palavra de ativacao. Vai como contexto (frase completa),
    # nao como inicio do texto: senao o Whisper acha que a palavra ja foi dita e a omite.
    prompt = f"Conversa com o assistente {hint}." if hint else "Conversa em português do Brasil com o assistente."

    def run(language):
        segs, info = whisper.transcribe(audio, language=language, beam_size=1, vad_filter=True,
                                        condition_on_previous_text=False, initial_prompt=prompt,
                                        no_speech_threshold=0.6, log_prob_threshold=-1.0)
        # segmento com cara de "nao havia fala" (alta chance de silencio + baixa confianca) fica de fora
        good = [s.text.strip() for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        return " ".join(good).strip(), info

    lang = "pt"
    if follow:
        text, info = run(None)
        if info.language != "pt" and info.language_probability >= LANG_MIN_PROB:
            lang = info.language
        elif info.language != "pt":
            text, _ = run("pt")          # pouca certeza (frase curta): fica no portugues
    else:
        text, _ = run("pt")
    if _is_junk(text):
        log.info("descartado (frase-fantasma do Whisper): %r", text)
        return "", lang
    return text, lang


class Recorder:
    """Grava a fala e decide quando ela terminou.

    Modo normal: depois da ativacao/botao. Modo 'spot' (palavra livre): fica de
    plantao, guarda so um pouquinho de audio antes da fala comecar, e devolve
    cada trecho falado para o Whisper procurar a palavra de ativacao."""

    def __init__(self, end_silence: float = END_SILENCE, max_sec: float = 20, nospeech_sec: float | None = 5,
                 spot: bool = False):
        self.vad = webrtcvad.Vad(2)
        self.end_silence, self.max_sec, self.nospeech_sec, self.spot = end_silence, max_sec, nospeech_sec, spot
        self.chunks: list[np.ndarray] = []
        self.rest = np.zeros(0, np.int16)
        self.speech = False
        self.silence = 0
        self.total = 0

    def feed(self, pcm: np.ndarray) -> str | None:
        self.chunks.append(pcm)
        self.total += len(pcm)
        if self.spot and not self.speech and self.total > SR * .5:
            # ainda ninguem falou: mantem so os ultimos ~0,5 s (inicio da palavra)
            keep = np.concatenate(self.chunks)[-int(SR * .5):]
            self.chunks, self.total = [keep], len(keep)
        data = np.concatenate([self.rest, pcm])
        n = len(data) // VAD_FRAME
        for i in range(n):
            frame = data[i * VAD_FRAME:(i + 1) * VAD_FRAME]
            if self.vad.is_speech(frame.tobytes(), SR):
                self.speech, self.silence = True, 0
            else:
                self.silence += VAD_FRAME
        self.rest = data[n * VAD_FRAME:]
        if self.speech and self.silence >= SR * self.end_silence:
            return "done"
        if not self.speech and self.nospeech_sec and self.total >= SR * self.nospeech_sec:
            return "nospeech"
        if self.total >= SR * self.max_sec:
            return "done"
        return None

    def audio(self) -> np.ndarray:
        return np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.int16)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.lower())
    return re.sub(r"[^a-z0-9 ]", "", "".join(c for c in s if not unicodedata.combining(c))).strip()


def match_wake(text: str, word: str) -> tuple[bool, str]:
    """A palavra de ativacao aparece no comeco da frase? Devolve (achou, resto da frase).
    Tolera pequenas diferencas de escrita ("Aura" -> "Áurea", "Sexta-feira" -> "Sexta feira")."""
    # compara sem espacos/hifens: "Sexta-feira" == "Sexta feira" == "sextafeira"
    target = norm(word.replace("-", " ")).replace(" ", "")
    pairs = [(tok, norm(tok.replace("-", " ")).replace(" ", "")) for tok in text.split()]
    pairs = [(o, n) for o, n in pairs if n]
    # palavra curta (ex.: "Aura"): exige mais semelhanca e a mesma inicial, senao "aula", "Laura", "ouro" acordariam
    short = len(target) <= 5
    best = (0.0, 0)
    for i in range(0, min(4, len(pairs))):                  # so nas primeiras palavras
        for j in range(i + 1, min(i + 5, len(pairs) + 1)):  # janela de 1 a 4 palavras
            cand = "".join(n for _, n in pairs[i:j])
            if short and cand[:1] != target[:1]:
                continue
            ratio = difflib.SequenceMatcher(None, cand, target).ratio()
            if ratio > best[0]:
                best = (ratio, j)
    if best[0] >= (.88 if short else .75):
        return True, " ".join(o for o, _ in pairs[best[1]:]).lstrip(",.!?;: ")
    return False, ""


@app.get("/health")
def health():
    return {"ok": True, "wake": "whisper", "stt": WHISPER_MODEL, "tts": TTS_VOICE}


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    wake_on = False
    follow = False                           # a voz te segue: so detecta a lingua se a tela pedir (padrao: portugues)
    word = "Aura"
    spotter: Recorder | None = None          # trechos falados que o Whisper confere se comecam com a palavra
    rec: Recorder | None = None
    try:
        while True:
            msg = await sock.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("text"):
                cmd = json.loads(msg["text"])
                if cmd.get("cmd") == "wake":
                    wake_on = bool(cmd.get("enabled"))
                    word = (cmd.get("word") or word).strip() or "Aura"
                    follow = bool(cmd.get("follow", follow))
                    spotter = Recorder(.6, 8, None, spot=True)
                elif cmd.get("cmd") == "listen":
                    # botao do microfone, ou modo conversa (timeout = quanto tempo esperar alguem falar)
                    follow = bool(cmd.get("follow", follow))
                    timeout = float(cmd.get("timeout") or 5)
                    rec = Recorder(nospeech_sec=min(120.0, max(2.0, timeout)), max_sec=max(20.0, timeout + 15))
                    await sock.send_json({"event": "listening", "followup": bool(cmd.get("followup"))})
                elif cmd.get("cmd") == "hold":             # segurar para falar (Ctrl+Espaco)
                    follow = bool(cmd.get("follow", follow))
                    rec = Recorder(end_silence=3600, max_sec=60, nospeech_sec=None)
                    await sock.send_json({"event": "listening", "hold": True})
                elif cmd.get("cmd") == "release" and rec is not None:
                    audio, rec = rec.audio(), None
                    if len(audio) < SR * .3:
                        await sock.send_json({"event": "no_speech"})
                        continue
                    await sock.send_json({"event": "transcribing"})
                    text, lang = await asyncio.to_thread(transcribe, audio, None, follow)
                    await sock.send_json({"event": "transcript", "text": text, "lang": lang} if text else {"event": "no_speech"})
                elif cmd.get("cmd") == "cancel":
                    rec = None
                continue

            pcm = np.frombuffer(msg["bytes"], dtype=np.int16)
            if rec is not None:
                if rec.end_silence > 600:      # segurando a tecla: so grava, quem encerra e o "release"
                    rec.chunks.append(pcm)
                    if sum(len(c) for c in rec.chunks) > SR * 60:
                        rec.chunks = rec.chunks[-int(SR * 60 / 1280):]
                    continue
                state = rec.feed(pcm)
                if state is None:
                    continue
                audio, rec = rec.audio(), None
                if state == "nospeech":
                    await sock.send_json({"event": "no_speech"})
                    continue
                await sock.send_json({"event": "transcribing"})
                text, lang = await asyncio.to_thread(transcribe, audio, None, follow)
                await sock.send_json({"event": "transcript", "text": text, "lang": lang} if text else {"event": "no_speech"})
                spotter = Recorder(.6, 8, None, spot=True)
            elif wake_on and spotter is not None:
                # escuta continua: cada trecho falado vai para o Whisper, que confere se comeca com a palavra
                if spotter.feed(pcm) is None:
                    continue
                audio, spotter = spotter.audio(), Recorder(.6, 8, None, spot=True)
                text, lang = await asyncio.to_thread(transcribe, audio, word, follow)
                found, rest = match_wake(text, word)
                if not found:
                    log.debug("sem palavra de ativacao em: %r", text)
                    continue
                log.info("'%s' detectado em: %r", word, text)
                await sock.send_json({"event": "wake", "word": word})
                if len(rest.split()) >= 2:
                    # falou tudo de uma vez ("Aura, que horas sao?"): ja manda o pedido
                    await sock.send_json({"event": "transcript", "text": rest, "lang": lang})
                else:
                    rec = Recorder()
    except WebSocketDisconnect:
        pass


# Vozes oferecidas no menu: so as nativas do portugues do Brasil.
# (as de outras linguas continuam sendo usadas por dentro em "a voz te segue": resposta em ingles = voz nativa do ingles)
VOICES = [
    # id, nome, genero, descricao
    ("pm_alex", "Alex", "M", "Masculina, firme e clara."),
    ("pm_santa", "Santa", "M", "Masculina, grave e calma."),
    ("pf_dora", "Dora", "F", "Feminina, suave e próxima."),
]
VOICE_IDS = {v[0] for v in VOICES} & set(kokoro.get_voices())


@app.post("/stt")
async def stt(request: Request, follow: bool = False):
    """Transcreve um arquivo de audio (ogg/opus do Telegram, mp3, wav, m4a...). O Whisper decodifica sozinho."""
    data = await request.body()
    if not data or len(data) > 25 * 1024 * 1024:
        return {"text": "", "lang": "pt", "error": "audio vazio ou grande demais"}

    def run():
        from faster_whisper.audio import decode_audio
        audio = decode_audio(io.BytesIO(data), sampling_rate=SR)          # float32 16 kHz
        pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
        return transcribe(pcm, None, follow)
    text, lang = await asyncio.to_thread(run)
    return {"text": text, "lang": lang}


@app.get("/voices")
def voices():
    return [{"id": i, "name": n, "gender": g, "desc": d, "kind": "nativa"} for i, n, g, d in VOICES if i in VOICE_IDS]


class TTSIn(BaseModel):
    text: str
    voice: str | None = None
    speed: float | None = None
    lang: str | None = None     # lingua da resposta (a voz te segue); vazio/pt = voz escolhida no menu


_THINK = re.compile(r"<(think|thinking|thought|reasoning|reflection|analysis)\b[^>]*>.*?</\1\s*>", re.S | re.I)


def clean_for_speech(text: str) -> str:
    # raciocinio nunca e falado (segunda barreira; o servidor da Aura ja remove)
    text = _THINK.sub(" ", text)
    text = re.sub(r"^.*?</(think|thinking|reasoning)\s*>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<(think|thinking|reasoning)\b.*$", " ", text, flags=re.S | re.I)
    text = re.sub(r"```.*?```", " (trecho de codigo omitido) ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " link ", text)
    text = re.sub(r"[*_`#>|]+", " ", text)
    # emojis e simbolos nao sao lidos em voz alta
    text = "".join(ch for ch in text if unicodedata.category(ch) not in ("So", "Sk", "Cs") and not 0xFE00 <= ord(ch) <= 0xFE0F)
    return re.sub(r"\s+", " ", text).strip()[:1500]


# ---------- a voz te segue: uma voz por lingua ----------
# Kokoro fala estas linguas (codigo espeak, voz masculina, voz feminina). As demais vao para o Piper.
KOKORO_LANGS = {
    "pt": ("pt-br", "pm_alex", "pf_dora"), "en": ("en-gb", "bm_george", "bf_emma"),
    "es": ("es", "em_alex", "ef_dora"), "fr": ("fr-fr", "ff_siwis", "ff_siwis"),
    "it": ("it", "im_nicola", "if_sara"), "hi": ("hi", "hm_omega", "hf_alpha"),
}
GENDER = {i: g for i, _, g, _ in VOICES}


def _wav(samples: np.ndarray, sr: int) -> bytes:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def synth(text: str, voice: str | None = None, speed: float | None = None, lang: str | None = None) -> bytes:
    voice = voice if voice in VOICE_IDS else (TTS_VOICE if TTS_VOICE in VOICE_IDS else "pm_alex")
    speed = min(1.5, max(0.7, speed)) if speed else TTS_SPEED
    lang = (lang or "pt").lower()[:2]
    if lang != "pt" and lang not in KOKORO_LANGS:
        return piper_synth(text, lang, speed)              # alemao, russo, holandes... (Piper)
    code, male, female = KOKORO_LANGS.get(lang, KOKORO_LANGS["pt"])
    if lang != "pt":
        voice = male if GENDER.get(voice, "M") == "M" else female   # voz nativa da lingua, mesmo genero
    samples, sr = kokoro.create(text, voice=voice, speed=speed, lang=code)
    return _wav(samples, sr)


# ---------- Piper: ~50 linguas, voz baixada na primeira vez que a lingua aparece ----------
PIPER_DIR = Path("/models/piper")
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
_piper_index: dict | None = None
_piper_voices: dict = {}


def _piper_pick(lang: str) -> str | None:
    global _piper_index
    if _piper_index is None:
        idx = PIPER_DIR / "voices.json"
        if not idx.exists():
            PIPER_DIR.mkdir(parents=True, exist_ok=True)
            idx.write_bytes(httpx.get(f"{PIPER_BASE}/voices.json", timeout=60, follow_redirects=True).content)
        _piper_index = json.loads(idx.read_text(encoding="utf-8"))
    cands = [k for k, v in _piper_index.items() if v.get("language", {}).get("family") == lang]
    rank = {"medium": 0, "high": 1, "low": 2, "x_low": 3}
    # vozes de varios locutores (ex.: "mls") soam embaralhadas sem escolher o locutor: ficam por ultimo
    cands.sort(key=lambda k: (_piper_index[k].get("num_speakers", 1) > 1, rank.get(_piper_index[k].get("quality"), 9), k))
    return cands[0] if cands else None


def piper_synth(text: str, lang: str, speed: float) -> bytes:
    key = _piper_pick(lang)
    if not key:
        raise ValueError(f"sem voz para a lingua '{lang}'")
    if key not in _piper_voices:
        files = _piper_index[key]["files"]
        onnx = next(p for p in files if p.endswith(".onnx"))
        for rel in (onnx, onnx + ".json"):
            dst = PIPER_DIR / Path(rel).name
            if not dst.exists():
                log.info("Baixando voz Piper %s...", Path(rel).name)
                with httpx.stream("GET", f"{PIPER_BASE}/{rel}", timeout=300, follow_redirects=True) as r:
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        for chunk in r.iter_bytes():
                            f.write(chunk)
        _piper_voices[key] = PiperVoice.load(PIPER_DIR / Path(onnx).name)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        _piper_voices[key].synthesize_wav(text, w, syn_config=SynthesisConfig(length_scale=1 / speed))
    return buf.getvalue()


@app.post("/tts")
async def tts(body: TTSIn):
    text = clean_for_speech(body.text)
    if not text:
        return Response(status_code=204)
    try:
        wav = await asyncio.to_thread(synth, text, body.voice, body.speed, body.lang)
    except Exception as e:      # lingua sem voz (ou download falhou): fala com a voz padrao
        log.warning("TTS na lingua %s falhou (%s); usando a voz padrao", body.lang, e)
        wav = await asyncio.to_thread(synth, text, body.voice, body.speed, None)
    return Response(wav, media_type="audio/wav", headers={"Cache-Control": "no-store"})
