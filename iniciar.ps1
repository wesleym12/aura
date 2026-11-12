# Liga a A.U.R.A. inteira: Docker Desktop, containers, agente do Windows e abre o Command Center.
# Uso: .\iniciar.ps1                 (na pasta do projeto; abre o navegador no fim)
#      .\iniciar.ps1 -SemNavegador   (usado pelo inicio automatico no logon)
param([switch]$SemNavegador)
Set-Location $PSScriptRoot
$log = Join-Path $PSScriptRoot "iniciar.log"
function Say($msg) { $line = "$(Get-Date -Format 'dd/MM HH:mm:ss')  $msg"; Write-Host $msg; Add-Content -Path $log -Value $line -Encoding utf8 }
if ((Test-Path $log) -and (Get-Item $log).Length -gt 200KB) { Remove-Item $log }

# primeira vez: cria o .env e preenche o que da para descobrir sozinho (pasta de usuario e chave do agente)
$envFile = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile; Say "Criei o .env a partir do .env.example." }
$lines = [System.Collections.Generic.List[string]](Get-Content $envFile -Encoding utf8)
function Set-EnvIfEmpty($name, $value) {
    $i = $lines.FindIndex({ param($l) $l -match "^$name=" })
    if ($i -lt 0) { $lines.Add("$name=$value"); return $true }
    if ($lines[$i] -match "^$name=\s*$") { $lines[$i] = "$name=$value"; return $true }
    return $false
}
$changed = (Set-EnvIfEmpty "WORK_ROOT" $env:USERPROFILE)
$changed = (Set-EnvIfEmpty "HOST_AGENT_TOKEN" (-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) }))) -or $changed
if ($changed) { [IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false))); Say "Configuracao inicial do .env preenchida." }

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
    if (-not $SemNavegador) { Start-Process "http://127.0.0.1:8765" }
} else { Say "A Aura nao respondeu em 5 minutos. Veja: docker compose logs aura" }
