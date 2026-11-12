"""Criacao e edicao de imagens com o Nano Banana (modelos de imagem do Gemini), usando a sua chave.

- Criar: descricao em texto -> imagem.
- Editar: uma ou mais imagens da pasta de trabalho (anexo, imagem gerada antes...) + o que mudar.
As imagens ficam em <pasta de trabalho>/imagens/ e aparecem no chat (e continuam no historico).
O modelo e escolhido na API (o Google troca versoes): IMAGE_MODEL no .env fixa um, se quiser.
"""
import io
import logging
import os
import re
import time
from pathlib import Path

from . import secrets, workdir

log = logging.getLogger("uvicorn.error")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
RATIOS = {"1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "4:5", "5:4", "21:9"}
_model_cache = {"t": 0.0, "name": ""}


def api_key() -> str:
    return secrets.get("gemini") or os.getenv("GOOGLE_API_KEY", "")


def available() -> bool:
    return bool(api_key())


def _client():
    from google import genai
    return genai.Client(api_key=api_key())


def model() -> str:
    """Modelo de imagem: IMAGE_MODEL, ou o Nano Banana estavel mais novo da sua conta (preview so se nao houver)."""
    if os.getenv("IMAGE_MODEL"):
        return os.environ["IMAGE_MODEL"]
    if time.time() - _model_cache["t"] < 3600 and _model_cache["name"]:
        return _model_cache["name"]
    names = []
    try:
        client = _client()                         # guardar a referencia: o SDK fecha o cliente sem dono
        names = [m.name.removeprefix("models/") for m in client.models.list()]
    except Exception as e:
        log.warning("Nao consegui listar os modelos de imagem: %s", e)
        return "nano-banana-pro-preview" if not _model_cache["name"] else _model_cache["name"]
    banana = [n for n in names if "banana" in n]

    def rank(n: str):
        ver = tuple(int(x) for x in re.findall(r"\d+", n)) or (0,)
        return ("preview" not in n, "pro" not in n, ver)     # estavel > preview; flash (rapido/barato) > pro
    pick = max(banana, key=rank) if banana else "gemini-2.5-flash-image"
    _model_cache.update(t=time.time(), name=pick)
    return pick


def _slug(text: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:40] or "imagem"


def generate(prompt: str, ratio: str = "1:1", inputs: list[Path] | None = None) -> tuple[Path, str]:
    """Gera (ou edita, se houver imagens de entrada) e salva. Devolve (arquivo, texto que o modelo mandou junto)."""
    from google.genai import types
    from PIL import Image
    parts: list = []
    for p in inputs or []:
        parts.append(Image.open(p))
    parts.append(prompt)
    ratio = ratio if ratio in RATIOS else "1:1"
    cfg = types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"],
                                      image_config=types.ImageConfig(aspect_ratio=ratio))
    name = model()
    client = _client()
    try:
        resp = client.models.generate_content(model=name, contents=parts, config=cfg)
    except Exception as e:
        msg = str(e)
        if "free_tier" in msg and "limit: 0" in msg:
            raise RuntimeError("a chave do Gemini esta no plano gratuito, que NAO inclui geracao de imagens. Para usar o "
                               "Nano Banana, ative o faturamento do projeto em https://aistudio.google.com (Configurar "
                               "faturamento); cada imagem custa alguns centavos de dolar.") from None
        if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
            raise RuntimeError("limite de uso do Gemini atingido agora; tente daqui a pouco.") from None
        raise RuntimeError(msg[:300]) from None
    img_bytes, text = None, []
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else []) or []:
            if getattr(part, "inline_data", None) and part.inline_data.data:
                img_bytes = part.inline_data.data
            elif getattr(part, "text", None) and not getattr(part, "thought", False):
                text.append(part.text)
    if not img_bytes:
        reason = " ".join(text).strip() or str(getattr(resp, "prompt_feedback", "") or "")
        raise RuntimeError(f"o {name} nao devolveu imagem" + (f": {reason[:300]}" if reason else ""))
    out_dir = workdir.current() / "imagens"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(prompt)}.png"
    Image.open(io.BytesIO(img_bytes)).save(dst, "PNG")
    return dst, " ".join(text).strip()
