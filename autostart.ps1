# Inicio automatico da A.U.R.A. quando voce entra no Windows (sem precisar de administrador).
# O mesmo que o botao "Iniciar com o Windows" em Configuracoes -> Geral: grava Aura.vbs na pasta
# "Inicializar", que roda o iniciar.ps1 escondido (Docker, containers e agente do Windows; sem navegador).
#
#   .\autostart.ps1            -> liga
#   .\autostart.ps1 -Remover   -> desliga
#   .\autostart.ps1 -Status    -> mostra se esta ligado
param([switch]$Remover, [switch]$Status)

$vbs = Join-Path ([Environment]::GetFolderPath("Startup")) "Aura.vbs"
$iniciar = Join-Path $PSScriptRoot "iniciar.ps1"

if ($Status) {
    if (Test-Path $vbs) { Write-Host "Ligado: $vbs" } else { Write-Host "Desligado." }
    exit 0
}
if ($Remover) {
    if (Test-Path $vbs) { Remove-Item $vbs -Force; Write-Host "Inicio automatico desligado." } else { Write-Host "Ja estava desligado." }
    exit 0
}

$body = @"
' A.U.R.A.: inicio automatico com o Windows (criado em Configuracoes > Geral; desligue por la).
' Roda o iniciar.ps1 escondido: Docker Desktop, containers e agente do Windows.
CreateObject("WScript.Shell").Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File ""$iniciar"" -SemNavegador", 0, False
"@
Set-Content -Path $vbs -Value $body -Encoding Unicode     # UTF-16 com BOM: aceita acentos no caminho
Write-Host "Inicio automatico ligado: $vbs"
Write-Host "No proximo logon a A.U.R.A. sobe sozinha. Registro em: $(Join-Path $PSScriptRoot 'iniciar.log')"
