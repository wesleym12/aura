# Inicia o agente do Windows em segundo plano (sem janela): metricas do PC, musica e volume, atalho Ctrl+Espaco
# e os comandos de controle do computador que a A.U.R.A. pede (abrir programas, YouTube, desligar...).
$agent = Join-Path $PSScriptRoot "agent.ps1"
Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$agent`"" -WindowStyle Hidden
Write-Host "host-agent iniciado em http://127.0.0.1:8766/metrics"
