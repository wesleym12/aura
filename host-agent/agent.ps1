# Agente do Windows para a A.U.R.A.
# - /metrics : nome do Windows, musica tocando (qualquer programa) e volume do sistema. Sem dados de hardware.
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

# ---- volume do sistema (Core Audio): ler e ajustar o volume exato ----
if (-not ('AuraVol' -as [type])) {
Add-Type -TypeDefinition @"
using System; using System.Runtime.InteropServices;
[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAuraEndpointVolume {
  int a(); int b(); int c(); int d();
  int SetMasterVolumeLevelScalar(float level, ref Guid ctx);
  int e(); int GetMasterVolumeLevelScalar(out float level);
  int f(); int g(); int h(); int i(); int SetMute(bool mute, ref Guid ctx); int GetMute(out bool mute);
}
[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAuraMMDevice { int Activate(ref Guid id, int ctx, IntPtr p, [MarshalAs(UnmanagedType.IUnknown)] out object o); }
[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAuraMMDeviceEnumerator { int a(); int GetDefaultAudioEndpoint(int flow, int role, out IAuraMMDevice d); }
[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")] class AuraMMDeviceEnumerator {}
public static class AuraVol {
  static IAuraEndpointVolume Ep() {
    var en = (IAuraMMDeviceEnumerator)(new AuraMMDeviceEnumerator()); IAuraMMDevice dev; en.GetDefaultAudioEndpoint(0, 1, out dev);
    var iid = typeof(IAuraEndpointVolume).GUID; object o; dev.Activate(ref iid, 23, IntPtr.Zero, out o); return (IAuraEndpointVolume)o;
  }
  public static int Get() { float v; Ep().GetMasterVolumeLevelScalar(out v); return (int)Math.Round(v * 100); }
  public static bool Muted() { bool m; Ep().GetMute(out m); return m; }
  public static void Set(int level) { var g = Guid.Empty; Ep().SetMasterVolumeLevelScalar(Math.Max(0, Math.Min(100, level)) / 100f, ref g); Ep().SetMute(false, ref g); }
}
"@
}

# ---- metricas numa thread separada (leitura leva ~1 s e nao pode atrasar o atalho) ----
$shared = [hashtable]::Synchronized(@{ json = '{}'; art = ''; artKey = '' })
$metricsPs = [powershell]::Create()
[void]$metricsPs.AddScript({
    param($shared)
    $ErrorActionPreference = "SilentlyContinue"
    $osInfo = Get-CimInstance Win32_OperatingSystem
    $osName = "$($osInfo.Caption) (build $($osInfo.BuildNumber))".Replace("Microsoft ", "")
    # o que esta tocando em qualquer programa (Spotify, YouTube no navegador...), pelos controles de midia do Windows
    $mgr = $null
    try {
        Add-Type -AssemblyName System.Runtime.WindowsRuntime
        $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
            $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
        function Await($op, [Type]$t) { $task = $asTask.MakeGenericMethod($t).Invoke($null, @($op)); [void]$task.Wait(2000); $task.Result }
        [void][Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager, Windows.Media.Control, ContentType = WindowsRuntime]
        $mgr = Await ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager]::RequestAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager])
    } catch { $mgr = $null }
    while ($true) {
        $med = $null
        if ($mgr) {
            try {
                $ses = $mgr.GetCurrentSession()
                if ($ses) {
                    $p = Await ($ses.TryGetMediaPropertiesAsync()) ([Windows.Media.Control.GlobalSystemMediaTransportControlsSessionMediaProperties])
                    $id = [string]$ses.SourceAppUserModelId
                    $key = "$id|$($p.Title)|$($p.Artist)"
                    if ($key -ne $shared.artKey) {               # musica nova: pega a capa uma vez so
                        $shared.artKey = $key; $shared.art = ''
                        if ($p.Thumbnail) {
                            try {
                                $rs = Await ($p.Thumbnail.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
                                $ms = New-Object System.IO.MemoryStream
                                [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($rs).CopyTo($ms)
                                $shared.art = [Convert]::ToBase64String($ms.ToArray())
                            } catch {}
                        }
                    }
                    $app = switch -Regex ($id) { 'spotify' { 'Spotify' } 'msedge' { 'Edge' } 'chrome' { 'Chrome' } 'firefox' { 'Firefox' }
                                                 default { ($id -split '[\\!]')[-1] -replace '\.exe$', '' } }
                    if ($p.Title) {
                        $med = [ordered]@{ title = $p.Title; artist = $p.Artist; app = $app
                                           playing = ($ses.GetPlaybackInfo().PlaybackStatus.ToString() -eq 'Playing')
                                           art = [bool]$shared.art; key = [string]$key.GetHashCode() }
                    }
                }
            } catch {}
        }
        $vol = $null; $muted = $null
        try { $vol = [AuraVol]::Get(); $muted = [AuraVol]::Muted() } catch {}
        $shared.json = ([ordered]@{
            os       = "WIN"
            os_name  = $osName
            media    = $med
            volume   = $vol
            muted    = $muted
        } | ConvertTo-Json -Compress -Depth 3)
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
$script:clipItems = New-Object System.Collections.ArrayList   # historico do que foi copiado (so na memoria)
$script:clipUntil = Get-Date
$script:clipLast = ""
$script:clipNext = Get-Date
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
        "/art" {
            # capa da musica que esta tocando (a pagina pede quando a musica muda)
            if ($shared.art) {
                $b = [Convert]::FromBase64String($shared.art)
                $res.ContentType = "image/jpeg"; $res.AddHeader("Cache-Control", "no-store")
                $res.OutputStream.Write($b, 0, $b.Length)
            } else { $res.StatusCode = 404 }
            $res.Close()
        }
        "/clip" {
            # historico do que voce copiou (texto). So grava enquanto a pagina pede com ?on=1 (opcao ligada).
            if ($ctx.Request.QueryString["on"] -eq "1") { $script:clipUntil = (Get-Date).AddSeconds(30) }
            if ($ctx.Request.QueryString["clear"] -eq "1") { $script:clipItems.Clear() }
            $b = $utf8.GetBytes((ConvertTo-Json -Compress -InputObject @($script:clipItems)))
            $res.ContentType = "application/json"; $res.AddHeader("Cache-Control", "no-store")
            $res.OutputStream.Write($b, 0, $b.Length); $res.Close()
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
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsIconic(System.IntPtr h);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint flags, System.UIntPtr extra);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, System.UIntPtr e);
'@
$script:desktopCmds = @("windows", "focus", "open", "open_in_tab", "ui", "click", "type", "keys", "screenshot", "media",
                        "clip_set", "find_files", "reveal", "desktop_scan", "desktop_organize", "desktop_undo", "yt_videos")
$script:uiElems = @()

# so "restaura" a janela se ela estiver minimizada: restaurar uma janela maximizada tira ela do maximizado
function Show-Front([IntPtr]$h) {
    if ([AuraAgent.Win]::IsIconic($h)) { [AuraAgent.Win]::ShowWindow($h, 9) | Out-Null }
}

function Press-Key([byte]$vk) {
    [AuraAgent.Win]::keybd_event($vk, 0, 0, [UIntPtr]::Zero)
    [AuraAgent.Win]::keybd_event($vk, 0, 2, [UIntPtr]::Zero)
}

# registro do Desfazer da organizacao (pasta de dados locais do usuario, criada se faltar)
function Undo-LogPath {
    $base = [Environment]::GetFolderPath('LocalApplicationData')
    if (-not $base) { $base = Join-Path $env:USERPROFILE "AppData\Local" }
    $dir = Join-Path $base "AURA"; New-Item -ItemType Directory -Force -Path $dir | Out-Null
    return (Join-Path $dir "desktop-undo.json")
}

# Le o registro do Desfazer como lista. No PowerShell 5.1 o ConvertFrom-Json entrega o array inteiro como um item so;
# o ForEach-Object o desmonta em um movimento por item.
function Read-UndoLog([string]$log) {
    if (-not (Test-Path -LiteralPath $log)) { return @() }
    try { return @(Get-Content -LiteralPath $log -Raw -Encoding UTF8 | ConvertFrom-Json | ForEach-Object { $_ }) } catch { return @() }
}

# Organiza os arquivos soltos da area de trabalho em pastas por tipo (atalhos, programas e pastas ficam onde estao).
# Guarda cada movimento para o Desfazer. $only = so conta, sem mexer.
function Desktop-Organize([bool]$only) {
    $desk = [Environment]::GetFolderPath('Desktop')
    $kinds = [ordered]@{
        Imagens = 'jpg|jpeg|png|gif|webp|bmp|heic|svg|tif|tiff'; PDFs = 'pdf'; Documentos = 'doc|docx|txt|rtf|odt|md'
        Planilhas = 'xls|xlsx|xlsm|csv|ods'; Apresentacoes = 'ppt|pptx|odp'; Compactados = 'zip|rar|7z|tar|gz'
        Videos = 'mp4|mkv|avi|mov|wmv|webm'; Audios = 'mp3|wav|m4a|ogg|flac'
    }
    $skip = 'lnk|url|exe|msi|bat|cmd|ps1|ini|appref-ms'
    $files = @(Get-ChildItem -LiteralPath $desk -File | Where-Object { $_.Extension.TrimStart('.') -notmatch "^($skip)$" -and -not $_.Attributes.HasFlag([IO.FileAttributes]::Hidden) })
    $plan = @{}
    foreach ($f in $files) {
        $ext = $f.Extension.TrimStart('.').ToLower(); $k = 'Outros'
        foreach ($name in $kinds.Keys) { if ($ext -match "^($($kinds[$name]))$") { $k = $name; break } }
        if (-not $plan[$k]) { $plan[$k] = New-Object System.Collections.ArrayList }
        [void]$plan[$k].Add($f)
    }
    $summary = ($plan.Keys | Sort-Object | ForEach-Object { "$($plan[$_].Count) $($_.ToLower())" }) -join ", "
    if (-not $files) { return @{ ok = $true; output = "a area de trabalho ja esta organizada: nenhum arquivo solto" } }
    if ($only) { return @{ ok = $true; output = "$($files.Count) arquivo(s) solto(s): $summary" } }
    $root = Join-Path $desk "Organizado pela AURA"
    # registro do Desfazer: caminho fixo, soma com o que ja havia e e gravado a cada arquivo movido
    $log = Undo-LogPath
    $moves = New-Object System.Collections.ArrayList
    foreach ($m in (Read-UndoLog $log)) { [void]$moves.Add(@{ from = $m.from; to = $m.to }) }
    foreach ($k in $plan.Keys) {
        $dir = Join-Path $root $k; New-Item -ItemType Directory -Force -Path $dir | Out-Null
        foreach ($f in $plan[$k]) {
            $to = Join-Path $dir $f.Name; $i = 2
            while (Test-Path -LiteralPath $to) { $to = Join-Path $dir ("{0} ({1}){2}" -f $f.BaseName, $i, $f.Extension); $i++ }
            Move-Item -LiteralPath $f.FullName -Destination $to -ErrorAction Stop
            [void]$moves.Add(@{ from = $f.FullName; to = $to })
            ConvertTo-Json -InputObject @($moves) | Set-Content -LiteralPath $log -Encoding UTF8
        }
    }
    return @{ ok = $true; output = "organizei $($files.Count) arquivo(s) em 'Organizado pela AURA': $summary" }
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
            $t = ([string]$a.title).Trim()
            if (-not $t) { return @{ ok = $false; output = "diga o nome da janela" } }   # vazio casaria com qualquer janela
            $alias = @{ "bloco de notas" = "notepad"; "calculadora" = "calculatorapp"; "explorador" = "explorer"; "navegador" = "msedge" }
            $proc = $alias[$t.ToLower()]
            $wins = Get-Process | Where-Object { $_.MainWindowTitle }
            $p = $wins | Where-Object { $_.MainWindowTitle -like "*$t*" -or $_.ProcessName -like "*$t*" -or ($proc -and $_.ProcessName -like "*$proc*") } |
                 Select-Object -First 1
            if (-not $p) {
                $lista = ($wins | ForEach-Object { "$($_.ProcessName): $($_.MainWindowTitle)" }) -join "; "
                return @{ ok = $false; output = "nenhuma janela com '$t'. Janelas abertas: $lista" }
            }
            Show-Front $p.MainWindowHandle
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
                        "configuracoes" = "ms-settings:"; "gerenciador de tarefas" = "taskmgr.exe" }
            $k = $t.ToLower().Normalize([Text.NormalizationForm]::FormD) -replace '\p{Mn}', ''     # ignora acentos (configuracoes com ou sem acento)
            if ($known.ContainsKey($k)) { Start-Process $known[$k]; return @{ ok = $true; output = "abriu $t" } }
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
        "clip_set" {
            $t = [string]$a.text
            if (-not $t) { return @{ ok = $false; output = "nada para copiar" } }
            try { [System.Windows.Forms.Clipboard]::SetText($t); $script:clipLast = $t; return @{ ok = $true; output = "copiado ($($t.Length) caracteres)" } }
            catch { return @{ ok = $false; output = "nao consegui copiar: $_" } }
        }
        "find_files" {
            # indice de pesquisa do Windows (rapido): nome do arquivo, na pasta do usuario, mais recentes primeiro
            $q = ([string]$a.query).Trim() -replace "[\'%_\[\]]", ' '
            if ($q.Length -lt 2) { return @{ ok = $false; output = "diga parte do nome do arquivo" } }
            $root = $env:USERPROFILE.Replace('\', '/')
            $words = ($q -split '\s+' | Where-Object { $_ } | ForEach-Object { "System.FileName LIKE '%$_%'" }) -join " AND "
            # ItemUrl tem o caminho real (o ItemPathDisplay vem traduzido, "C:\Usuarios\...", e nao abre)
            $sql = "SELECT TOP 15 System.ItemUrl, System.DateModified FROM SYSTEMINDEX WHERE $words AND SCOPE='file:$root' " +
                   "AND System.ItemUrl NOT LIKE '%/AppData/%' ORDER BY System.DateModified DESC"
            try {
                $con = New-Object -ComObject ADODB.Connection
                $con.Open("Provider=Search.CollatorDSO;Extended Properties='Application=Windows';")
                $rs = $con.Execute($sql); $out = @()
                while (-not $rs.EOF) {
                    $path = ([string]$rs.Fields.Item('System.ItemUrl').Value -replace '^file:', '').Replace('/', '\')
                    $out += "$path  ($(([datetime]$rs.Fields.Item('System.DateModified').Value).ToString('dd/MM/yyyy')))"
                    $rs.MoveNext()
                }
                $rs.Close(); $con.Close()
            } catch { return @{ ok = $false; output = "a pesquisa do Windows nao respondeu: $_" } }
            if (-not $out) { return @{ ok = $true; output = "nenhum arquivo com '$q' na pasta do usuario" } }
            return @{ ok = $true; output = ($out -join "`n") }
        }
        "reveal" {
            # mostra o arquivo selecionado no Explorador (so dentro da pasta do usuario)
            $p = [string]$a.path
            if (-not $p -or -not (Test-Path -LiteralPath $p) -or -not ([IO.Path]::GetFullPath($p).StartsWith($env:USERPROFILE, [StringComparison]::OrdinalIgnoreCase))) {
                return @{ ok = $false; output = "arquivo nao encontrado na pasta do usuario" }
            }
            Start-Process explorer.exe -ArgumentList "/select,`"$([IO.Path]::GetFullPath($p))`""
            return @{ ok = $true; output = "mostrando $p no Explorador" }
        }
        "desktop_scan" { return (Desktop-Organize $true) }
        "desktop_organize" { return (Desktop-Organize $false) }
        "desktop_undo" {
            $log = Undo-LogPath
            $dir = Join-Path ([Environment]::GetFolderPath('Desktop')) "Organizado pela AURA"
            $moves = Read-UndoLog $log
            if (-not $moves.Count -and (Test-Path -LiteralPath $dir)) {
                # sem o registro: tudo que esta em "Organizado pela AURA" veio da area de trabalho, volta para la
                $moves = @(Get-ChildItem -LiteralPath $dir -Directory | ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -File } |
                           ForEach-Object { [pscustomobject]@{ from = (Join-Path ([Environment]::GetFolderPath('Desktop')) $_.Name); to = $_.FullName } })
            }
            if (-not $moves.Count) { return @{ ok = $false; output = "nada para desfazer" } }
            $n = 0
            foreach ($m in $moves) {
                if ((Test-Path -LiteralPath $m.to) -and -not (Test-Path -LiteralPath $m.from)) { Move-Item -LiteralPath $m.to -Destination $m.from; $n++ }
            }
            if (-not $n) { return @{ ok = $false; output = "nenhum arquivo voltou: eles ja nao estao em 'Organizado pela AURA'" } }
            if (Test-Path -LiteralPath $log) { Remove-Item -LiteralPath $log }
            Get-ChildItem -LiteralPath $dir -Directory -ErrorAction SilentlyContinue | Where-Object { -not (Get-ChildItem -LiteralPath $_.FullName -Force) } | Remove-Item
            if ((Test-Path $dir) -and -not (Get-ChildItem -LiteralPath $dir -Force)) { Remove-Item -LiteralPath $dir }
            return @{ ok = $true; output = "$n arquivo(s) voltaram para a area de trabalho" }
        }
        "yt_videos" {
            # videos que aparecem na aba do YouTube, na ordem da pagina (titulo + id), pela acessibilidade do
            # navegador. So leitura: nao clica em nada. O navegador monta essa arvore na primeira consulta.
            $w = Get-Process | Where-Object { $_.MainWindowTitle -like "*YouTube*" -and $_.ProcessName -match 'msedge|chrome|firefox|brave|opera|vivaldi' } | Select-Object -First 1
            if (-not $w) { return @{ ok = $false; output = "nao ha aba do YouTube aberta em primeiro plano no navegador" } }
            $root = [System.Windows.Automation.AutomationElement]::FromHandle($w.MainWindowHandle)
            $cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty, [System.Windows.Automation.ControlType]::Hyperlink)
            $links = $null
            for ($try = 0; $try -lt 4; $try++) {
                $links = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
                if ($links.Count -gt 5) { break }
                Start-Sleep -Milliseconds 900
            }
            $seen = @{}; $out = @()
            foreach ($l in $links) {
                $v = $null
                try { $v = $l.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).Current.Value } catch {}
                if (-not $v -or $v -notmatch 'youtube\.com/(watch\?v=|shorts/)([\w-]{11})') { continue }
                $id = $Matches[2]; $name = ([string]$l.Current.Name).Trim()
                # botoes genericos ("Assistir", "Reproduzir tudo"...) nao sao o titulo do video
                if ($name.Length -lt 6 -or $name -match '^(Assistir|Watch|Reproduzir|Play|Ver tudo|Mix)') { continue }
                if ($seen[$id]) { continue }; $seen[$id] = 1
                if ($name.Length -gt 90) { $name = $name.Substring(0, 90) }
                $out += "$($out.Count + 1). $name | $id"
                if ($out.Count -ge 15) { break }
            }
            if (-not $out) { return @{ ok = $false; output = "nao achei videos na aba do YouTube (a pagina ainda estava carregando?)" } }
            return @{ ok = $true; output = ($out -join "`n") }
        }
        "open_in_tab" {
            # abre o endereco NA ABA que ja mostra o site (ex.: YouTube), em vez de abrir outra janela.
            # So digita depois de confirmar que a janela em foco e mesmo a do site: nunca digita na janela errada.
            $url = [string]$a.url; $match = [string]$a.match
            if ($url -notmatch '^https://') { return @{ ok = $false; output = "endereco invalido" } }
            $browsers = 'msedge|chrome|firefox|brave|opera|vivaldi'
            $w = Get-Process | Where-Object { $_.MainWindowTitle -like "*$match*" -and $_.ProcessName -match $browsers } | Select-Object -First 1
            if ($w) {
                Show-Front $w.MainWindowHandle
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
            if ([string]$a.action -eq "set_volume") {              # volume exato (0 a 100)
                try { [AuraVol]::Set([int]$a.level); return @{ ok = $true; output = "volume: $([AuraVol]::Get())%" } }
                catch { return @{ ok = $false; output = "nao consegui mudar o volume" } }
            }
            $vk = @{ volume_up = 0xAF; volume_down = 0xAE; mute = 0xAD; play_pause = 0xB3; next = 0xB0; previous = 0xB1 }[[string]$a.action]
            if (-not $vk) { return @{ ok = $false; output = "acao de midia desconhecida" } }
            $n = 1; if ($a.times) { $n = [Math]::Min(10, [int]$a.times) }
            1..$n | ForEach-Object { Press-Key ([byte]$vk) }
            $out = "midia: $($a.action)"
            if ([string]$a.action -like "volume_*" -or [string]$a.action -eq "mute") {
                Start-Sleep -Milliseconds 120
                try { $out = if ([AuraVol]::Muted()) { "som mudo" } else { "volume: $([AuraVol]::Get())%" } } catch {}
            }
            return @{ ok = $true; output = $out }
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
    # shutdown/netsh escrevem na pagina de codigo do console (OEM): sem isto os acentos chegam quebrados
    $oem = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
    $psi.StandardOutputEncoding = $oem; $psi.StandardErrorEncoding = $oem
    $proc = [System.Diagnostics.Process]::Start($psi)
    $out = ($proc.StandardOutput.ReadToEnd() + $proc.StandardError.ReadToEnd()).Trim()
    $proc.WaitForExit(15000) | Out-Null
    $ok = ($proc.ExitCode -eq 0) -or ($c.cmd -eq "lock")
    if ($c.cmd -eq "abort" -and $proc.ExitCode -eq 1116) { $ok = $true; $out = "nao havia desligamento agendado" }
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
    if ((Get-Date) -lt $script:clipUntil -and (Get-Date) -ge $script:clipNext) {
        $script:clipNext = (Get-Date).AddSeconds(1)
        try {
            $txt = [System.Windows.Forms.Clipboard]::GetText()
            if ($txt -and $txt -ne $script:clipLast) {
                $script:clipLast = $txt
                $item = $txt.Trim(); if ($item.Length -gt 1000) { $item = $item.Substring(0, 1000) }
                if ($item) {
                    $script:clipItems.Remove($item)
                    $script:clipItems.Insert(0, $item)
                    while ($script:clipItems.Count -gt 25) { $script:clipItems.RemoveAt($script:clipItems.Count - 1) }
                }
            }
        } catch {}
    }
    Start-Sleep -Milliseconds 25
}
