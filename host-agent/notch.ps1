# Entalhe da A.U.R.A.: uma pilula no topo da tela do Windows, sempre visivel.
# - mostra o estado (ouvindo, pensando, falando, dormindo) e a hora; passando o mouse, o texto do estado
# - clique: abre (ou traz para a frente) a janela da A.U.R.A.; botao direito: menu
# - some quando o programa em foco esta maximizado ou em tela cheia nesse monitor, e volta quando ele sai
# - liga/desliga em Configuracoes -> Geral -> "Entalhe no topo da tela"
# Le o estado em /api/host/notch com a chave do agente (.env). Sai sozinho quando o agente do Windows para.
$ErrorActionPreference = "SilentlyContinue"
$mutex = New-Object System.Threading.Mutex($false, "Local\AuraNotch")
if (-not $mutex.WaitOne(0)) { exit }            # ja tem um entalhe rodando

Add-Type -AssemblyName PresentationFramework, PresentationCore, WindowsBase, System.Net.Http, System.Windows.Forms
Add-Type -Namespace AuraNotch -Name Win -MemberDefinition @'
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern System.IntPtr GetForegroundWindow();
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsZoomed(System.IntPtr h);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsIconic(System.IntPtr h);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool ShowWindow(System.IntPtr h, int n);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool SetForegroundWindow(System.IntPtr h);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool GetWindowRect(System.IntPtr h, out RECT r);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern System.IntPtr MonitorFromWindow(System.IntPtr h, uint f);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool GetMonitorInfo(System.IntPtr m, ref MONITORINFO i);
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern int GetClassName(System.IntPtr h, System.Text.StringBuilder s, int n);
[System.Runtime.InteropServices.DllImport("user32.dll", CharSet = System.Runtime.InteropServices.CharSet.Unicode)]
public static extern int GetWindowText(System.IntPtr h, System.Text.StringBuilder s, int n);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool IsWindowVisible(System.IntPtr h);
public delegate bool EnumProc(System.IntPtr h, System.IntPtr p);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc f, System.IntPtr p);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern int GetWindowLong(System.IntPtr h, int i);
[System.Runtime.InteropServices.DllImport("user32.dll")] public static extern int SetWindowLong(System.IntPtr h, int i, int v);
public struct RECT { public int Left, Top, Right, Bottom; }
public struct MONITORINFO { public int cbSize; public RECT rcMonitor, rcWork; public uint dwFlags; }

// janela da A.U.R.A. aberta (titulo "A.U.R.A. ..."): o app instalado ou a aba em foco do navegador
public static System.IntPtr FindAura() {
    System.IntPtr found = System.IntPtr.Zero;
    EnumWindows((h, p) => {
        if (!IsWindowVisible(h)) return true;
        var sb = new System.Text.StringBuilder(256); GetWindowText(h, sb, 256);
        if (sb.ToString().StartsWith("A.U.R.A.")) { found = h; return false; }
        return true;
    }, System.IntPtr.Zero);
    return found;
}

// o programa em foco cobre o topo do monitor principal? (maximizado ou tela cheia)
public static bool Covered(System.IntPtr self) {
    System.IntPtr h = GetForegroundWindow();
    if (h == System.IntPtr.Zero || h == self) return false;
    var sb = new System.Text.StringBuilder(64); GetClassName(h, sb, 64);
    string c = sb.ToString();
    if (c == "Progman" || c == "WorkerW" || c == "Shell_TrayWnd" || c == "Shell_SecondaryTrayWnd") return false;
    MONITORINFO mi = new MONITORINFO(); mi.cbSize = System.Runtime.InteropServices.Marshal.SizeOf(typeof(MONITORINFO));
    if (!GetMonitorInfo(MonitorFromWindow(h, 2), ref mi) || (mi.dwFlags & 1) == 0) return false;   // so o monitor principal
    if (IsZoomed(h)) return true;
    RECT r; GetWindowRect(h, out r);
    return r.Left <= mi.rcMonitor.Left && r.Top <= mi.rcMonitor.Top && r.Right >= mi.rcMonitor.Right && r.Bottom >= mi.rcMonitor.Bottom;
}
'@

$root = Split-Path $PSScriptRoot -Parent
$token = (Get-Content (Join-Path $root ".env") | Where-Object { $_ -match '^HOST_AGENT_TOKEN=(.+)$' } |
          ForEach-Object { $Matches[1].Trim() } | Select-Object -First 1)
$auraUrl = "http://127.0.0.1:8765"
$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(4)
if ($token) { $http.DefaultRequestHeaders.Add("X-Agent-Token", $token) }
$agentHttp = New-Object System.Net.Http.HttpClient
$agentHttp.Timeout = [TimeSpan]::FromSeconds(3)
$script:agentReq = $null

[xml]$xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        WindowStyle="None" AllowsTransparency="True" Background="Transparent" Topmost="True"
        ShowInTaskbar="False" ResizeMode="NoResize" SizeToContent="WidthAndHeight" ShowActivated="False" Title="AuraNotch">
  <Border x:Name="Pill" Background="#F2050608" CornerRadius="0,0,16,16" Padding="14,5,14,7" Cursor="Hand"
          BorderBrush="#33FFFFFF" BorderThickness="1,0,1,1">
    <StackPanel>
      <StackPanel Orientation="Horizontal" HorizontalAlignment="Center">
        <Grid Width="16" Height="16" VerticalAlignment="Center">
          <Ellipse x:Name="Glow" Width="16" Height="16" Fill="#F08C00" Opacity="0.35"/>
          <Ellipse x:Name="Core" Width="9" Height="9" Fill="#F08C00"/>
        </Grid>
        <TextBlock x:Name="Name" Text="A.U.R.A." Foreground="#E8EEF5" FontFamily="Segoe UI Semibold" FontSize="11"
                   Margin="7,0,0,0" VerticalAlignment="Center"/>
        <Ellipse x:Name="Dot" Width="6" Height="6" Fill="#666" Margin="9,0,0,0" VerticalAlignment="Center"/>
        <TextBlock x:Name="Clock" Text="--:--" Foreground="#B8C2CC" FontFamily="Segoe UI" FontSize="11"
                   Margin="7,0,0,0" VerticalAlignment="Center"/>
      </StackPanel>
      <TextBlock x:Name="Status" Text="" Foreground="#B8C2CC" FontFamily="Segoe UI" FontSize="11"
                 HorizontalAlignment="Center" Margin="0,4,0,0" Visibility="Collapsed" MaxWidth="320" TextTrimming="CharacterEllipsis"/>
    </StackPanel>
  </Border>
</Window>
'@
$win = [Windows.Markup.XamlReader]::Load((New-Object System.Xml.XmlNodeReader $xaml))
$el = @{}
foreach ($n in "Pill", "Glow", "Core", "Name", "Dot", "Clock", "Status") { $el[$n] = $win.FindName($n) }

# fora do Alt+Tab e sem roubar o foco ao clicar
$win.Add_SourceInitialized({
    $h = (New-Object System.Windows.Interop.WindowInteropHelper $win).Handle
    $ex = [AuraNotch.Win]::GetWindowLong($h, -20)
    [void][AuraNotch.Win]::SetWindowLong($h, -20, ($ex -bor 0x80 -bor 0x08000000))   # TOOLWINDOW | NOACTIVATE
})
function Place {
    $win.Left = [math]::Round(([System.Windows.SystemParameters]::PrimaryScreenWidth - $win.ActualWidth) / 2)
    $win.Top = 0
}
$win.Add_SizeChanged({ Place })

function Open-Aura {
    $h = [AuraNotch.Win]::FindAura()
    if ($h -ne [IntPtr]::Zero) {
        if ([AuraNotch.Win]::IsIconic($h)) { [void][AuraNotch.Win]::ShowWindow($h, 9) }
        [void][AuraNotch.Win]::SetForegroundWindow($h); return
    }
    if ($script:offline) {
        # A.U.R.A. desligada: liga tudo (Docker, containers) e abre a janela
        Start-Process powershell.exe -WindowStyle Hidden -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $root 'iniciar.ps1')`""
        return
    }
    $b = foreach ($exe in "msedge.exe", "chrome.exe") { foreach ($r in "HKLM:", "HKCU:") {
        (Get-ItemProperty "$r\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\$exe").'(default)' } }
    $b = $b | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
    if ($b) { Start-Process $b "--app=$auraUrl" } else { Start-Process $auraUrl }
}

$el.Pill.Add_MouseLeftButtonUp({ Open-Aura })
$el.Pill.Add_MouseEnter({ if ($el.Status.Text) { $el.Status.Visibility = "Visible" } })
$el.Pill.Add_MouseLeave({ $el.Status.Visibility = "Collapsed" })

$menu = New-Object System.Windows.Controls.ContextMenu
$miOpen = New-Object System.Windows.Controls.MenuItem; $miOpen.Header = "Abrir A.U.R.A."
$miOpen.Add_Click({ Open-Aura })
$miClose = New-Object System.Windows.Controls.MenuItem; $miClose.Header = "Fechar o entalhe (volta ao reiniciar)"
$miClose.Add_Click({ $win.Close() })
[void]$menu.Items.Add($miOpen); [void]$menu.Items.Add($miClose)
$el.Pill.ContextMenu = $menu

# cores por estado: [nucleo, brilho pulsando?, texto padrao]
$styles = @{
    idle      = @("#3DDC84", $false, "Pronta")
    sleeping  = @("#3DDC84", $false, "Dormindo")
    listening = @("#3EC7FF", $true, "Ouvindo")
    thinking  = @("#A66BFF", $true, "Pensando")
    speaking  = @("#F08C00", $true, "Falando")
    closed    = @("#8A96A3", $false, "Janela fechada")
    offline   = @("#555E68", $false, "Desligada")
}
$conv = New-Object System.Windows.Media.BrushConverter
$script:state = "offline"; $script:offline = $true; $script:enabled = $true
$script:req = $null; $script:nextReq = Get-Date; $script:agentFails = 0; $script:nextAgent = (Get-Date).AddSeconds(5)
$script:phase = 0.0

function Apply($s, $text) {
    $st = $styles[$s]; if (-not $st) { $st = $styles.idle }
    $script:state = $s
    $col = $conv.ConvertFromString($st[0])
    $el.Core.Fill = $col; $el.Glow.Fill = $col; $el.Dot.Fill = $col
    $el.Core.Opacity = if ($s -eq "sleeping" -or $s -eq "offline") { 0.55 } else { 1 }
    $el.Status.Text = if ($text) { $text } else { $st[2] }
}
Apply "offline" ""

$timer = New-Object System.Windows.Threading.DispatcherTimer
$timer.Interval = [TimeSpan]::FromMilliseconds(120)
$timer.Add_Tick({
    $now = Get-Date
    $el.Clock.Text = $now.ToString("HH:mm")

    # estado da A.U.R.A. (pedido assincrono: nunca trava a janela)
    if ($null -eq $script:req -and $now -ge $script:nextReq) {
        $script:req = $http.GetAsync("$auraUrl/api/host/notch")
    } elseif ($script:req -and $script:req.IsCompleted) {
        $resp = if ($script:req.IsFaulted -or $script:req.IsCanceled) { $null } else { $script:req.Result }
        $script:req = $null
        if ($resp -and $resp.IsSuccessStatusCode) {
            $d = $resp.Content.ReadAsStringAsync().Result | ConvertFrom-Json
            $script:offline = $false; $script:enabled = [bool]$d.enabled
            if ($d.name) { $el.Name.Text = $d.name }
            Apply $d.state $d.text
            $script:nextReq = $now.AddMilliseconds(400)
        } else {
            $script:offline = $true; Apply "offline" "Desligada - clique para ligar"
            $script:nextReq = $now.AddSeconds(3)
        }
    }

    # o agente do Windows parou (ex.: "Encerrar A.U.R.A.")? o entalhe sai junto
    if ($null -eq $script:agentReq -and $now -ge $script:nextAgent) {
        $script:agentReq = $agentHttp.GetAsync("http://127.0.0.1:8766/metrics")
    } elseif ($script:agentReq -and $script:agentReq.IsCompleted) {
        $ok = -not ($script:agentReq.IsFaulted -or $script:agentReq.IsCanceled) -and $script:agentReq.Result.IsSuccessStatusCode
        $script:agentReq = $null; $script:nextAgent = $now.AddSeconds(5)
        if ($ok) { $script:agentFails = 0 } else { $script:agentFails++ }
        if ($script:agentFails -ge 3) { $win.Close(); return }
    }

    # pulsa enquanto ouve, pensa ou fala
    $script:phase += 0.35
    if ($styles[$script:state][1]) {
        $k = 0.5 + 0.5 * [math]::Sin($script:phase)
        $el.Glow.Opacity = 0.25 + 0.45 * $k; $el.Glow.Width = $el.Glow.Height = 11 + 5 * $k
    } else { $el.Glow.Opacity = 0.2; $el.Glow.Width = $el.Glow.Height = 13 }

    # some com programa maximizado/tela cheia (ou desligado nas configuracoes)
    $h = (New-Object System.Windows.Interop.WindowInteropHelper $win).Handle
    $show = $script:enabled -and -not [AuraNotch.Win]::Covered($h)
    if ($show -and -not $win.IsVisible) { $win.Show(); $win.Topmost = $true; Place }
    elseif (-not $show -and $win.IsVisible -and -not $menu.IsOpen) { $win.Hide() }
})
$app = New-Object System.Windows.Application
$app.ShutdownMode = "OnExplicitShutdown"      # esconder a janela nao encerra o entalhe; fechar, sim
$win.Add_Loaded({ Place; $timer.Start() })
$win.Add_Closed({ $timer.Stop(); $app.Shutdown() })
[void]$app.Run($win)
$mutex.ReleaseMutex()
