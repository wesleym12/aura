#!/usr/bin/env bash
# Atualiza a A.U.R.A. (Linux): baixa a versao nova do GitHub e reconstroi os containers.
# Conversas, memoria, chaves e configuracoes ficam nos volumes e no .env: nada se perde.
# Depois de atualizar, reabra o app de mesa (ou recarregue a pagina) para ver as telas novas.
set -euo pipefail
cd "$(dirname "$0")"
DOCKER=(docker); docker info >/dev/null 2>&1 || DOCKER=(sudo docker)
git pull --ff-only
# instalacoes antigas citam no .env o docker-compose.linux.yml, que saiu do projeto
[ -f .env ] && sed -i 's/:docker-compose\.linux\.yml//' .env
"${DOCKER[@]}" compose up -d --build
"${DOCKER[@]}" image prune -f >/dev/null
echo "A.U.R.A. atualizada."
