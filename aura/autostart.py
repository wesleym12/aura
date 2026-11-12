"""Iniciar com o Windows (Configuracoes -> Geral).

O docker-compose monta a pasta "Inicializar" do Windows em /startup. Ligar = gravar ali um Aura.vbs
que roda o iniciar.ps1 escondido no logon (Docker Desktop, containers e agente do Windows, sem abrir o
navegador). Desligar = apagar o Aura.vbs.
O conteudo e sempre este script fixo: nada vindo de fora entra nele.
"""
import os
import re
from pathlib import Path

STARTUP = Path("/startup")
VBS = STARTUP / "Aura.vbs"


def _project_dir_win() -> str:
    """Pasta do projeto como o Windows a ve. Vem de AURA_DIR_WIN ou da origem da montagem de /app/plugins."""
    env = os.environ.get("AURA_DIR_WIN", "").strip()
    if env:
        return env.rstrip("\\/")
    try:
        for line in open("/proc/self/mountinfo", encoding="utf-8"):
            f = line.split()
            if len(f) > 4 and f[4] == "/app/plugins":
                m = re.search(r"path=([A-Za-z]:\\)", line)       # Docker Desktop: drvfs com path=C:\
                if m and f[3].endswith("/plugins"):
                    return (m.group(1) + f[3][: -len("/plugins")].lstrip("/")).replace("/", "\\")
    except OSError:
        pass
    return ""


def status() -> dict:
    available = STARTUP.is_dir()
    on = available and VBS.exists()
    return {"available": available, "enabled": on, "project": _project_dir_win(), "file": VBS.name if on else ""}


def enable() -> dict:
    if not STARTUP.is_dir():
        raise ValueError("a pasta Inicializar do Windows nao esta montada (recrie o container: docker compose up -d)")
    proj = _project_dir_win()
    if not proj:
        raise ValueError("nao descobri a pasta do projeto no Windows; defina AURA_DIR_WIN no .env")
    ps1 = proj + "\\iniciar.ps1"
    vbs = ("' A.U.R.A.: inicio automatico com o Windows (criado em Configuracoes > Geral; desligue por la).\r\n"
           "' Roda o iniciar.ps1 escondido: Docker Desktop, containers e agente do Windows.\r\n"
           'CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
           f'-File ""{ps1}"" -SemNavegador", 0, False\r\n')
    VBS.write_bytes(b"\xff\xfe" + vbs.encode("utf-16-le"))     # UTF-16 com BOM: aceita acentos no caminho
    return status()


def disable() -> dict:
    VBS.unlink(missing_ok=True)
    return status()
