"""Inicia o servidor. Com AURA_TLS=1 (instalacao em servidor/umbrelOS) serve em HTTPS: o navegador so libera
o microfone em HTTPS (ou em localhost). Na primeira vez gera um certificado proprio (autoassinado, 10 anos) em
/data/tls para os nomes de AURA_TLS_NAMES (ex.: umbrel.local, 192.168.0.10). O navegador avisa uma vez
("conexao nao particular"): clique em Avancado -> continuar.
"""
import ipaddress
import os
import subprocess
from pathlib import Path

import uvicorn


def _cert() -> tuple[str, str] | None:
    d = Path(os.getenv("AURA_TLS_DIR", "/data/tls"))
    cert, key = d / "cert.pem", d / "key.pem"
    if cert.exists() and key.exists():
        return str(cert), str(key)
    d.mkdir(parents=True, exist_ok=True)
    names = ["localhost", "127.0.0.1"] + [n.strip() for n in os.getenv("AURA_TLS_NAMES", "").split(",") if n.strip()]
    san = []
    for n in dict.fromkeys(names):
        try:
            ipaddress.ip_address(n)
            san.append(f"IP:{n}")
        except ValueError:
            san.append(f"DNS:{n}")
    try:
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
                        "-keyout", str(key), "-out", str(cert), "-subj", "/CN=A.U.R.A.",
                        "-addext", "subjectAltName=" + ",".join(san)], check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        print(f"Nao consegui gerar o certificado HTTPS ({e}); seguindo em HTTP.")
        return None
    key.chmod(0o600)
    print(f"Certificado HTTPS criado para: {', '.join(names)}")
    return str(cert), str(key)


def main():
    kw = {}
    if os.getenv("AURA_TLS", "0") == "1":
        c = _cert()
        if c:
            kw = {"ssl_certfile": c[0], "ssl_keyfile": c[1]}
    uvicorn.run("aura.server:app", host="0.0.0.0", port=8765, proxy_headers=True, **kw)


if __name__ == "__main__":
    main()
