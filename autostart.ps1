# Inicio automatico da Aura quando voce entra no Windows (sem precisar de administrador).
# O mesmo que o botao "Iniciar com o Windows" em Configuracoes -> Geral: grava Aura.vbs na pasta
# "Inicializar", que roda o iniciar.ps1 escondido (Docker, containers e agente do Windows; sem navegador).
#
#   .\autostart.ps1            -> liga
#   .\autostart.ps1 -Remover   -> desliga
#   .\autostart.ps1 -Status    -> mostra se esta ligado
param([switch]$Remover, [switch]$Status)

$startup = [Environment]::GetFolderPath("Startup")
$vbs = Join-Path $startup "Aura.vbs"
$lnk = Join-Path $startup "Jarvis.lnk"    # versoes antigas (projeto se chamava Jarvis)
$oldVbs = Join-Path $startup "Jarvis.vbs"
$iniciar = Join-Path $PSScriptRoot "iniciar.ps1"

if ($Status) {
    $f = @($vbs, $oldVbs, $lnk) | Where-Object { Test-Path $_ }
    if ($f) { Write-Host "Ligado: $($f -join ', ')" } else { Write-Host "Desligado." }
    exit 0
}
if ($Remover) {
    $f = @($vbs, $oldVbs, $lnk) | Where-Object { Test-Path $_ }
    $f | ForEach-Object { Remove-Item $_ -Force }
    if ($f) { Write-Host "Inicio automatico desligado." } else { Write-Host "Ja estava desligado." }
    exit 0
}

$body = @"
' Aura: inicio automatico com o Windows (criado em Configuracoes > Geral; desligue por la).
' Roda o iniciar.ps1 escondido: Docker Desktop, containers e agente do Windows.
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$iniciar"" -SemNavegador", 0, False
"@
Set-Content -Path $vbs -Value $body -Encoding Unicode     # UTF-16 com BOM: aceita acentos no caminho
@($oldVbs, $lnk) | Where-Object { Test-Path $_ } | ForEach-Object { Remove-Item $_ -Force }
Write-Host "Inicio automatico ligado: $vbs"
Write-Host "No proximo logon a Aura sobe sozinha. Registro em: $(Join-Path $PSScriptRoot 'iniciar.log')"
