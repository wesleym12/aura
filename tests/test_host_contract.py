"""Contrato entre a A.U.R.A. (aura/hostbridge.py) e o agente do Windows (host-agent/agent.ps1).

Todo comando que o servidor pode mandar precisa ser tratado pelo agente, e os de controle do computador precisam
estar na lista que o agente aceita. (Ja aconteceu: "open_in_tab" existia nos dois lados, mas faltava na lista do
agente, e abrir o YouTube falhava calado.)

Roda sem dependencias: `python tests/test_host_contract.py` (ou com pytest).
"""
import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = (ROOT / "host-agent" / "agent.ps1").read_text(encoding="utf-8")


def _bridge_sets() -> tuple[set, set]:
    tree = ast.parse((ROOT / "aura" / "hostbridge.py").read_text(encoding="utf-8"))
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("ALLOWED", "DRY_CMDS"):
            found[node.targets[0].id] = set(ast.literal_eval(node.value))
    return found["ALLOWED"], found["DRY_CMDS"]


def _agent_desktop_list() -> set:
    m = re.search(r"\$script:desktopCmds\s*=\s*@\(([^)]*)\)", AGENT)
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def _switch_cases(func: str) -> set:
    """Casos "nome" { ... } do switch principal de uma funcao do agente."""
    start = AGENT.index(f"function {func}")
    end = AGENT.find("\nfunction ", start + 1)
    body = AGENT[start:end if end > 0 else None]
    return set(re.findall(r'^\s{8}"([a-z_]+)"\s*\{', body, re.M))


def _power_cases() -> set:
    body = AGENT[AGENT.index("function Invoke-HostCommand"):]
    return set(re.findall(r'^\s*"([a-z_]+)"\s*\{\s*@\(', body, re.M)) | ({"aura_stop"} if '"aura_stop"' in body else set())


def _calls_from_server() -> set:
    """Comandos que o codigo Python manda (hostbridge.run("x") e _do("x"))."""
    cmds = set()
    for p in (ROOT / "aura").rglob("*.py"):
        cmds |= set(re.findall(r'(?:hostbridge\.run|_do)\(\s*"([a-z_]+)"', p.read_text(encoding="utf-8")))
    return cmds


def test_server_only_sends_allowed_commands():
    allowed, _ = _bridge_sets()
    assert _calls_from_server() <= allowed, _calls_from_server() - allowed


def test_every_allowed_command_is_handled_by_the_agent():
    allowed, _ = _bridge_sets()
    handled = _switch_cases("Invoke-Desktop") | _power_cases()
    assert allowed <= handled, f"o agente nao trata: {allowed - handled}"


def test_desktop_commands_are_accepted_by_the_agent():
    desktop = _switch_cases("Invoke-Desktop")
    accepted = _agent_desktop_list()
    assert desktop == accepted, f"faltam na lista do agente: {desktop - accepted}; sobram: {accepted - desktop}"


def test_dry_run_only_covers_known_commands():
    allowed, dry = _bridge_sets()
    assert dry <= allowed


def test_agent_script_is_ascii():
    # o PowerShell 5.1 le .ps1 sem BOM como ANSI: acento no codigo vira lixo e o texto deixa de bater
    bad = [i + 1 for i, line in enumerate(AGENT.splitlines()) if not line.isascii()]
    assert not bad, f"linhas com acento no agent.ps1: {bad}"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
