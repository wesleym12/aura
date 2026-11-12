"""Leitura de documentos e imagens: transforma PDF, Word, Excel, PowerPoint e imagens em texto
que qualquer modelo (local ou na nuvem) consegue usar.

- Documentos: texto extraido direto do arquivo (pypdf, python-docx, openpyxl, python-pptx).
- Imagens: descritas por um modelo com visao. Primeiro o local (Ollama, VISION_MODEL);
  se ele nao estiver instalado e houver chave do Gemini, usa o Gemini (VISION_CLOUD_MODEL).
  PDF escaneado (sem texto) tem as primeiras paginas lidas como imagem.
"""
import base64
import io
import logging
import os
from pathlib import Path

import httpx

from .config import OLLAMA_URL

log = logging.getLogger("uvicorn.error")

VISION_MODEL = os.getenv("VISION_MODEL", "qwen3-vl:2b-instruct")
VISION_CLOUD_MODEL = os.getenv("VISION_CLOUD_MODEL", "gemini-flash-latest")
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DOC_EXT = {".pdf", ".docx", ".xlsx", ".xlsm", ".pptx"}
MAX_CHARS = 20000
MAX_SHEET_ROWS = 200
SCAN_PAGES = 3                      # PDF escaneado: quantas paginas ler como imagem

DEFAULT_PROMPT = ("Descreva esta imagem em portugues do Brasil, de forma objetiva. Transcreva TODO o texto visivel "
                  "(mantendo numeros, valores e datas exatamente). Se for documento, tabela, grafico ou print de tela, "
                  "explique a estrutura e os dados principais.")


def kind(p: Path) -> str | None:
    s = p.suffix.lower()
    return "image" if s in IMAGE_EXT else "doc" if s in DOC_EXT else None


# ---------------- documentos ----------------
def _pdf(p: Path) -> tuple[str, list[bytes]]:
    from pypdf import PdfReader
    r = PdfReader(str(p))
    parts, total = [], 0
    for i, page in enumerate(r.pages, 1):
        t = (page.extract_text() or "").strip()
        if t:
            parts.append(f"--- pagina {i} ---\n{t}")
            total += len(t)
        if total > MAX_CHARS:
            break
    text = "\n".join(parts)
    scans: list[bytes] = []
    if len(text) < 40 * max(1, min(len(r.pages), 3)):      # quase sem texto: provavelmente escaneado
        for page in r.pages[:SCAN_PAGES]:
            imgs = sorted(page.images, key=lambda im: len(im.data), reverse=True)
            if imgs:
                scans.append(imgs[0].data)
    header = f"[PDF com {len(r.pages)} pagina(s)]\n"
    return header + text, scans


def _docx(p: Path) -> str:
    import docx
    d = docx.Document(str(p))
    out = [para.text for para in d.paragraphs if para.text.strip()]
    for ti, table in enumerate(d.tables, 1):
        out.append(f"--- tabela {ti} ---")
        for row in table.rows:
            out.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n".join(out)


def _xlsx(p: Path) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(str(p), read_only=True, data_only=True)
    out = []
    for ws in wb.worksheets:
        out.append(f"--- planilha '{ws.title}' ---")
        n = 0
        for row in ws.iter_rows(values_only=True):
            if all(v is None for v in row):
                continue
            out.append(" | ".join("" if v is None else str(v) for v in row).rstrip(" |"))
            n += 1
            if n >= MAX_SHEET_ROWS:
                out.append(f"[...mais linhas; mostrando as primeiras {MAX_SHEET_ROWS}]")
                break
    wb.close()
    return "\n".join(out)


def _pptx(p: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(p))
    out = []
    for i, slide in enumerate(prs.slides, 1):
        texts = [sh.text_frame.text.strip() for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]
        out.append(f"--- slide {i} ---\n" + "\n".join(texts))
    return "\n".join(out)


def _clip(text: str, limit: int = MAX_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + "\n[...documento maior, cortado]"


# ---------------- imagens ----------------
def _ollama_has(model: str) -> bool:
    try:
        tags = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3).json().get("models", [])
        return any(m.get("name") == model or m.get("name") == f"{model}:latest" for m in tags)
    except (httpx.HTTPError, ValueError):
        return False


def _gemini_key() -> str:
    from . import secrets
    return secrets.get("gemini") or os.getenv("GOOGLE_API_KEY", "")


def _shrink(data: bytes, max_side: int = 1280) -> tuple[bytes, str]:
    """Reduz imagens grandes (mais rapido e cabe no contexto do modelo local)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im = im.convert("RGB")
        if max(im.size) > max_side:
            im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
        return buf.getvalue(), "image/jpeg"
    except Exception:
        return data, "image/png"


def see(data: bytes, question: str | None = None) -> str:
    """Descreve/responde sobre uma imagem. Local primeiro; Gemini se nao houver modelo local."""
    img, mime = _shrink(data)
    prompt = DEFAULT_PROMPT + (f"\nDe atencao especial ao que o usuario quer saber: {question[:500]}" if question else "")
    if _ollama_has(VISION_MODEL):
        r = httpx.post(f"{OLLAMA_URL}/api/chat", timeout=240, json={
            "model": VISION_MODEL, "stream": False, "keep_alive": "5m",
            "think": False,                                  # sem raciocinio escondido: bem mais rapido
            "options": {"temperature": 0.2, "num_ctx": 8192, "num_predict": 900},
            "messages": [{"role": "user", "content": prompt, "images": [base64.b64encode(img).decode()]}]})
        r.raise_for_status()
        from .textutil import strip_reasoning
        return strip_reasoning(r.json().get("message", {}).get("content", "")).strip()
    key = _gemini_key()
    if key:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=key)
        resp = client.models.generate_content(model=VISION_CLOUD_MODEL, contents=[
            types.Part.from_bytes(data=img, mime_type=mime), prompt])
        return (resp.text or "").strip()
    raise RuntimeError(f"nenhum modelo de visao disponivel (instale o {VISION_MODEL} no Ollama ou coloque a chave do Gemini)")


# ---------------- entrada unica ----------------
def read(p: Path, question: str | None = None) -> str:
    """Texto de um documento ou descricao de uma imagem (para mandar ao modelo)."""
    k = kind(p)
    if k == "image":
        return see(p.read_bytes(), question)
    s = p.suffix.lower()
    if s == ".pdf":
        text, scans = _pdf(p)
        if scans:
            seen = []
            for i, data in enumerate(scans, 1):
                try:
                    seen.append(f"--- pagina {i} (lida como imagem) ---\n{see(data, question)}")
                except Exception as e:
                    seen.append(f"--- pagina {i}: nao consegui ler a imagem ({e}) ---")
            text += "\n[PDF escaneado: paginas lidas como imagem]\n" + "\n".join(seen)
        return _clip(text)
    if s == ".docx":
        return _clip(_docx(p))
    if s in (".xlsx", ".xlsm"):
        return _clip(_xlsx(p))
    if s == ".pptx":
        return _clip(_pptx(p))
    raise ValueError(f"formato {s or '?'} nao suportado para leitura")
