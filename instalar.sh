#!/usr/bin/env bash
# Instalador da A.U.R.A. para Linux (servidor, umbrelOS, Debian/Ubuntu...).
# Analisa o computador, recomenda "modelo local" ou "so Gemini", pergunta o essencial, gera o .env e sobe tudo.
#
#   ./instalar.sh            instala (ou reconfigura: o que ja estiver no .env vira o padrao das perguntas)
#   ./instalar.sh --analisar so mostra a analise do computador, sem mudar nada
#
# Depois: https://<este-servidor>:8765 (o navegador avisa do certificado proprio uma vez: Avancado -> continuar).
set -euo pipefail
cd "$(dirname "$0")"

# este instalador e so para Linux: no Windows e no macOS orienta em vez de falhar no meio
case "$(uname -s)" in
  Linux) ;;
  MINGW*|MSYS*|CYGWIN*)
    echo "Este é o instalador do Linux. No Windows, abra o PowerShell nesta pasta e rode:  .\\iniciar.ps1"; exit 1 ;;
  Darwin)
    echo "macOS ainda não é suportado pela A.U.R.A. (ela usa recursos do Linux e do Windows)."; exit 1 ;;
  *)
    echo "Sistema '$(uname -s)' não suportado: a A.U.R.A. roda em Linux e Windows."; exit 1 ;;
esac
if grep -qi microsoft /proc/version 2>/dev/null; then
  echo "Você está no WSL (Linux dentro do Windows). Para usar no próprio Windows, rode no PowerShell:  .\\iniciar.ps1"
  read -r -p "Continuar mesmo assim instalando como servidor Linux? (s/n) [n]: " a </dev/tty || true
  [[ "${a:-n}" =~ ^[sSyY] ]] || exit 1
fi

B=$'\e[1m'; D=$'\e[2m'; G=$'\e[32m'; Y=$'\e[33m'; R=$'\e[31m'; C=$'\e[36m'; N=$'\e[0m'
say()  { printf '%s\n' "$*"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*"; }
fail() { printf '%s✗ %s%s\n' "$R" "$*" "$N"; exit 1; }
ask()  { local q="$1" def="${2:-}" a; read -r -p "  $q${def:+ [$def]}: " a </dev/tty || true; printf '%s' "${a:-$def}"; }
askyn(){ local a; a="$(ask "$1 (s/n)" "$2")"; [[ "$a" =~ ^[sSyY] ]]; }

# ---------- .env ----------
ENVF=.env
envget() { [ -f "$ENVF" ] && grep -E "^$1=" "$ENVF" | tail -n1 | cut -d= -f2- || true; }
envset() {   # troca a linha KEY=... (ou acrescenta), sem mexer no resto do arquivo
  local k="$1" v="$2"
  [ -f "$ENVF" ] || cp .env.example "$ENVF"
  if grep -qE "^#?\s*$k=" "$ENVF"; then
    local tmp; tmp="$(mktemp)"
    awk -v k="$k" -v v="$v" 'BEGIN{done=0} { if (!done && $0 ~ "^#?[ \t]*"k"=") { print k"="v; done=1 } else print }' "$ENVF" >"$tmp"
    cat "$tmp" >"$ENVF"; rm -f "$tmp"
  else
    printf '%s=%s\n' "$k" "$v" >>"$ENVF"
  fi
}

# ---------- docker ----------
DOCKER=(docker)
if ! docker info >/dev/null 2>&1 && command -v sudo >/dev/null; then DOCKER=(sudo docker); fi   # usuario fora do grupo docker

# ---------- analise do computador ----------
say ""; say "${B}A.U.R.A. · análise do computador${N}"
. /etc/os-release 2>/dev/null || true
OS_NAME="${PRETTY_NAME:-Linux}"
UMBREL=0; { grep -qi umbrel /etc/os-release 2>/dev/null || [ -d /home/umbrel/umbrel ]; } && UMBREL=1
ARCH="$(uname -m)"
CPU="$(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2- | sed 's/^ *//' || true)"; CPU="${CPU:-$ARCH}"
CORES="$(nproc 2>/dev/null || echo 1)"
RAM_GB="$(awk '/MemTotal/ {printf "%d", $2/1024/1024 + 0.5}' /proc/meminfo)"
DISK_GB="$(df -Pk . | awk 'NR==2 {printf "%d", $4/1024/1024}')"
GPU_NAME=""; VRAM_GB=0
if command -v nvidia-smi >/dev/null; then
  IFS=',' read -r GPU_NAME VRAM_MB < <(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>/dev/null | head -n1) || true
  VRAM_GB=$(( ${VRAM_MB:-0} / 1024 ))
fi
NV_RUNTIME=0; "${DOCKER[@]}" info 2>/dev/null | grep -qi nvidia && NV_RUNTIME=1
HAVE_DOCKER=0; "${DOCKER[@]}" compose version >/dev/null 2>&1 && HAVE_DOCKER=1
HOSTN="$(hostname)"; IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
HA_PORT=0; (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE '[:.]8123\b' && HA_PORT=1
AURA_PORT=0; (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -qE '[:.]8765\b' && AURA_PORT=1

printf '  %-14s %s%s\n' "Sistema" "$OS_NAME" "$([ $UMBREL = 1 ] && echo ' (umbrelOS)')"
printf '  %-14s %s · %s núcleos · %s\n' "Processador" "$CPU" "$CORES" "$ARCH"
printf '  Memória        %s GB\n' "$RAM_GB"
printf '  %-14s %s GB livres aqui\n' "Disco" "$DISK_GB"
if [ -n "$GPU_NAME" ]; then printf '  %-14s %s (%s GB)%s\n' "Placa NVIDIA" "$GPU_NAME" "$VRAM_GB" "$([ $NV_RUNTIME = 1 ] || echo " ${Y}— falta o NVIDIA Container Toolkit${N}")"
else printf '  %-14s %s\n' "Placa NVIDIA" "nenhuma"; fi
printf '  %-14s %s\n' "Docker" "$([ $HAVE_DOCKER = 1 ] && echo ok || echo "${R}não encontrado${N}")"
printf '  Endereço       %s %s\n' "$HOSTN" "${IP:+($IP)}"
[ $HA_PORT = 1 ] && printf '  %-14s %s\n' "Home Assistant" "já existe um nesta máquina (porta 8123)"

# recomendacao
if [ -n "$GPU_NAME" ] && [ $NV_RUNTIME = 1 ] && [ "$VRAM_GB" -ge 6 ]; then
  REC=local; LOCAL_MODEL=qwen3:4b-instruct; WHY="placa NVIDIA com ${VRAM_GB} GB: o modelo local responde em poucos segundos"
elif [ "$ARCH" = x86_64 ] && [ "$RAM_GB" -ge 16 ] && [ "$CORES" -ge 8 ]; then
  REC=gemini; LOCAL_MODEL=qwen3:1.7b; WHY="sem placa de vídeo o modelo local roda na CPU (~10-30 s por resposta); o Gemini é bem mais rápido"
else
  REC=gemini; LOCAL_MODEL=qwen3:1.7b; WHY="este computador não tem força para um modelo local com boa velocidade"
fi
say ""; say "  ${C}Recomendação: $([ $REC = local ] && echo 'modelo LOCAL' || echo 'SÓ GEMINI') — $WHY.${N}"
[ "${1:-}" = "--analisar" ] && exit 0
[ $HAVE_DOCKER = 1 ] || fail "Instale o Docker (com o plugin compose) e rode de novo."
[ "$DISK_GB" -ge 15 ] || warn "Pouco disco livre (${DISK_GB} GB): as imagens e modelos ocupam de 8 a 20 GB."

# ---------- perguntas ----------
say ""; say "${B}Configuração${N}"
CUR_LOCAL="$(envget AURA_LOCAL_LLM)"
DEF_MODE=$([ "${CUR_LOCAL:-}" = 1 ] && echo 2 || { [ "${CUR_LOCAL:-}" = 0 ] && echo 1 || { [ $REC = local ] && echo 2 || echo 1; }; })
say "  1) Só Gemini — o Google responde (rápido, precisa de internet e de uma chave grátis do Gemini)"
say "  2) Modelo local — tudo no seu computador (privado, funciona sem internet; precisa de força)"
MODE="$(ask 'Escolha' "$DEF_MODE")"
if [ "$MODE" = 2 ]; then
  LOCAL=1
  MODEL="$(ask 'Modelo local (Ollama)' "$(envget OLLAMA_MODEL | grep . || echo "$LOCAL_MODEL")")"
else
  LOCAL=0; MODEL="$(envget OLLAMA_MODEL | grep . || echo "$LOCAL_MODEL")"
fi

KEY="$(envget GEMINI_API_KEY)"
say "  Chave do Gemini: crie em ${C}https://aistudio.google.com/apikey${N}$([ $LOCAL = 1 ] && echo ' (opcional no modo local)')"
NEWKEY="$(ask "Cole a chave $([ -n "$KEY" ] && echo '(Enter mantém a atual)' || echo '(Enter para colar depois na tela)')" "")"
[ -n "$NEWKEY" ] && KEY="$NEWKEY"
[ $LOCAL = 0 ] && [ -z "$KEY" ] && warn "Sem chave a A.U.R.A. não responde no modo só Gemini: cole depois em Configurações → Modelos."

if [ $HA_PORT = 1 ]; then
  HA=0; ok "Home Assistant: vou usar o que já existe (conecte em Plugins → Casa inteligente → Usar outro Home Assistant)."
else
  CUR_P="$(envget COMPOSE_PROFILES)"
  HA=0; askyn "Instalar o Home Assistant junto (casa inteligente)?" "$([[ "$CUR_P" == *casa* ]] && echo s || echo n)" && HA=1
fi

DEF_ROOT="$(envget WORK_ROOT | grep . || { [ -d "$HOME/umbrel/home" ] && echo "$HOME/umbrel/home" || echo "$HOME"; })"
ROOT="$(ask 'Pasta que a A.U.R.A. pode usar (arquivos, projetos)' "$DEF_ROOT")"
[ -d "$ROOT" ] || fail "A pasta $ROOT não existe."

PASS="$(envget AURA_PASSWORD)"
if [ -z "$PASS" ]; then PASS="$(head -c 18 /dev/urandom | base64 | tr -d '/+=' | head -c 16)"; fi
NEWPASS="$(ask 'Senha de acesso (Enter mantém a gerada)' "")"
[ -n "$NEWPASS" ] && PASS="$NEWPASS"

NAME="$([ $UMBREL = 1 ] && echo umbrel.local || echo "$HOSTN.local")"
[ $AURA_PORT = 1 ] && ! "${DOCKER[@]}" compose ps aura 2>/dev/null | grep -q aura && warn "A porta 8765 já está em uso por outro programa."

# ---------- grava o .env ----------
FILES="docker-compose.yml:docker-compose.linux.yml"
[ $LOCAL = 1 ] && [ -n "$GPU_NAME" ] && [ $NV_RUNTIME = 1 ] && FILES="$FILES:docker-compose.gpu.yml"
envset COMPOSE_FILE "$FILES"
envset COMPOSE_PROFILES "$([ $HA = 1 ] && echo casa)"
envset AURA_LOCAL_LLM "$LOCAL"
envset OLLAMA_MODEL "$MODEL"
envset GEMINI_API_KEY "$KEY"
envset WORK_ROOT "$ROOT"
envset TZ "$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo America/Sao_Paulo)"
envset AURA_BIND 0.0.0.0
envset AURA_PASSWORD "$PASS"
envset AURA_TLS 1
envset AURA_TLS_NAMES "$NAME,$HOSTN,$HOSTN.local${IP:+,$IP}"
envset AURA_PUBLIC_URL "https://$NAME:8765"
chmod 600 "$ENVF"
mkdir -p workspace backups memoria plugins
ok ".env gravado (chaves e senha ficam só nele; não compartilhe)."

# ---------- sobe ----------
say ""; say "${B}Subindo os containers${N} ${D}(a primeira vez baixa e monta as imagens: pode levar de 10 a 30 min)${N}"
"${DOCKER[@]}" compose up -d --build
say "  Aguardando a A.U.R.A. responder..."
for _ in $(seq 1 90); do
  curl -sk -o /dev/null https://localhost:8765/login && break
  sleep 4
done

say ""
say "${G}${B}Pronto!${N}"
say "  Abra:  ${C}https://$NAME:8765${N}${IP:+   ou   ${C}https://$IP:8765${N}}"
say "  Senha: ${B}$PASS${N}"
say "  ${D}• O navegador avisa do certificado próprio uma vez: Avançado → Continuar. Sem HTTPS o microfone não funciona.${N}"
[ $LOCAL = 1 ] && say "  ${D}• O modelo local ainda está baixando em segundo plano: '${DOCKER[*]} compose logs -f ollama-pull'.${N}"
say "  ${D}• Logins do Google e de conectores MCP: abra uma vez pelo túnel ${N}ssh -L 8765:localhost:8765 $(whoami)@$NAME${D} e acesse http://localhost:8765.${N}"
say "  ${D}• Atualizar depois: ./atualizar.sh   ·   Reconfigurar: ./instalar.sh${N}"
