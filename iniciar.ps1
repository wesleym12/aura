# Liga a A.U.R.A. inteira: Docker Desktop, containers, agente do Windows e abre o Command Center.
# Uso: .\iniciar.ps1                 (na pasta do projeto; abre o navegador no fim)
#      .\iniciar.ps1 -SemNavegador   (usado pelo inicio automatico no logon)
param([switch]$SemNavegador)
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "iniciar.log"
function Say($msg) { $line = "$(Get-Date -Format 'dd/MM HH:mm:ss')  $msg"; Write-Host $msg; Add-Content -Path $log -Value $line -Encoding utf8 }
if ((Test-Path $log) -and (Get-Item $log).Length -gt 200KB) { Remove-Item $log }

# primeira vez: o instalador analisa o PC e pergunta (modelo local ou so Gemini, Home Assistant...).
# Nas outras vezes (e no inicio automatico, escondido) so completa o que faltar no .env, sem perguntar.
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile) -and -not $SemNavegador) { & (Join-Path $PSScriptRoot "instalar.ps1"); Say "Instalacao configurada." }
& (Join-Path $PSScriptRoot "instalar.ps1") -Completar

docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Say "Iniciando o Docker Desktop..."
    $exe = @("$env:ProgramFiles\Docker\Docker\Docker Desktop.exe", "$env:LOCALAPPDATA\Programs\DockerDesktop\Docker Desktop.exe") |
           Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($exe) { Start-Process $exe } else { Say "Docker Desktop nao encontrado; abra-o manualmente." }
    $t0 = Get-Date
    do { Start-Sleep 3; docker info --format "{{.ServerVersion}}" 2>$null | Out-Null }
    while ($LASTEXITCODE -ne 0 -and ((Get-Date) - $t0).TotalMinutes -lt 5)
    if ($LASTEXITCODE -ne 0) { Say "Docker nao respondeu em 5 minutos; desisti."; exit 1 }
}

Say "Subindo os containers..."
docker compose up -d 2>&1 | Out-Null

try { Invoke-WebRequest http://127.0.0.1:8766/metrics -UseBasicParsing -TimeoutSec 2 | Out-Null; Say "Agente do Windows ja estava rodando." }
catch { & "$PSScriptRoot\host-agent\start.ps1" | Out-Null; Say "Agente do Windows iniciado." }

Say "Aguardando a Aura responder..."
$t0 = Get-Date
do { Start-Sleep 2; try { $ok = (Invoke-WebRequest http://127.0.0.1:8765/ -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch { $ok = $false } }
until ($ok -or ((Get-Date) - $t0).TotalMinutes -gt 5)

if ($ok) {
    Say "Aura online em http://127.0.0.1:8765"
    if (-not $SemNavegador) {
        # abre como aplicativo (janela propria, sem abas) no Edge/Chrome; sem eles, no navegador padrao
        $b = foreach ($exe in "msedge.exe", "chrome.exe") { foreach ($r in "HKLM:", "HKCU:") {
            (Get-ItemProperty "$r\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe" -ErrorAction SilentlyContinue).'(default)' } }
        $b = $b | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
        if ($b) { Start-Process $b "--app=http://127.0.0.1:8765" } else { Start-Process "http://127.0.0.1:8765" }
    }
} else { Say "A Aura nao respondeu em 5 minutos. Veja: docker compose logs aura" }
