"""O modelo local escolhe a ferramenta certa? (pedidos comuns, com todas as ferramentas oferecidas)

Mede o acerto do modelo do Ollama com as descricoes atuais das ferramentas. Nao executa nada: so olha qual
ferramenta ele chamaria. Roda dentro do container:
    docker compose exec -T aura python - < tests/test_tool_choice.py
"""
import os

import httpx

from aura import hostbridge, llm, settings
from aura.tools import active_tools, load_all

MODEL = os.getenv("TEST_MODEL", "qwen3:4b-instruct")
OLL = os.environ.get("OLLAMA_URL", "http://ollama:11434")

CASES = [
    ("põe uma coroa no seu rostinho", "alterar_configuracao", {"chave": "face_acc"}),
    ("liga o modo silencioso", "alterar_configuracao", {"chave": "quiet_mode"}),
    ("muda seu jeito para sarcástico", "alterar_configuracao", {"chave": "personality"}),
    ("deixa o volume em 30", "midia", {"acao": "volume"}),
    ("pausa a música", "midia", {"acao": "play_pause"}),
    ("abre o spotify", "abrir", {}),
    ("toca lofi no youtube", "youtube", {}),
    ("timer de 10 minutos para a pizza", "criar_timer", {}),
    ("me lembra de ligar pro cliente em 30 minutos", "criar_lembrete", {}),
    ("vai chover hoje?", "clima", {}),
    ("quanto está o dólar?", "cotacao", {}),
    ("bloqueia o computador", "bloquear_tela", {}),
    ("adiciona na lista: comprar café", "criar_tarefa", {}),
    ("bebi um copo de água", "marcar_habito", {}),
    ("quanto é 15% de 230?", "calcular", {}),
]


def main():
    hostbridge.agent_online = lambda: True           # as ferramentas do PC aparecem (nada e executado)
    settings.get()["desktop_control"] = True
    load_all()
    cfg = llm.cfg_for(f"ollama:{MODEL}")
    system = settings.system_prompt({"brain": llm.describe(cfg)})
    tools = [t.schema() for t in active_tools()]
    ok = 0
    for q, want, args in CASES:
        j = httpx.post(OLL + "/api/chat", json={"model": MODEL, "stream": False, "tools": tools, "keep_alive": "2m",
                                               "messages": [{"role": "system", "content": system}, {"role": "user", "content": q}]},
                       timeout=300).json()
        calls = j["message"].get("tool_calls") or []
        got = calls[0]["function"] if calls else {"name": "(nenhuma)", "arguments": {}}
        good = got["name"] == want and all(got["arguments"].get(k) == v for k, v in args.items())
        ok += good
        extra = "" if calls else " | respondeu: " + (j["message"].get("content") or "")[:70].replace("\n", " ")
        print(("ok   " if good else "ERRO ") + f"{q!r} -> {got['name']} {got['arguments']}{extra}")
    print(f"{ok}/{len(CASES)} certas com {len(tools)} ferramentas")


main()
