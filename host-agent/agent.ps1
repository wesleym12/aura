# Agente do Windows para o Command Center da Aura.
# - /metrics : CPU/RAM/GPU reais do PC (o container so enxerga a VM do WSL).
# - /ptt     : canal ao vivo (Server-Sent Events) do atalho global Ctrl+Espaco (segurar para falar).
#              So observa essas duas teclas, nada mais, e funciona com qualquer janela em foco.
# Usa so o que ja vem no Windows. Escuta apenas em localhost:8766 e so responde para a pagina da Aura.
$ErrorActionPreference = "SilentlyContinue"
$port = 8766
$allowed = @("http://localhost:8765", "http://127.0.0.1:8765")

Add-Type -Namespace AuraAgent -Name Keys -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")]
public static extern short GetAsyncKeyState(int vKey);
'@

# ---- metricas numa thread separada (leitura leva ~1 s e nao pode atrasar o atalho) ----
$shared = [hashtable]::Synchronized(@{ json = '{}' })
$metricsPs = [powershell]::Create()
[void]$metricsPs.AddScript({
    param($shared)
    $ErrorActionPreference = "SilentlyContinue"
    $osInfo = Get-CimInstance Win32_OperatingSystem
    $osName = "$($osInfo.Caption) (build $($osInfo.BuildNumber))".Replace("Microsoft ", "")
    while ($true) {
        $os = Get-CimInstance Win32_OperatingSystem
        $cpu = (Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'").PercentProcessorTime
        $net = (Get-CimInstance Win32_PerfFormattedData_Tcpip_NetworkInterface | Measure-Object BytesTotalPersec -Sum).Sum
        $gpu = $null; $gpuTemp = $null; $vram = $null
        $smi = & nvidia-smi --query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total --format=csv,noheader,nounits 2>$null
        if ($smi) {
            $p = ($smi | Select-Object -First 1).Split(",") | ForEach-Object { [double]$_.Trim() }
            $gpu = [int]$p[0]; $gpuTemp = [int]$p[1]; $vram = [int][math]::Round(100 * $p[2] / $p[3])
        }
        $shared.json = ([ordered]@{
            cpu      = [int]$cpu
            ram      = [int][math]::Round(100 * (1 - $os.FreePhysicalMemory / $os.TotalVisibleMemorySize))
            gpu      = $gpu
            gpu_temp = $gpuTemp
            vram     = $vram
            net_kbs  = [math]::Round($net / 1024, 1)
            uptime_s = [int]((Get-Date) - $os.LastBootUpTime).TotalSeconds
            procs    = (Get-Process).Count
            os       = "WIN"
            os_name  = $osName
        } | ConvertTo-Json -Compress)
        Start-Sleep -Milliseconds 1500
    }
}).AddArgument($shared)
[void]$metricsPs.BeginInvoke()

# ---- servidor HTTP ----
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$port/")
$listener.Prefixes.Add("http://127.0.0.1:$port/")
$listener.Start()
Write-Host "Aura host-agent em http://127.0.0.1:$port (metrics, ptt)"

$streams = New-Object System.Collections.ArrayList   # paginas ouvindo o /ptt
$utf8 = [Text.Encoding]::UTF8

function Send-Event($res, [string]$text) {
    $b = $utf8.GetBytes($text)
    $res.OutputStream.Write($b, 0, $b.Length)
    $res.OutputStream.Flush()
}

function Broadcast([string]$text) {
    foreach ($r in @($streams)) {
        try { Send-Event $r $text } catch { [void]$streams.Remove($r); try { $r.Abort() } catch {} }
    }
}

function Handle($ctx) {
    $res = $ctx.Response
    $origin = $ctx.Request.Headers["Origin"]
    if ($allowed -contains $origin) {
        $res.AddHeader("Access-Control-Allow-Origin", $origin)
        $res.AddHeader("Vary", "Origin")
    }
    switch ($ctx.Request.Url.AbsolutePath) {
        "/metrics" {
            $b = $utf8.GetBytes($shared.json)
            $res.ContentType = "application/json"
            $res.AddHeader("Cache-Control", "no-store")
            $res.OutputStream.Write($b, 0, $b.Length)
            $res.Close()
        }
        "/ptt" {
            $res.ContentType = "text/event-stream"
            $res.AddHeader("Cache-Control", "no-store")
            $res.SendChunked = $true
            try { Send-Event $res "retry: 2000`n`n"; [void]$streams.Add($res) } catch { try { $res.Abort() } catch {} }
        }
        default { $res.StatusCode = 404; $res.Close() }
    }
}

# ---- comandos da Aura (desligar, reiniciar, Wi-Fi...) ----
# O agente BUSCA os comandos na Aura com a chave secreta do .env (nenhuma porta nova aberta)
# e so executa a lista fechada abaixo. Os perigosos so chegam la depois do seu clique em Autorizar.
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$token = (Get-Content $envFile -ErrorAction SilentlyContinue | Where-Object { $_ -match '^HOST_AGENT_TOKEN=(.+)$' } |
          ForEach-Object { $Matches[1].Trim() } | Select-Object -First 1)
Add-Type -AssemblyName System.Net.Http
$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(40)
if ($token) { $http.DefaultRequestHeaders.Add("X-Agent-Token", $token) }
$auraUrl = "http://127.0.0.1:8765"
$poll = $null
$nextPoll = Get-Date
$lastWifi = $null

# ---- controle do computador (lista fechada; clicar/digitar/atalhos so chegam depois do seu Autorizar) ----
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms, System.Drawing
Add-Type -Namespace AuraAgent -Name Win -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, System.UIntPtr extra);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.UIntPtr e);
'@
$script:desktopCmds = @("windows", "focus", "open", "ui", "click", "type", "keys", "screenshot", "media")
$script:uiElems = @()

function Press-Key([byte]$vk) {
    [AuraAgent.Win]::keybd_event($vk, 0, 0, [UIntPtr]::Zero)
    [AuraAgent.Win]::keybd_event($vk, 0, 2, [UIntPtr]::Zero)
}

function Invoke-Desktop($c) {
    $a = $c.args
    switch ($c.cmd) {
        "windows" {
            $list = Get-Process | Where-Object { $_.MainWindowTitle } | Select-Object -First 40 |
                    ForEach-Object { "$($_.ProcessName): $($_.MainWindowTitle)" }
            return @{ ok = $true; output = ($list -join "`n") }
        }
        "focus" {
            $t = [string]$a.title
            $alias = @{ "bloco de notas" = "notepad"; "calculadora" = "calculatorapp"; "explorador" = "explorer"; "navegador" = "msedge" }
            $proc = $alias[$t.ToLower()]
            $wins = Get-Process | Where-Object { $_.MainWindowTitle }
            $p = $wins | Where-Object { $_.MainWindowTitle -like "*$t*" -or $_.ProcessName -like "*$t*" -or ($proc -and $_.ProcessName -like "*$proc*") } |
                 Select-Object -First 1
            if (-not $p) {
                $lista = ($wins | ForEach-Object { "$($_.ProcessName): $($_.MainWindowTitle)" }) -join "; "
                return @{ ok = $false; output = "nenhuma janela com '$t'. Janelas abertas: $lista" }
            }
            [AuraAgent.Win]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
            Press-Key 0x12                                   # Alt: libera o Windows para trocar o foco
            [AuraAgent.Win]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
            return @{ ok = $true; output = "em foco: $($p.MainWindowTitle)" }
        }
        "open" {
            $t = [string]$a.target
            if ($a.path) {                                   # pasta/arquivo dentro da pasta de trabalho (ja validado na Aura)
                if (-not (Test-Path -LiteralPath $a.path)) { return @{ ok = $false; output = "nao encontrei $($a.path)" } }
                Start-Process -FilePath $a.path
                return @{ ok = $true; output = "abriu $($a.path)" }
            }
            if ($t -match '^https?://') { Start-Process $t; return @{ ok = $true; output = "abriu $t" } }
            $known = @{ "bloco de notas" = "notepad.exe"; "notepad" = "notepad.exe"; "calculadora" = "calc.exe"; "calc" = "calc.exe";
                        "explorador" = "explorer.exe"; "explorer" = "explorer.exe"; "paint" = "mspaint.exe";
                        "configuracoes" = "ms-settings:"; "configurações" = "ms-settings:"; "gerenciador de tarefas" = "taskmgr.exe" }
            if ($known.ContainsKey($t.ToLower())) { Start-Process $known[$t.ToLower()]; return @{ ok = $true; output = "abriu $t" } }
            # lista de apps do Menu Iniciar do Windows: inclui os da Microsoft Store (Spotify, WhatsApp...), que nao
            # tem atalho .lnk. Fica em cache por 10 min (a primeira consulta leva ~1 s).
            if (-not $script:startApps -or ((Get-Date) - $script:startAppsAt).TotalMinutes -gt 10) {
                $script:startApps = @(Get-StartApps | Where-Object { $_.Name -notmatch 'uninstall|desinstal' })
                $script:startAppsAt = Get-Date
            }
            $app = $script:startApps | Where-Object { $_.Name -eq $t } | Select-Object -First 1
            if (-not $app) { $app = $script:startApps | Where-Object { $_.Name -like "*$t*" } | Sort-Object { $_.Name.Length } | Select-Object -First 1 }
            if ($app) { Start-Process "shell:AppsFolder\$($app.AppID)"; return @{ ok = $true; output = "abriu o aplicativo instalado $($app.Name)" } }
            $dirs = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs", "$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
            $lnk = Get-ChildItem $dirs -Recurse -Include *.lnk, *.url -ErrorAction SilentlyContinue |
                   Where-Object { $_.BaseName -like "*$t*" -and $_.BaseName -notmatch 'uninstall|desinstal' } |
                   Sort-Object { $_.BaseName.Length } | Select-Object -First 1
            if ($lnk) { Start-Process $lnk.FullName; return @{ ok = $true; output = "abriu $($lnk.BaseName)" } }
            return @{ ok = $false; output = "'$t' nao esta instalado neste PC. Diga isso ao usuario; NAO abra a versao web sem ele pedir." }
        }
        "ui" {
            $h = [AuraAgent.Win]::GetForegroundWindow()
            $root = [System.Windows.Automation.AutomationElement]::FromHandle($h)
            $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
            $types = @("Button", "MenuItem", "Edit", "Hyperlink", "ListItem", "TabItem", "CheckBox", "RadioButton",
                       "ComboBox", "TreeItem", "SplitButton", "Document")
            $script:uiElems = @(); $out = @()
            foreach ($e in $all) {
                try {
                    $cur = $e.Current
                    $ct = $cur.ControlType.ProgrammaticName -replace 'ControlType\.', ''
                    if (($types -contains $ct) -and ($cur.Name -or $ct -in @("Edit", "Document")) -and -not $cur.IsOffscreen) {
                        $script:uiElems += $e
                        $out += "[$($script:uiElems.Count - 1)] $ct`: $($cur.Name)"
                        if ($script:uiElems.Count -ge 150) { break }
                    }
                } catch {}
            }
            return @{ ok = $true; output = "Janela: $($root.Current.Name)`n" + ($out -join "`n") }
        }
        "click" {
            $e = $null
            if ($null -ne $a.index -and "$($a.index)" -ne "") { $i = [int]$a.index; if ($i -lt $script:uiElems.Count) { $e = $script:uiElems[$i] } }
            elseif ($a.name) { $e = $script:uiElems | Where-Object { $_.Current.Name -like "*$($a.name)*" } | Select-Object -First 1 }
            if (-not $e) { return @{ ok = $false; output = "item nao encontrado: leia a tela de novo (ler_tela)" } }
            $label = $e.Current.Name
            try { $e.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); return @{ ok = $true; output = "clicou em '$label'" } } catch {}
            try { $e.SetFocus() } catch {}
            try {
                $pt = $e.GetClickablePoint()
                [AuraAgent.Win]::SetCursorPos([int]$pt.X, [int]$pt.Y) | Out-Null
                [AuraAgent.Win]::mouse_event(0x2, 0, 0, 0, [UIntPtr]::Zero); [AuraAgent.Win]::mouse_event(0x4, 0, 0, 0, [UIntPtr]::Zero)
                return @{ ok = $true; output = "clicou em '$label'" }
            } catch { return @{ ok = $false; output = "nao consegui clicar em '$label'" } }
        }
        "open_in_tab" {
            # abre o endereco NA ABA que ja mostra o site (ex.: YouTube), em vez de abrir outra janela.
            # So digita depois de confirmar que a janela em foco e mesmo a do site: nunca digita na janela errada.
            $url = [string]$a.url; $match = [string]$a.match
            if ($url -notmatch '^https://') { return @{ ok = $false; output = "endereco invalido" } }
            $browsers = 'msedge|chrome|firefox|brave|opera|vivaldi'
            $w = Get-Process | Where-Object { $_.MainWindowTitle -like "*$match*" -and $_.ProcessName -match $browsers } | Select-Object -First 1
            if ($w) {
                [AuraAgent.Win]::ShowWindow($w.MainWindowHandle, 9) | Out-Null
                Press-Key 0x12
                [AuraAgent.Win]::SetForegroundWindow($w.MainWindowHandle) | Out-Null
                Start-Sleep -Milliseconds 350
                if ([AuraAgent.Win]::GetForegroundWindow() -eq $w.MainWindowHandle) {
                    [System.Windows.Forms.SendKeys]::SendWait("^l")
                    Start-Sleep -Milliseconds 150
                    $esc = -join ($url.ToCharArray() | ForEach-Object { if ('+^%~(){}[]'.Contains($_)) { "{$_}" } else { "$_" } })
                    [System.Windows.Forms.SendKeys]::SendWait($esc + "{ENTER}")
                    return @{ ok = $true; output = "abriu na aba do $match que ja estava aberta" }
                }
            }
            Start-Process $url
            return @{ ok = $true; output = "abriu $url (nova aba: nao havia $match aberto em primeiro plano no navegador)" }
        }
        "type" {
            $txt = [string]$a.text
            $esc = -join ($txt.ToCharArray() | ForEach-Object { if ('+^%~(){}[]'.Contains($_)) { "{$_}" } elseif ($_ -eq "`n") { "{ENTER}" } else { "$_" } })
            [System.Windows.Forms.SendKeys]::SendWait($esc)
            return @{ ok = $true; output = "digitou $($txt.Length) caracteres" }
        }
        "keys" {
            $parts = ([string]$a.combo).ToLower() -split '\+' | ForEach-Object { $_.Trim() }
            $named = @{ enter = "{ENTER}"; tab = "{TAB}"; esc = "{ESC}"; escape = "{ESC}"; backspace = "{BACKSPACE}"; delete = "{DELETE}";
                        up = "{UP}"; down = "{DOWN}"; left = "{LEFT}"; right = "{RIGHT}"; home = "{HOME}"; end = "{END}";
                        pgup = "{PGUP}"; pgdn = "{PGDN}"; space = " "; espaco = " " }
            1..12 | ForEach-Object { $named["f$_"] = "{F$_}" }
            if ($parts -contains "win") {                    # SendKeys nao tem a tecla Windows: usa keybd_event
                $key = ($parts | Where-Object { $_ -ne "win" } | Select-Object -First 1)
                [AuraAgent.Win]::keybd_event(0x5B, 0, 0, [UIntPtr]::Zero)
                if ($key) { Press-Key ([byte][char]$key.ToUpper()) }
                [AuraAgent.Win]::keybd_event(0x5B, 0, 2, [UIntPtr]::Zero)
                return @{ ok = $true; output = "teclas: $($a.combo)" }
            }
            $mods = ""; $key = ""
            foreach ($p in $parts) {
                switch ($p) { "ctrl" { $mods += "^" } "alt" { $mods += "%" } "shift" { $mods += "+" }
                    default { if ($named.ContainsKey($p)) { $key = $named[$p] } elseif ($p.Length -eq 1) { $key = $p } else { return @{ ok = $false; output = "tecla desconhecida: $p" } } } }
            }
            [System.Windows.Forms.SendKeys]::SendWait($mods + $key)
            return @{ ok = $true; output = "teclas: $($a.combo)" }
        }
        "screenshot" {
            $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
            $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
            $g = [System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size); $g.Dispose()
            $scale = [Math]::Min(1.0, 1280.0 / $b.Width)
            $small = New-Object System.Drawing.Bitmap $bmp, ([int]($b.Width * $scale)), ([int]($b.Height * $scale))
            $codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq "image/jpeg" }
            $ep = New-Object System.Drawing.Imaging.EncoderParameters 1
            $ep.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter ([System.Drawing.Imaging.Encoder]::Quality, [long]70)
            $ms = New-Object System.IO.MemoryStream; $small.Save($ms, $codec, $ep)
            $bmp.Dispose(); $small.Dispose()
            return @{ ok = $true; output = "data:image/jpeg;base64," + [Convert]::ToBase64String($ms.ToArray()) }
        }
        "media" {
            $vk = @{ volume_up = 0xAF; volume_down = 0xAE; mute = 0xAD; play_pause = 0xB3; next = 0xB0; previous = 0xB1 }[[string]$a.action]
            if (-not $vk) { return @{ ok = $false; output = "acao de midia desconhecida" } }
            $n = 1; if ($a.times) { $n = [Math]::Min(10, [int]$a.times) }
            1..$n | ForEach-Object { Press-Key ([byte]$vk) }
            return @{ ok = $true; output = "midia: $($a.action)" }
        }
    }
}

function Invoke-HostCommand($c) {
    if ($script:desktopCmds -contains $c.cmd) {
        if ($c.dry) { return @{ ok = $true; output = "SIMULACAO: $($c.cmd) $($c.args | ConvertTo-Json -Compress)" } }
        try { return (Invoke-Desktop $c) } catch { return @{ ok = $false; output = "erro: $_" } }
    }
    if ($c.cmd -eq "aura_stop") {
        # Encerrar a A.U.R.A. (botao nas Configuracoes): para todos os containers dela e, se pedido, o Docker Desktop.
        # Roda num PowerShell separado depois de responder (os containers caem, entao a resposta tem de ir antes),
        # e este agente sai logo em seguida.
        $closeDocker = [bool]($c.args -and $c.args.docker)
        if ($c.dry) { return @{ ok = $true; output = "SIMULACAO: pararia os containers da A.U.R.A.$(if ($closeDocker) { ', o Docker Desktop' }) e o agente" } }
        $dir = Split-Path $PSScriptRoot -Parent
        $log = Join-Path $dir "iniciar.log"
        $script = @"
Start-Sleep -Seconds 2
Set-Location '$dir'
Add-Content -Path '$log' -Value "`$(Get-Date -Format 'dd/MM HH:mm:ss')  A.U.R.A. encerrada pela tela." -Encoding utf8
docker compose --profile '*' stop 2>`$null | Out-Null
"@
        if ($closeDocker) {
            $script += "`ndocker desktop stop 2>`$null | Out-Null`nif (`$LASTEXITCODE -ne 0) { Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue | Stop-Process -Force }"
        }
        $enc = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -EncodedCommand $enc"
        $script:quitAfter = $true
        return @{ ok = $true; output = "encerrando a A.U.R.A." }
    }
    $delay = 30
    if ($c.args -and $c.args.delay) { $delay = [int]$c.args.delay }
    $plan = switch ($c.cmd) {
        "shutdown" { @("shutdown.exe", "/s /t $delay /c ""Aura: desligando em $delay s. Diga 'cancela' para abortar.""") }
        "restart"  { @("shutdown.exe", "/r /t $delay /c ""Aura: reiniciando em $delay s. Diga 'cancela' para abortar.""") }
        "abort"    { @("shutdown.exe", "/a") }
        "lock"     { @("rundll32.exe", "user32.dll,LockWorkStation") }
        "sleep"    { @("rundll32.exe", "powrprof.dll,SetSuspendState 0,1,0") }
        "wifi_off" { @("netsh.exe", "wlan disconnect") }
        "wifi_on"  { @("netsh.exe", "wlan connect name=""PERFIL""") }
        default    { $null }
    }
    if (-not $plan) { return @{ ok = $false; output = "comando desconhecido" } }

    if ($c.cmd -eq "wifi_off") {
        # lembra a rede atual para poder reconectar depois
        $cur = (netsh wlan show interfaces) | Select-String '^\s*(Perfil|Profile)\s*:\s*(.+)$' | Select-Object -First 1
        if ($cur) { $script:lastWifi = $cur.Matches[0].Groups[2].Value.Trim() }
    }
    if ($c.cmd -eq "wifi_on") {
        $name = $script:lastWifi
        if (-not $name) {
            $p = (netsh wlan show profiles) | Select-String ':\s*(.+)$' | Select-Object -Last 1
            if ($p) { $name = $p.Matches[0].Groups[1].Value.Trim() }
        }
        if (-not $name) { return @{ ok = $false; output = "nenhuma rede Wi-Fi salva" } }
        $plan[1] = "wlan connect name=""$name"""
    }

    if ($c.dry) { return @{ ok = $true; output = "SIMULACAO: executaria $($plan[0]) $($plan[1])" } }
    if ($c.cmd -eq "sleep") {
        # responde antes, porque depois o PC dorme
        Start-Process -FilePath $plan[0] -ArgumentList $plan[1] -WindowStyle Hidden
        return @{ ok = $true; output = "suspendendo" }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $plan[0]; $psi.Arguments = $plan[1]
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $out = ($proc.StandardOutput.ReadToEnd() + $proc.StandardError.ReadToEnd()).Trim()
    $proc.WaitForExit(15000) | Out-Null
    $ok = ($proc.ExitCode -eq 0) -or ($c.cmd -eq "lock")
    if (-not $out) { $out = "ok" }
    return @{ ok = $ok; output = $out }
}

$pending = $listener.BeginGetContext($null, $null)
$down = $false
$lastBeat = Get-Date
while ($listener.IsListening) {
    # busca de comandos (assincrona: nao atrasa o atalho Ctrl+Espaco)
    if ($token) {
        if ($null -eq $poll -and (Get-Date) -ge $nextPoll) {
            $poll = $http.GetAsync("$auraUrl/api/host/next")
        } elseif ($poll -and $poll.IsCompleted) {
            $resp = if ($poll.IsFaulted -or $poll.IsCanceled) { $null } else { $poll.Result }
            $poll = $null
            if ($resp -and [int]$resp.StatusCode -eq 200) {
                try {
                    $c = $resp.Content.ReadAsStringAsync().Result | ConvertFrom-Json
                    $r = Invoke-HostCommand $c
                    $body = @{ id = $c.id; ok = $r.ok; output = $r.output } | ConvertTo-Json -Compress
                    $content = New-Object System.Net.Http.StringContent($body, $utf8, "application/json")
                    [void]$http.PostAsync("$auraUrl/api/host/result", $content).Result
                } catch {}
                if ($script:quitAfter) { $listener.Stop(); break }      # "Encerrar A.U.R.A.": o agente sai junto
            } elseif (-not $resp -or [int]$resp.StatusCode -ne 204) {
                $nextPoll = (Get-Date).AddSeconds(5)    # Aura fora do ar ou chave errada: tenta de novo em 5 s
            }
        }
    }
    if ($pending.IsCompleted) {
        try { Handle ($listener.EndGetContext($pending)) } catch {}
        $pending = $listener.BeginGetContext($null, $null)
    }
    # Ctrl (0x11) + Espaco (0x20) pressionados juntos?
    $now = (([AuraAgent.Keys]::GetAsyncKeyState(0x11) -band 0x8000) -ne 0) -and
           (([AuraAgent.Keys]::GetAsyncKeyState(0x20) -band 0x8000) -ne 0)
    if ($now -ne $down) {
        $down = $now
        Broadcast ("data: {""down"":" + $down.ToString().ToLower() + "}`n`n")
    }
    if (((Get-Date) - $lastBeat).TotalSeconds -gt 15) { Broadcast ": ping`n`n"; $lastBeat = Get-Date }
    Start-Sleep -Milliseconds 25
}
