"""Ponte de comandos para o agente do Windows (desligar, reiniciar, Wi-Fi...).

O agente BUSCA os comandos aqui (long-poll com chave secreta) em vez de receber conexoes:
nenhuma porta nova fica aberta para isso. So comandos de uma lista fechada existem, e os
perigosos so chegam aqui DEPOIS do clique em Autorizar (ferramentas sensitive=True).
"""
import asyncio
import hmac
import itertools
import os
import time

TOKEN = os.getenv("HOST_AGENT_TOKEN", "")
DRYRUN = os.getenv("AURA_POWER_DRYRUN", "0") == "1"
ALLOWED = {"shutdown", "restart", "sleep", "lock", "abort", "wifi_off", "wifi_on",
           # controle do computador
           "windows", "focus", "open", "open_in_tab", "ui", "click", "type", "keys", "screenshot", "media",
           "aura_stop"}    # botao "Encerrar A.U.R.A." (para os containers e o agente)
DRY_CMDS = {"shutdown", "restart", "sleep", "lock", "abort", "wifi_off", "wifi_on", "click", "type", "keys", "media",
            "aura_stop"}

_queue: asyncio.Queue = asyncio.Queue()
_waiting: dict[int, asyncio.Future] = {}
_ids = itertools.count(1)
_last_seen = 0.0
pending_shutdown: dict = {}          # desligamento/reinicio agendado (para o aviso com contagem na tela)


def token_ok(given: str | None) -> bool:
    return bool(TOKEN) and hmac.compare_digest(TOKEN, given or "")


def agent_online() -> bool:
    return time.time() - _last_seen < 40


def touch():
    global _last_seen
    _last_seen = time.time()


async def next_command(timeout: float = 25) -> dict | None:
    touch()
    try:
        cmd = await asyncio.wait_for(_queue.get(), timeout)
    except asyncio.TimeoutError:
        return None
    touch()
    return cmd


def deliver(cmd_id: int, ok: bool, output: str):
    touch()
    fut = _waiting.pop(cmd_id, None)
    if fut and not fut.done():
        fut.set_result((ok, output))


async def run(cmd: str, timeout: float = 20, **args) -> tuple[bool, str]:
    """Manda um comando da lista fechada e espera o agente responder."""
    if cmd not in ALLOWED:
        return False, "comando nao permitido"
    if not agent_online():
        return False, "o agente do Windows nao esta rodando (rode host-agent\\start.ps1)"
    cid = next(_ids)
    fut = asyncio.get_running_loop().create_future()
    _waiting[cid] = fut
    # simulacao vale so para o que AGE (energia, Wi-Fi, clicar/digitar/teclas); ler e abrir rodam de verdade
    await _queue.put({"id": cid, "cmd": cmd, "args": args, "dry": DRYRUN and cmd in DRY_CMDS})
    try:
        return await asyncio.wait_for(fut, timeout)
    except asyncio.TimeoutError:
        _waiting.pop(cid, None)
        return False, "o agente nao respondeu a tempo"
