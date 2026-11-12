"""Metricas do servidor (Linux/umbrelOS): CPU, RAM, temperatura, rede e GPU NVIDIA (se houver).

No Linux o container enxerga a maquina inteira quando o /proc do host esta montado em /host_proc
(docker-compose.linux.yml). Mesmo formato do agente do Windows, para a tela tratar igual.
"""
import os
import shutil
import subprocess
import time
from pathlib import Path

import psutil

if Path("/host_proc/stat").exists():
    psutil.PROCFS_PATH = "/host_proc"

_last = {"t": 0.0, "net": None, "data": None}


def _os_name() -> str:
    for f in ("/host_os_release", "/etc/os-release"):
        try:
            for line in open(f, encoding="utf-8"):
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
        except OSError:
            continue
    return "Linux"


OS_NAME = _os_name()


def _temp() -> int | None:
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz", "zenpower"):
        if temps.get(key):
            return int(max(t.current for t in temps[key]))
    vals = [t.current for ts in temps.values() for t in ts if t.current]
    return int(max(vals)) if vals else None


def _gpu() -> tuple:
    if not shutil.which("nvidia-smi"):
        return None, None, None
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3).stdout
        u, t, used, total = (float(x) for x in out.splitlines()[0].split(","))
        return int(u), int(t), int(round(100 * used / total))
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None, None, None


def snapshot() -> dict:
    if psutil.PROCFS_PATH != "/host_proc":
        return {"cpu": None}          # Windows/Docker Desktop: o container so ve a VM; quem mede e o agente do Windows
    now = time.time()
    if _last["data"] and now - _last["t"] < 1.5:       # a tela pede a cada 2 s
        return _last["data"]
    net = psutil.net_io_counters()
    kbs = 0.0
    if _last["net"] and now > _last["t"]:
        kbs = ((net.bytes_sent + net.bytes_recv) - (_last["net"].bytes_sent + _last["net"].bytes_recv)) / 1024 / (now - _last["t"])
    gpu, gpu_temp, vram = _gpu()
    data = {"cpu": int(psutil.cpu_percent(interval=None)), "ram": int(psutil.virtual_memory().percent),
            "gpu": gpu, "gpu_temp": gpu_temp, "vram": vram, "cpu_temp": _temp(),
            "net_kbs": round(max(0.0, kbs), 1), "uptime_s": int(now - psutil.boot_time()),
            "procs": len(psutil.pids()), "os": "LINUX", "os_name": OS_NAME}
    _last.update(t=now, net=net, data=data)
    return data
