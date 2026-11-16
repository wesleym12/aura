"""Ferramentas de controle do computador: cada uma manda o comando certo ao agente do Windows.

Troca o agente por um falso (grava o comando e responde ok) e chama as ferramentas pelo mesmo caminho do chat
(run_tool). Roda dentro do container:  docker compose exec -T aura python - < tests/test_tools_host.py
"""
import asyncio

from aura import hostbridge, settings
from aura.tools import REGISTRY, load_all, run_tool

sent: list = []


async def fake_run(cmd, timeout=20, **args):
    sent.append((cmd, args))
    if cmd == "focus" and args.get("title") == "YouTube":
        return False, "nenhuma janela com 'YouTube'"
    return True, "ok"


CASES = [
    ("bloquear_tela", {}, "lock", {}),
    ("cancelar_desligamento", {}, "abort", {}),
    ("desligar_pc", {}, "shutdown", {"delay": 30}),
    ("reiniciar_pc", {}, "restart", {"delay": 30}),
    ("suspender_pc", {}, "sleep", {}),
    ("wifi", {"acao": "desconectar"}, "wifi_off", {}),
    ("wifi", {"acao": "conectar"}, "wifi_on", {}),
    ("listar_janelas", {}, "windows", {}),
    ("focar_janela", {"titulo": "Bloco de Notas"}, "focus", {"title": "Bloco de Notas"}),
    ("abrir", {"alvo": "Spotify"}, "open", {"target": "Spotify"}),
    ("ler_tela", {}, "ui", {}),
    ("clicar", {"numero": 3}, "click", {"index": 3, "name": None}),
    ("digitar", {"texto": "oi"}, "type", {"text": "oi"}),
    ("teclas", {"atalho": "ctrl+s"}, "keys", {"combo": "ctrl+s"}),
    ("youtube", {}, "open_in_tab", {"url": "https://www.youtube.com/", "match": "YouTube"}),
]


async def main():
    hostbridge.run = fake_run
    hostbridge.agent_online = lambda: True
    settings.get()["desktop_control"] = True      # so neste processo de teste
    load_all()
    fails = 0
    for tool, args, cmd, want in CASES:
        sent.clear()
        if tool not in REGISTRY:
            print(f"FALTA  {tool}"); fails += 1; continue
        out = await run_tool(tool, args)
        last = sent[-1] if sent else (None, {})
        ok = last[0] == cmd and all(last[1].get(k) == v for k, v in want.items())
        fails += not ok
        print(f"{'ok   ' if ok else 'ERRO '} {tool:<22} -> {last[0]} {last[1]}  | {out[:70]}")
    # midia: confere so o comando (os nomes das acoes vem da propria ferramenta)
    sent.clear()
    out = await run_tool("midia", {"acao": "play_pause"})
    print(("ok    " if sent and sent[-1][0] == "media" else "ERRO  ") + f"midia -> {sent[-1] if sent else None} | {out[:70]}")
    print("falhas:", fails)


asyncio.run(main())
