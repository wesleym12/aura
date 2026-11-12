"""Contas: conectar o Claude (Claude Code) e o ChatGPT (Codex) pelas SUAS assinaturas, direto da tela.

Por baixo, roda os mesmos logins oficiais de terminal dentro do container (num terminal virtual)
e mostra na tela o que eles pedem:
- Codex:  `codex login --device-auth`  -> link + codigo de uso unico; termina sozinho quando voce confirma.
- Claude: `claude setup-token`         -> link; voce autoriza, cola o codigo que aparecer, e ele devolve
           um token de longa duracao, guardado com as outras chaves (secrets) e usado pela Aura.
"""
import fcntl
import os
import pty
import re
import select
import shutil
import struct
import subprocess
import termios
import threading
import time
from pathlib import Path

from . import secrets

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")
CLAUDE_HOME = Path(os.getenv("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
CODEX_HOME = Path(os.getenv("CODEX_HOME", Path.home() / ".codex"))


class Login:
    """Um login em andamento: processo num terminal virtual + o que ja apareceu na tela dele."""

    def __init__(self, provider: str, cmd: list[str]):
        self.provider = provider
        self.state = {"status": "starting", "url": None, "code": None, "message": "Iniciando..."}
        self.buf = ""
        self.master, slave = pty.openpty()
        # terminal bem largo: o link nao quebra em varias linhas
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 50, 1000, 0, 0))
        env = {**os.environ, "TERM": "xterm-256color", "COLUMNS": "1000", "NO_COLOR": "1", "BROWSER": "true"}
        self.proc = subprocess.Popen(cmd, stdin=slave, stdout=slave, stderr=slave, close_fds=True, env=env,
                                     cwd=str(Path.home()))
        os.close(slave)
        self.started = time.time()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        while True:
            try:
                r, _, _ = select.select([self.master], [], [], 0.5)
                if r:
                    chunk = os.read(self.master, 65536)
                    if not chunk:
                        break
                    self.buf += ANSI.sub("", chunk.decode(errors="replace"))
                    self.parse()
            except OSError:
                break
            if self.proc.poll() is not None:
                break
            if time.time() - self.started > 16 * 60:          # os codigos expiram em ~15 min
                self.fail("O tempo para concluir o login acabou. Tente de novo.")
                self.proc.kill()
                break
        self.finished()

    def send(self, text: str):
        os.write(self.master, (text + "\r").encode())

    def fail(self, msg: str):
        self.state.update(status="error", message=msg)

    def cancel(self):
        if self.proc.poll() is None:
            self.proc.kill()
        self.state.update(status="cancelled", message="Cancelado.")

    def parse(self):
        ...

    def finished(self):
        ...


class CodexLogin(Login):
    def __init__(self):
        super().__init__("codex", ["codex", "login", "--device-auth"])

    def parse(self):
        url = re.search(r"https://auth\.openai\.com/\S+", self.buf)
        code = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4,6})\b", self.buf)
        if url and code and self.state["status"] == "starting":
            self.state.update(status="waiting_user", url=url.group(0), code=code.group(1),
                              message="Abra o link, entre na sua conta do ChatGPT e digite o código.")

    def finished(self):
        if self.state["status"] in ("cancelled", "error"):
            return
        if self.proc.wait() == 0 and (CODEX_HOME / "auth.json").exists():
            self.state.update(status="done", message="ChatGPT (Codex) conectado.")
        else:
            tail = self.buf.strip().splitlines()[-1:] or ["sem detalhes"]
            self.fail("O login do ChatGPT nao terminou: " + tail[0][:200])


class ClaudeLogin(Login):
    TOKEN = re.compile(r"(sk-ant-oat[\w\-]{20,})")

    def __init__(self):
        super().__init__("claude", ["claude", "setup-token"])

    def parse(self):
        flat = re.sub(r"\s+", "", self.buf)               # junta o link, mesmo se o terminal quebrou a linha
        tok = self.TOKEN.search(flat)
        if tok and self.state["status"] != "done":
            secrets.put("claude_oauth", tok.group(1))
            self.state.update(status="done", message="Claude conectado.")
            return
        url = re.search(r"https://claude\.(?:com|ai)/\S*?oauth/authorize\S*?state=[\w\-]+", flat)
        if url and self.state["status"] == "starting":
            self.state.update(status="waiting_code", url=url.group(0),
                              message="Abra o link, autorize e cole aqui o código que aparecer.")
        low = self.buf.lower()
        if self.state["status"] == "checking" and ("invalid" in low or "error" in low.split("paste")[-1]):
            self.fail("Código recusado. Gere outro e tente de novo.")

    def submit(self, code: str):
        self.state.update(status="checking", message="Conferindo o código...")
        self.send(code.strip())

    def finished(self):
        if self.state["status"] not in ("done", "cancelled", "error"):
            self.fail("O login do Claude nao terminou. Tente de novo.")


_logins: dict[str, Login] = {}


def start(provider: str) -> dict:
    if provider not in ("claude", "codex"):
        raise ValueError("conta desconhecida")
    if not shutil.which(provider):
        raise ValueError(f"'{provider}' nao esta instalado no container")
    old = _logins.get(provider)
    if old and old.proc.poll() is None:
        old.cancel()
    _logins[provider] = ClaudeLogin() if provider == "claude" else CodexLogin()
    return login_state(provider)


def login_state(provider: str) -> dict | None:
    lg = _logins.get(provider)
    return dict(lg.state) if lg else None


def submit_code(code: str) -> dict:
    lg = _logins.get("claude")
    if not isinstance(lg, ClaudeLogin) or lg.proc.poll() is not None:
        raise ValueError("nenhum login do Claude em andamento")
    lg.submit(code)
    return login_state("claude")


def cancel(provider: str):
    lg = _logins.pop(provider, None)
    if lg:
        lg.cancel()


def claude_connected() -> bool:
    return bool(secrets.get("claude_oauth") or os.getenv("CLAUDE_CODE_OAUTH_TOKEN")
                or (CLAUDE_HOME / ".credentials.json").exists())


def codex_connected() -> bool:
    return (CODEX_HOME / "auth.json").exists()


def logout(provider: str):
    if provider == "claude":
        secrets.put("claude_oauth", "")
        (CLAUDE_HOME / ".credentials.json").unlink(missing_ok=True)
    elif provider == "codex":
        subprocess.run(["codex", "logout"], capture_output=True, timeout=20)
        (CODEX_HOME / "auth.json").unlink(missing_ok=True)


def status() -> dict:
    return {
        "claude": {"installed": bool(shutil.which("claude")), "connected": claude_connected(),
                   "login": login_state("claude")},
        "codex": {"installed": bool(shutil.which("codex")), "connected": codex_connected(),
                  "login": login_state("codex")},
    }
