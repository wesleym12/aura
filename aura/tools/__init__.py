"""Registro de ferramentas que o modelo local pode chamar.

Para criar uma ferramenta nova, decore uma funcao com @tool:
- sensitive=True: acoes que exigem confirmacao do usuario (enviar email, destrancar porta...)
- slow=True: tarefas demoradas; a Aura avisa na hora que comecou ("vou pesquisar, um momento")
- available=funcao: diz se a ferramenta pode ser usada agora (ex.: precisa de login)

Plugins: qualquer arquivo .py na pasta plugins/ do projeto e carregado no inicio de cada
conversa nova. Basta usar `from aura.tools import tool` nele.
"""
import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("uvicorn.error")
PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"


@dataclass
class Tool:
    name: str
    description: str
    params: dict
    fn: Callable[..., Any]
    sensitive: bool = False
    slow: bool = False
    available: Callable[[], bool] | None = None
    origin: str = "nativa"          # nativa | plugin:<arquivo>

    def is_available(self) -> bool:
        try:
            return self.available() if self.available else True
        except Exception:
            return False

    def schema(self) -> dict:
        props = {k: {kk: vv for kk, vv in v.items() if kk != "x-optional"} for k, v in self.params.items()}
        required = [k for k, v in self.params.items() if not v.get("x-optional")]
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": required},
            },
        }


REGISTRY: dict[str, Tool] = {}
_loading_plugin: str | None = None


def tool(description: str, params: dict | None = None, sensitive: bool = False, slow: bool = False,
         available: Callable[[], bool] | None = None):
    """params: {"nome": {"type": "string", "description": "...", "x-optional": True}}"""

    def deco(fn):
        origin = f"plugin:{_loading_plugin}" if _loading_plugin else "nativa"
        REGISTRY[fn.__name__] = Tool(fn.__name__, description, params or {}, fn, sensitive, slow, available, origin)
        return fn

    return deco


def active_tools() -> list[Tool]:
    return [t for t in REGISTRY.values() if t.is_available()]


async def run_tool(name: str, args: dict) -> str:
    t = REGISTRY.get(name)
    if not t:
        return f"Erro: ferramenta '{name}' nao existe."
    if not t.is_available():
        return f"Erro: '{name}' nao esta disponivel agora."
    try:
        result = t.fn(**(args or {}))
        if inspect.isawaitable(result):
            result = await result
        return str(result)
    except TypeError as e:
        return f"Erro nos argumentos de {name}: {e}"
    except Exception as e:  # a ferramenta falhou; devolve o erro ao modelo
        return f"Erro ao executar {name}: {e}"


# plugins antigos escritos com `from jarvis.tools import tool` continuam funcionando
import aura as _aura  # noqa: E402
sys.modules.setdefault("jarvis", _aura)
sys.modules.setdefault("jarvis.tools", sys.modules[__name__])

_plugin_mtimes: dict[str, float] = {}
plugin_errors: dict[str, str] = {}      # arquivo -> erro ao carregar (a tela mostra)


def load_plugins():
    """(Re)carrega plugins novos ou alterados e remove os que foram apagados."""
    global _loading_plugin
    files = {p.name: p for p in PLUGINS_DIR.glob("*.py") if not p.name.startswith("_")} if PLUGINS_DIR.is_dir() else {}
    for gone in set(_plugin_mtimes) - set(files):
        for name in [n for n, t in REGISTRY.items() if t.origin == f"plugin:{gone}"]:
            del REGISTRY[name]
        del _plugin_mtimes[gone]
        plugin_errors.pop(gone, None)
        log.info("Plugin removido: %s", gone)
    for fname, path in files.items():
        mtime = path.stat().st_mtime
        if _plugin_mtimes.get(fname) == mtime:
            continue
        for name in [n for n, t in REGISTRY.items() if t.origin == f"plugin:{fname}"]:
            del REGISTRY[name]
        _loading_plugin = fname
        try:
            spec = importlib.util.spec_from_file_location(f"aura_plugin_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = mod
            spec.loader.exec_module(mod)
            plugin_errors.pop(fname, None)
            log.info("Plugin carregado: %s", fname)
        except Exception as e:
            plugin_errors[fname] = f"{type(e).__name__}: {e}"[:300]
            log.error("Plugin %s com erro: %s", fname, e)
        finally:
            _loading_plugin = None
        _plugin_mtimes[fname] = mtime


def load_all():
    # importa os modulos para registrar as ferramentas
    from . import (agenda, agents, basic, config_tool, desktop, files, google_apps, home, images,  # noqa: F401
                   instructions, memory, music, schedules, system)
    load_plugins()
