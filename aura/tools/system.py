"""Energia e Wi-Fi do PC, executados pelo agente do Windows.

Confirmacao real: desligar, reiniciar, suspender e mexer no Wi-Fi sao sensitive=True, entao
o modelo NAO consegue executa-los sozinho: a Aura para e espera o clique em Autorizar.
Desligar/reiniciar ainda tem 30 s de contagem com botao Cancelar.
"""
import time

from .. import hostbridge
from . import tool

DELAY = 30


def _ready() -> bool:
    return hostbridge.agent_online()


async def _power(cmd: str, label: str) -> str:
    ok, out = await hostbridge.run(cmd, delay=DELAY)
    if not ok:
        return f"Nao consegui {label}: {out}"
    hostbridge.pending_shutdown.update({"cmd": cmd, "label": label, "at": time.time() + DELAY})
    return (f"O PC vai {label} em {DELAY} segundos. Avise o usuario que ele pode cancelar dizendo 'cancela' "
            f"ou no botao Cancelar da tela. ({out})")


@tool("Desliga o computador (com 30 segundos para cancelar).", sensitive=True, available=_ready)
async def desligar_pc() -> str:
    return await _power("shutdown", "desligar")


@tool("Reinicia o computador (com 30 segundos para cancelar).", sensitive=True, available=_ready)
async def reiniciar_pc() -> str:
    return await _power("restart", "reiniciar")


@tool("Cancela um desligamento ou reinicio agendado.", available=_ready)
async def cancelar_desligamento() -> str:
    ok, out = await hostbridge.run("abort")
    hostbridge.pending_shutdown.clear()
    return "Cancelado: o PC nao vai mais desligar/reiniciar." if ok else f"Nao consegui cancelar: {out}"


@tool("Suspende o computador (modo de espera).", sensitive=True, available=_ready)
async def suspender_pc() -> str:
    ok, out = await hostbridge.run("sleep")
    return f"Suspendendo o PC. ({out})" if ok else f"Nao consegui suspender: {out}"


@tool("Bloqueia a tela do computador (volta com a senha do Windows).", available=_ready)
async def bloquear_tela() -> str:
    ok, out = await hostbridge.run("lock")
    return "Tela bloqueada." if ok else f"Nao consegui bloquear: {out}"


@tool(
    "Desconecta ou reconecta o Wi-Fi do computador.",
    {"acao": {"type": "string", "enum": ["desconectar", "conectar"], "description": "O que fazer com o Wi-Fi"}},
    sensitive=True, available=_ready,
)
async def wifi(acao: str) -> str:
    ok, out = await hostbridge.run("wifi_off" if acao == "desconectar" else "wifi_on")
    return f"Wi-Fi: {out}" if ok else f"Nao consegui mexer no Wi-Fi: {out}"
