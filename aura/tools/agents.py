"""Ponte para Claude Code e Codex CLI usando o login que voce ja tem neles.

O prompt vai pelo stdin (nunca pela linha de comando), o que evita problemas
de escape/injecao com os wrappers .cmd do Windows.
"""
import asyncio
import os
import shutil
import subprocess

from .. import accounts, actions, attachments, memory, secrets, workdir
from ..config import AGENT_TIMEOUT
from . import tool


def _run(cmd: list[str], prompt: str) -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        return f"Erro: '{cmd[0]}' nao esta instalado ou nao esta no PATH."
    env = dict(os.environ)
    token = secrets.get("claude_oauth")
    if cmd[0] == "claude" and token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = token        # token da sua assinatura, conectado pela tela
    try:
        p = subprocess.run(
            [exe, *cmd[1:]],
            input=prompt,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=workdir.current(),          # trabalham na pasta de trabalho escolhida na tela
            timeout=AGENT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return f"Erro: {cmd[0]} passou de {AGENT_TIMEOUT}s."
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        detail = (out or (p.stderr or "").strip())[-1500:]
        return f"Erro ({cmd[0]} saiu com {p.returncode}): {detail}"
    return out or "(sem resposta)"


def _with_attachments(tarefa: str) -> str:
    """Os arquivos que o usuario anexou nesta conversa vao junto com o pedido."""
    files = attachments.current()
    if not files:
        return tarefa
    lista = "\n".join(f"- {f}" for f in files)
    return (f"{tarefa}\n\nArquivos anexados pelo usuario (caminhos relativos a pasta de trabalho atual; "
            f"leia-os antes de responder):\n{lista}")


async def _delegate(kind: str, cmd: list[str], tarefa: str) -> str:
    tarefa = _with_attachments(tarefa)
    result = await asyncio.to_thread(_run, cmd, tarefa)
    if not result.startswith("Erro"):
        memory.save(kind, tarefa[:120], f"PEDIDO:\n{tarefa}\n\nRESPOSTA:\n{result}")
    return result


def claude_ready() -> bool:
    """Instalado e conectado (login pela tela em Configuracoes -> Motor, ou credenciais/token antigos)."""
    return bool(shutil.which("claude")) and accounts.claude_connected()


def codex_ready() -> bool:
    return bool(shutil.which("codex")) and accounts.codex_connected()


async def _with_undo(tool_name: str, label: str, run) -> str:
    """Foto da pasta de trabalho antes: tudo que for criado/alterado/apagado pode ser desfeito."""
    root = workdir.current()
    snap = await asyncio.to_thread(actions.snapshot_before, root)
    result = await run()
    await asyncio.to_thread(actions.snapshot_after, snap, tool_name, label)
    if snap is None:
        result += "\n\n(Aviso: a pasta de trabalho e grande demais para guardar uma copia; essa tarefa nao pode ser desfeita.)"
    return result


# -p = modo nao interativo. Le, pesquisa e edita arquivos SO na pasta de trabalho (cwd); sem terminal (Bash).
CLAUDE_CMD = ["claude", "-p", "--output-format", "text", "--permission-mode", "acceptEdits",
              "--allowedTools", "WebSearch,WebFetch,Read,Glob,Grep,Edit,Write"]
# sandbox workspace-write: o Codex so consegue gravar dentro da pasta de trabalho
CODEX_CMD = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "workspace-write", "-"]


async def direct(agent: str, prompt: str, title: str) -> str:
    """Conversa com o Claude/Codex escolhido no seletor do chat (ele responde direto, com Desfazer)."""
    cmd = CLAUDE_CMD if agent == "claude" else CODEX_CMD
    name = "perguntar_claude" if agent == "claude" else "perguntar_codex"
    label = "Claude" if agent == "claude" else "Codex"
    return await _with_undo(name, f"{label}: {title[:70]}", lambda: _delegate(agent, cmd, prompt))


@tool(
    "Delega ao Claude (Claude Code) pesquisas profundas com busca na web, analises, textos complexos E "
    "programacao: ele pode ler, criar e editar arquivos na pasta de trabalho atual. Escreva a tarefa completa "
    "e autocontida. Demora de segundos a minutos.",
    {"tarefa": {"type": "string", "description": "Pedido completo para o Claude"}},
    slow=True, available=claude_ready,
)
async def perguntar_claude(tarefa: str) -> str:
    return await _with_undo("perguntar_claude", f"Claude: {tarefa[:70]}", lambda: _delegate("claude", CLAUDE_CMD, tarefa))


@tool(
    "Delega ao Codex (OpenAI Codex CLI, GPT) tarefas de programacao: escrever, revisar ou explicar codigo. "
    "Ele trabalha na pasta de trabalho atual. Demora de segundos a minutos.",
    {"tarefa": {"type": "string", "description": "Pedido completo para o Codex"}},
    slow=True, available=codex_ready,
)
async def perguntar_codex(tarefa: str) -> str:
    return await _with_undo("perguntar_codex", f"Codex: {tarefa[:70]}", lambda: _delegate("codex", CODEX_CMD, tarefa))
