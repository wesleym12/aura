#!/usr/bin/env bash
# Atualiza a A.U.R.A. (Linux/umbrelOS): baixa a versao nova do GitHub e reconstroi os containers.
# Conversas, memoria, chaves e configuracoes ficam nos volumes e no .env: nada se perde.
set -euo pipefail
cd "$(dirname "$0")"
DOCKER=(docker); docker info >/dev/null 2>&1 || DOCKER=(sudo docker)
git pull --ff-only
"${DOCKER[@]}" compose up -d --build
"${DOCKER[@]}" image prune -f >/dev/null
echo "A.U.R.A. atualizada."
