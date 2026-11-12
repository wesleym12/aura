# Inicia o agente de metricas do Windows em segundo plano (sem janela).
$agent = Join-Path $PSScriptRoot "agent.ps1"
Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$agent`"" -WindowStyle Hidden
Write-Host "host-agent iniciado em http://127.0.0.1:8766/metrics"
