# Inicia o agente do Windows em segundo plano (sem janela). -SoEntalhe: so o entalhe do topo da tela.
param([switch]$SoEntalhe)
if (-not $SoEntalhe) {
    $agent = Join-Path $PSScriptRoot "agent.ps1"
    Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$agent`"" -WindowStyle Hidden
    Write-Host "host-agent iniciado em http://127.0.0.1:8766/metrics"
}
# entalhe (so abre um; se estiver desligado nas configuracoes, fica escondido)
$notch = Join-Path $PSScriptRoot "notch.ps1"
Start-Process powershell.exe -ArgumentList "-NoProfile -STA -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$notch`"" -WindowStyle Hidden
