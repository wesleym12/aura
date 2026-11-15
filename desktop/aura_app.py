"""A.U.R.A. na area de trabalho (Windows e Linux), com dois modos:

- janela:  a A.U.R.A. numa janela propria, como um aplicativo comum.
- entalhe: uma pilula no topo da tela, sempre visivel, mostrando se ela esta ouvindo, pensando ou falando.
           Clique: a A.U.R.A. inteira abre ali mesmo, descendo do entalhe; clique fora (ou em recolher) e ela volta
           a ser pilula. Some quando um programa esta maximizado ou em tela cheia, e volta quando ele sai.

Troca de modo em Configuracoes -> Geral -> "Modo de exibicao" (a escolha fica neste computador).
A pagina continua viva nos dois modos: a voz e a palavra de ativacao funcionam mesmo com o entalhe recolhido.

Uso: python aura_app.py [--fundo] [--url http://127.0.0.1:8765]
     --fundo: inicio automatico no logon; no modo janela nao abre nada (so o entalhe aparece sozinho).
"""
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

if sys.platform.startswith("linux") and os.getenv("WAYLAND_DISPLAY") and os.getenv("DISPLAY"):
    # no Wayland o app nao consegue se posicionar nem ficar por cima: roda pelo XWayland (o entalhe precisa disso)
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import webview  # noqa: E402

URL = os.getenv("AURA_URL", "http://127.0.0.1:8765").rstrip("/")
if "--url" in sys.argv:
    URL = sys.argv[sys.argv.index("--url") + 1].rstrip("/")
WIN = sys.platform == "win32"
CONF_DIR = Path(os.getenv("APPDATA") or Path.home() / ".config") / ("AURA" if WIN else "aura")
CONF = CONF_DIR / "desktop.json"

PILL = (130, 34)          # entalhe recolhido: so o rostinho (largura, altura)
PANEL = (860, 540)        # entalhe aberto: menu lateral + conteudo
WINDOW = (1280, 820)      # modo janela



def load_conf() -> dict:
    try:
        return json.loads(CONF.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_conf(**kw):
    c = load_conf() | kw
    CONF_DIR.mkdir(parents=True, exist_ok=True)
    CONF.write_text(json.dumps(c), "utf-8")


def single_instance() -> socket.socket | None:
    """So uma A.U.R.A. de mesa por vez (porta local como trava). Se ja houver uma aberta, pede para ela aparecer
    (abrir pelo atalho de novo traz a janela, ou abre o entalhe) e devolve None."""
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 8767))
        s.listen(2)
        return s
    except OSError:
        if "--fundo" not in sys.argv:
            try:
                with socket.create_connection(("127.0.0.1", 8767), timeout=2) as c:
                    c.sendall(b"show")
            except OSError:
                pass
        return None


def server_up() -> bool:
    try:
        urllib.request.urlopen(URL + "/manifest.webmanifest", timeout=2)
        return True
    except Exception:
        return False


def allow_microphone():
    """WebView2 (Windows): libera o microfone so para a pagina da A.U.R.A., sem a pergunta do navegador
    (no entalhe recolhido ela nem caberia). No Linux o pywebview (Qt) ja libera o microfone sozinho."""
    if not WIN:
        return
    try:
        from webview.platforms import edgechromium as ec
        from Microsoft.Web.WebView2.Core import CoreWebView2PermissionKind, CoreWebView2PermissionState
    except Exception:
        return
    original = ec.EdgeChrome.on_webview_ready

    def on_permission(_sender, e):
        if str(e.Uri).startswith(URL + "/") and e.PermissionKind == CoreWebView2PermissionKind.Microphone:
            e.State = CoreWebView2PermissionState.Allow

    def ready(self, sender, args):
        original(self, sender, args)
        if args.IsSuccess:
            sender.CoreWebView2.PermissionRequested += on_permission
    ec.EdgeChrome.on_webview_ready = ready


LOADING = """<!doctype html><meta charset="utf-8"><body style="margin:0;background:#050608;color:#b8c2cc;
font:13px 'Segoe UI',sans-serif;display:grid;place-items:center;height:100vh;overflow:hidden">
<div>A.U.R.A. ligando…</div><script>setInterval(()=>pywebview.api.retry(),3000)</script>"""


# ---------- deteccao de programa maximizado/tela cheia (o entalhe recolhido some) ----------
if WIN:
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    u32.MonitorFromWindow.restype = wintypes.HMONITOR
    u32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    def covered(own_title: str) -> bool:
        h = u32.GetForegroundWindow()
        if not h:
            return False
        buf = ctypes.create_unicode_buffer(256)
        u32.GetClassNameW(h, buf, 256)
        if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        u32.GetWindowTextW(h, buf, 256)
        if buf.value == own_title:
            return False
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if not u32.GetMonitorInfoW(u32.MonitorFromWindow(h, 2), ctypes.byref(mi)) or not mi.dwFlags & 1:
            return False                     # so importa o monitor principal, onde o entalhe fica
        if u32.IsZoomed(h):
            return True
        r = wintypes.RECT()
        u32.GetWindowRect(h, ctypes.byref(r))
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom

    ICON = str(Path(__file__).resolve().parent.parent / "aura" / "web" / "icons" / "aura.ico")
    u32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    u32.LoadImageW.restype = wintypes.HANDLE
    u32.GetWindowLongW.restype = ctypes.c_long
    try:   # o Windows agrupa e mostra o app como "A.U.R.A." (e nao como o python)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AURA.Desktop")
    except (AttributeError, OSError):
        pass

    def find_hwnd(title: str) -> int:
        """Janela deste processo com o titulo (a mais recente, se houver duas durante a troca de modo)."""
        found = []
        proc = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

        def cb(h, _):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
            if pid.value == os.getpid():
                buf = ctypes.create_unicode_buffer(64)
                u32.GetWindowTextW(h, buf, 64)
                if buf.value == title:
                    found.append(h)
            return True
        u32.EnumWindows(proc(cb), 0)
        return found[0] if found else 0

    def style_window(hwnd: int, taskbar: bool):
        """Icone da A.U.R.A. na janela e, no entalhe, fora da barra de tarefas e do Alt+Tab."""
        if not hwnd:
            return
        ico = u32.LoadImageW(None, ICON, 1, 0, 0, 0x10 | 0x40)          # IMAGE_ICON, LOADFROMFILE | DEFAULTSIZE
        if ico:
            u32.SendMessageW(hwnd, 0x80, 1, ico)                          # WM_SETICON grande
            u32.SendMessageW(hwnd, 0x80, 0, ico)                          # e pequeno
        if not taskbar:
            ex = u32.GetWindowLongW(hwnd, -20)
            u32.ShowWindow(hwnd, 0)
            u32.SetWindowLongW(hwnd, -20, (ex | 0x80) & ~0x40000)          # TOOLWINDOW, sem APPWINDOW
            u32.ShowWindow(hwnd, 4)                                       # mostra de novo sem roubar o foco

    def bring_front(hwnd: int):
        if hwnd:
            u32.ShowWindow(hwnd, 9)
            u32.SetForegroundWindow(hwnd)

    u32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u32.MonitorFromPoint.restype = wintypes.HMONITOR
    u32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]

    def place_top_center(hwnd: int, w: int, h: int) -> bool:
        """Tamanho e posicao numa chamada so, no topo e no centro do monitor principal (pixels reais, com a escala
        do Windows). Mover e redimensionar separado fazia o entalhe ir escorregando para o lado a cada abre/fecha."""
        if not hwnd:
            return False
        try:
            scale = u32.GetDpiForWindow(hwnd) / 96 or 1
        except (AttributeError, OSError):
            scale = 1
        mi = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if not u32.GetMonitorInfoW(u32.MonitorFromPoint(wintypes.POINT(0, 0), 1), ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        pw, ph = round(w * scale), round(h * scale)
        x = m.left + (m.right - m.left - pw) // 2
        return bool(u32.SetWindowPos(hwnd, None, x, m.top, pw, ph, 0x0004 | 0x0010))   # NOZORDER | NOACTIVATE

    def focus_elsewhere() -> bool:
        """O foco foi para outro programa? (janelas deste processo, como o seletor de arquivos, nao contam)"""
        h = u32.GetForegroundWindow()
        if not h:
            return False
        pid = wintypes.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
        return pid.value != os.getpid()
else:
    import shutil
    import subprocess

    def covered(own_title: str) -> bool:
        """Linux com X11 (xprop instalado). No Wayland o sistema nao conta: o entalhe fica sempre visivel."""
        if not shutil.which("xprop") or not os.getenv("DISPLAY"):
            return False
        try:
            out = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=1).stdout
            wid = out.strip().split()[-1]
            if wid in ("0x0", "0"):
                return False
            st = subprocess.run(["xprop", "-id", wid, "_NET_WM_STATE", "WM_NAME"], capture_output=True, text=True, timeout=1).stdout
            if own_title in st:
                return False
            return "_NET_WM_STATE_FULLSCREEN" in st or ("MAXIMIZED_VERT" in st and "MAXIMIZED_HORZ" in st)
        except (OSError, subprocess.SubprocessError, IndexError):
            return False

    def focus_elsewhere() -> bool:
        if not shutil.which("xprop") or not os.getenv("DISPLAY"):
            return False                     # sem como saber: a pagina recolhe pelo proprio evento de foco
        try:
            wid = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=1).stdout.split()[-1]
            pid = subprocess.run(["xprop", "-id", wid, "_NET_WM_PID"], capture_output=True, text=True, timeout=1).stdout.split()[-1]
            return wid not in ("0x0", "0") and pid.isdigit() and int(pid) != os.getpid()
        except (OSError, subprocess.SubprocessError, IndexError):
            return False

    def find_hwnd(title: str) -> int:
        return 0

    def style_window(hwnd: int, taskbar: bool):
        pass                                 # no Linux o Qt cuida (o entalhe e uma janela "ferramenta" comum)

    def bring_front(hwnd: int):
        pass

    def place_top_center(hwnd: int, w: int, h: int) -> bool:
        return False                         # no Linux o pywebview (Qt) posiciona


class App:
    """Ponte com a pagina (window.pywebview.api.*) e controle das janelas."""

    def __init__(self):
        conf = load_conf()
        self._mode = conf.get("mode", "janela")
        self._on_top = bool(conf.get("on_top", False))   # entalhe sempre por cima (nao some com programa maximizado)
        self._win = None
        self._hwnd = 0            # janela do entalhe no Windows (achada quando aparece)
        self._expanded = False
        self._hidden = False
        self._pinned = False      # entalhe aberto com clique (fica ate clicar fora); aberto so pelo mouse fecha ao sair
        self._focused = False     # o entalhe aberto ja recebeu o foco (so entao "foco em outro programa" recolhe)
        self._title = "A.U.R.A."

    # ---- chamado pela pagina ----
    def info(self):
        return {"mode": self._mode, "expanded": self._expanded, "on_top": self._on_top, "platform": sys.platform}

    def set_on_top(self, on):
        """Ligado: o entalhe fica sempre visivel por cima de tudo. Desligado: some com programa maximizado/tela cheia."""
        self._on_top = bool(on)
        save_conf(on_top=self._on_top)
        return self.info()

    def set_mode(self, mode):
        if mode not in ("janela", "entalhe") or mode == self._mode:
            return self.info()
        save_conf(mode=mode)
        self._mode = mode
        threading.Thread(target=self._reopen, daemon=True).start()     # recria a janela no outro formato
        return self.info()

    def expand(self):
        if self._mode == "entalhe" and not self._expanded:
            self._expanded = True
            self._place(*PANEL)
        return self.info()

    def pin(self):
        """Clicou dentro do entalhe aberto: ele fica aberto (e recebe o teclado) ate clicar fora."""
        if self._mode == "entalhe" and self._expanded:
            self._pinned = True
        return self.info()

    def collapse(self):
        if self._mode == "entalhe" and self._expanded:
            self._expanded = self._pinned = self._focused = False
            self._place(*PILL)
        return self.info()

    def quit(self):
        threading.Timer(1.5, lambda: [w.destroy() for w in list(webview.windows)]).start()   # deixa a tela final aparecer

    def retry(self):
        if server_up() and self._win:
            self._win.load_url(self._url())

    # ---- janelas ----
    def _url(self):
        return URL + ("/?ui=entalhe" if self._mode == "entalhe" else "/")

    def _screen(self):
        s = webview.screens[0]
        return s.width, s.height

    def _place(self, w, h):
        if self._mode == "entalhe":
            self._hwnd = self._hwnd or find_hwnd(self._title)
            if place_top_center(self._hwnd, w, h):
                return
        sw, _ = self._screen()
        self._win.resize(w, h)
        self._win.move(max(0, (sw - w) // 2), 0)

    def _create(self):
        start = self._url() if server_up() else None
        common = dict(js_api=self, background_color="#050608", text_select=True)
        if self._mode == "entalhe":
            sw, _ = self._screen()
            self._expanded = False
            self._hwnd = 0
            self._win = webview.create_window(self._title, start, html=None if start else LOADING, frameless=True,
                                             on_top=True, resizable=False, easy_drag=False, min_size=(120, 30),
                                             width=PILL[0], height=PILL[1], x=(sw - PILL[0]) // 2, y=0, **common)
            prev = u32.GetForegroundWindow() if WIN else None

            def shown():
                self._hwnd = find_hwnd(self._title)
                self._place(*PILL)           # o tamanho inicial de janela sem moldura sai torto no Windows
                style_window(self._hwnd, taskbar=False)
                if prev:
                    u32.SetForegroundWindow(prev)    # aparecer nao rouba o foco de quem voce estava usando
            self._win.events.shown += shown
        else:
            sw, sh = self._screen()
            w, h = min(WINDOW[0], sw - 60), min(WINDOW[1], sh - 90)       # cabe em tela pequena / com zoom
            self._win = webview.create_window(self._title, start, html=None if start else LOADING,
                                             width=w, height=h, x=(sw - w) // 2, y=max(0, (sh - h) // 2 - 20),
                                             min_size=(400, 560), **common)
            self._win.events.shown += lambda: style_window(find_hwnd(self._title), taskbar=True)
        return self._win

    def _reopen(self):
        old = self._win
        self._create()
        if old:
            old.destroy()

    def _serve(self, lock: socket.socket):
        """Outra instancia pediu para aparecer."""
        while True:
            conn, _ = lock.accept()
            with conn:
                if conn.recv(16) != b"show" or not self._win:
                    continue
            w = self._win
            if self._hidden:
                w.show(); self._hidden = False
            if self._mode == "entalhe":
                w.evaluate_js("notchExpand(true)")
            else:
                w.restore(); w.show()
            bring_front(find_hwnd(self._title))

    def _watch(self):
        """Entalhe recolhido: some com programa maximizado/tela cheia e volta quando ele sai."""
        away = 0
        while True:
            time.sleep(0.5)
            w = self._win
            if w and self._mode == "entalhe" and self._expanded and self._pinned:
                # aberto com clique e o foco foi para outro programa: recolhe (como clicar fora).
                # So depois de ele ter tido o foco: o clique que abre pode demorar um instante para ativar a janela.
                elsewhere = focus_elsewhere()
                if not elsewhere:
                    self._focused = True
                away = away + 1 if elsewhere and self._focused else 0
                if away >= 2:
                    away = 0
                    w.evaluate_js("notchCollapse()")
            if not w or self._mode != "entalhe" or self._expanded:
                if self._hidden and w:
                    w.show(); self._hidden = False
                continue
            hide = not self._on_top and covered(self._title)
            if hide != self._hidden:
                (w.hide if hide else w.show)()
                self._hidden = hide


def main():
    lock = single_instance()
    if not lock:
        return                                   # ja esta aberta
    app = App()
    if "--fundo" in sys.argv and app._mode == "janela":
        return                                   # inicio automatico no modo janela: nao abre nada sozinho
    allow_microphone()
    app._create()
    threading.Thread(target=app._watch, daemon=True).start()
    threading.Thread(target=app._serve, args=(lock,), daemon=True).start()
    storage = CONF_DIR / "webview"
    webview.start(private_mode=False, storage_path=str(storage), gui=None if WIN else "qt")


if __name__ == "__main__":
    main()
