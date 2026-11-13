# Instalador da A.U.R.A. para Windows: analisa o computador, recomenda "modelo local" ou "so Gemini",
# pergunta o essencial e gera o .env. O iniciar.ps1 chama este script sozinho na primeira vez.
#   .\instalar.ps1              instala ou reconfigura (o que ja estiver no .env vira o padrao das perguntas)
#   .\instalar.ps1 -Analisar    so mostra a analise
#   .\instalar.ps1 -Completar   sem perguntas: so preenche o que faltar no .env (usado pelo iniciar.ps1)
#   .\instalar.ps1 -Atalho      so cria/atualiza o atalho "A.U.R.A." na area de trabalho e no menu Iniciar
param([switch]$Analisar, [switch]$Completar, [switch]$Atalho)
Set-Location $PSScriptRoot
$envFile = Join-Path $PSScriptRoot ".env"

# navegador para abrir a A.U.R.A. como aplicativo (janela propria, sem abas): Edge ou Chrome
function Get-AppBrowser {
    foreach ($exe in "msedge.exe", "chrome.exe") {
        foreach ($root in "HKLM:", "HKCU:") {
            $p = (Get-ItemProperty "$root\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe" -ErrorAction SilentlyContinue).'(default)'
            if ($p -and (Test-Path $p)) { return $p }
        }
    }
    return $null
}
function New-AuraShortcut {
    $browser = Get-AppBrowser
    if (-not $browser) { Write-Host "  ! Sem Edge/Chrome: atalho de aplicativo nao criado (abra http://127.0.0.1:8765 no navegador)." -ForegroundColor Yellow; return }
    $icon = Join-Path $PSScriptRoot "aura\web\icons\aura.ico"
    $sh = New-Object -ComObject WScript.Shell
    foreach ($dir in [Environment]::GetFolderPath("Desktop"), (Join-Path ([Environment]::GetFolderPath("Programs")) "")) {
        $s = $sh.CreateShortcut((Join-Path $dir "A.U.R.A..lnk"))
        $s.TargetPath = $browser
        $s.Arguments = "--app=http://127.0.0.1:8765"
        $s.IconLocation = "$icon,0"
        $s.Description = "A.U.R.A. - assistente pessoal"
        $s.Save()
    }
    Write-Host "  Atalho 'A.U.R.A.' criado na area de trabalho e no menu Iniciar." -ForegroundColor Green
}
if ($Atalho) { New-AuraShortcut; return }

function Get-EnvVal($k) {
    if (-not (Test-Path $envFile)) { return "" }
    $l = Get-Content $envFile -Encoding utf8 | Where-Object { $_ -match "^$k=" } | Select-Object -Last 1
    if ($l) { return $l.Substring($k.Length + 1) } else { return "" }
}
function Set-EnvVal($k, $v) {
    if (-not (Test-Path $envFile)) { Copy-Item (Join-Path $PSScriptRoot ".env.example") $envFile }
    $lines = [System.Collections.Generic.List[string]](Get-Content $envFile -Encoding utf8)
    $i = $lines.FindIndex({ param($l) $l -match "^#?\s*$k=" })
    if ($i -ge 0) { $lines[$i] = "$k=$v" } else { $lines.Add("$k=$v") }
    [IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding($false)))
}
function Ask($q, $def) { $a = Read-Host "  $q$(if ($def) { " [$def]" })"; if ($a) { $a } else { $def } }

# ---------- analise ----------
$os = Get-CimInstance Win32_OperatingSystem
$cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1)
$ramGb = [math]::Round($os.TotalVisibleMemorySize / 1MB)
$diskGb = [math]::Round((Get-PSDrive ($PSScriptRoot.Substring(0, 1))).Free / 1GB)
$gpuName = ""; $vramGb = 0
$smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
if ($smi) {
    $q = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader,nounits 2>$null | Select-Object -First 1
    if ($q) { $p = $q.Split(","); $gpuName = $p[0].Trim(); $vramGb = [math]::Round([double]$p[1].Trim() / 1024) }
}
$docker = $null -ne (Get-Command docker -ErrorAction SilentlyContinue)

if ($Completar) {
    # sem perguntas: o que da para descobrir sozinho (e migra instalacoes antigas, de antes do COMPOSE_FILE)
    if (-not (Get-EnvVal "WORK_ROOT")) { Set-EnvVal "WORK_ROOT" $env:USERPROFILE }
    if (-not (Get-EnvVal "HOST_AGENT_TOKEN")) { Set-EnvVal "HOST_AGENT_TOKEN" (-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })) }
    if (-not (Get-EnvVal "COMPOSE_FILE")) {
        $f = "docker-compose.yml;docker-compose.windows.yml"
        if ($gpuName -and (Get-EnvVal "AURA_LOCAL_LLM") -ne "0") { $f += ";docker-compose.gpu.yml" }
        Set-EnvVal "COMPOSE_FILE" $f
        if (-not (Select-String -Path $envFile -Pattern '^COMPOSE_PROFILES=' -Quiet)) { Set-EnvVal "COMPOSE_PROFILES" "casa" }
    }
    # modo local precisa do perfil "local" (Ollama); instalacoes de antes dele so tinham "casa"
    $prof = Get-EnvVal "COMPOSE_PROFILES"
    if ((Get-EnvVal "AURA_LOCAL_LLM") -ne "0" -and $prof -notmatch '(^|,)local(,|$)') {
        Set-EnvVal "COMPOSE_PROFILES" ((@("local") + ($prof -split ',' | Where-Object { $_ })) -join ',')
    }
    return
}

Write-Host ""
Write-Host "A.U.R.A. - analise do computador" -ForegroundColor White
Write-Host ("  Sistema        {0}" -f $os.Caption.Replace("Microsoft ", ""))
Write-Host ("  Processador    {0} - {1} nucleos" -f $cpu.Name.Trim(), $cpu.NumberOfLogicalProcessors)
Write-Host ("  Memoria        {0} GB" -f $ramGb)
Write-Host ("  Disco          {0} GB livres" -f $diskGb)
Write-Host ("  Placa NVIDIA   {0}" -f $(if ($gpuName) { "$gpuName ($vramGb GB)" } else { "nenhuma" }))
Write-Host ("  Docker         {0}" -f $(if ($docker) { "ok" } else { "nao encontrado (instale o Docker Desktop)" }))

if ($gpuName -and $vramGb -ge 6) { $rec = "local"; $model = "qwen3:4b-instruct"; $why = "placa NVIDIA com $vramGb GB: o modelo local responde em poucos segundos" }
elseif ($gpuName -and $vramGb -ge 4) { $rec = "local"; $model = "qwen3:1.7b"; $why = "placa NVIDIA com $vramGb GB: cabe um modelo local menor" }
else { $rec = "gemini"; $model = "qwen3:1.7b"; $why = "sem placa NVIDIA o modelo local roda na CPU e fica lento; o Gemini e bem mais rapido" }
Write-Host ""
Write-Host ("  Recomendacao: {0} - {1}." -f $(if ($rec -eq "local") { "modelo LOCAL" } else { "SO GEMINI" }), $why) -ForegroundColor Cyan
if ($Analisar) { return }
if (-not $docker) { Write-Host "Instale o Docker Desktop e rode de novo." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Configuracao" -ForegroundColor White
$cur = Get-EnvVal "AURA_LOCAL_LLM"
$def = if ($cur -eq "1") { "2" } elseif ($cur -eq "0") { "1" } elseif ($rec -eq "local") { "2" } else { "1" }
Write-Host "  1) So Gemini - o Google responde (rapido, precisa de internet e de uma chave gratis do Gemini)"
Write-Host "  2) Modelo local - tudo no seu computador (privado, funciona sem internet; precisa de placa de video)"
$mode = Ask "Escolha" $def
$local = if ($mode -eq "2") { "1" } else { "0" }
$curModel = Get-EnvVal "OLLAMA_MODEL"
if ($local -eq "1") { $model = Ask "Modelo local (Ollama)" $(if ($curModel) { $curModel } else { $model }) } elseif ($curModel) { $model = $curModel }

$key = Get-EnvVal "GEMINI_API_KEY"
Write-Host "  Chave do Gemini: crie em https://aistudio.google.com/apikey$(if ($local -eq '1') { ' (opcional no modo local)' })"
$new = Read-Host "  Cole a chave $(if ($key) { '(Enter mantem a atual)' } else { '(Enter para colar depois na tela)' })"
if ($new) { $key = $new.Trim() }
if ($local -eq "0" -and -not $key) { Write-Host "  ! Sem chave a A.U.R.A. nao responde no modo so Gemini: cole depois em Configuracoes -> Modelos." -ForegroundColor Yellow }
$curP = Get-EnvVal "COMPOSE_PROFILES"
$ha = Ask "Instalar o Home Assistant junto (casa inteligente)? (s/n)" $(if ($curP -match "casa" -or -not (Test-Path $envFile)) { "s" } else { "n" })

$files = "docker-compose.yml;docker-compose.windows.yml"
if ($local -eq "1" -and $gpuName) { $files += ";docker-compose.gpu.yml" }
Set-EnvVal "COMPOSE_FILE" $files
$profiles = @(); if ($local -eq "1") { $profiles += "local" }; if ($ha -match "^[sSyY]") { $profiles += "casa" }
Set-EnvVal "COMPOSE_PROFILES" ($profiles -join ",")
Set-EnvVal "AURA_LOCAL_LLM" $local
Set-EnvVal "OLLAMA_MODEL" $model
Set-EnvVal "GEMINI_API_KEY" $key
if (-not (Get-EnvVal "WORK_ROOT")) { Set-EnvVal "WORK_ROOT" $env:USERPROFILE }
if (-not (Get-EnvVal "HOST_AGENT_TOKEN")) { Set-EnvVal "HOST_AGENT_TOKEN" (-join ((1..32) | ForEach-Object { '{0:x2}' -f (Get-Random -Maximum 256) })) }
Write-Host "  .env gravado (chaves ficam so nele; nao compartilhe)." -ForegroundColor Green
New-AuraShortcut
