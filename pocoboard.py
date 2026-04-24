"""POCOBoard — Windows streamer sidekick (control + big-screen display).

Inspired by M5Tab-Poco.  Two windows, multi-screen aware:

  * Control window — fixed size, sits on the operator's monitor.
  * Display window — opens on a different monitor, fullscreen-capable.

Multiple browsers on the LAN can connect to the embedded HTTP server to
trigger BOMB/CHEER/HEARTS/STARS/SNOW effects, send scrolling text, or
speak through the host's speakers via TALK.

Run:    python pocoboard.py [--config config.ini]
"""
from __future__ import annotations
import argparse
import os
import signal
import socket
import sys

from PySide6.QtCore    import Qt, QTimer
from PySide6.QtGui     import QFont, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from config         import Config
from audio          import AudioEngine
from media_queue    import MediaQueue
from web_server     import WebBridge, run_in_thread
from control_window import ControlWindow
from display_window import DisplayWindow


def _pick_display_screen(cfg_screen: int, control_screen: int, n_screens: int) -> int:
    """cfg_screen >=0 wins; cfg_screen == -1 means "the other screen"."""
    if cfg_screen >= 0:
        return min(cfg_screen, n_screens - 1)
    if n_screens >= 2:
        return 1 if control_screen == 0 else 0
    return 0


def _pick_control_screen(cfg_screen: int, n_screens: int) -> int:
    if cfg_screen >= 0:
        return min(cfg_screen, n_screens - 1)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="pocoboard")
    ap.add_argument("--config", default=None,
                    help="Path to config.ini (default: ./config.ini, then ./config.example.ini)")
    ap.add_argument("--port", type=int, default=None, help="Override http_port")
    ap.add_argument("--display-screen", type=int, default=None,
                    help="Override display_screen (0-based, -1 = other screen)")
    ap.add_argument("--no-fullscreen", action="store_true",
                    help="Start with the display window windowed")
    args = ap.parse_args()

    # When running as a PyInstaller-built exe, sys.frozen is set and
    # config.ini lives next to POCOBoard.exe (NOT inside the temp unpack
    # directory that __file__ points to in onefile mode).
    if getattr(sys, "frozen", False):
        here = os.path.dirname(os.path.abspath(sys.executable))
    else:
        here = os.path.dirname(os.path.abspath(__file__))
    cfg_path = args.config or (
        os.path.join(here, "config.ini") if os.path.isfile(os.path.join(here, "config.ini"))
        else os.path.join(here, "config.example.ini")
    )
    cfg = Config()
    cfg.load(cfg_path)

    host = cfg.get_str("http_host", "0.0.0.0")
    port = args.port if args.port is not None else cfg.get_int("http_port", 8080)
    startup_volume = cfg.get_int("startup_volume", 80)
    accept_on_boot = cfg.get_bool("accept_on_boot", True)
    debounce_ms    = cfg.get_int("debounce_ms", 300)

    fs_default = (cfg.get_bool("display_fullscreen_on_boot", True)
                  and not args.no_fullscreen)
    disp_w = cfg.get_int("display_width", 1600)
    disp_h = cfg.get_int("display_height", 900)
    marquee_size = cfg.get_int("marquee_size", 64)
    # image_display_sec: image background auto-clears after N seconds (0 = never).
    # media_min_play_sec: videos and uploaded audio loop until at least N seconds
    #                     have played, then stop at the next natural end (0 = play once).
    image_sec    = cfg.get_int("image_display_sec", 180)
    min_play_sec = cfg.get_int("media_min_play_sec", 60)

    disp_screen_cfg = (args.display_screen
                       if args.display_screen is not None
                       else cfg.get_int("display_screen", -1))
    ctrl_screen_cfg = cfg.get_int("control_screen", -1)

    # ----- Qt app -----
    # Tell Qt we want HiDPI + smooth scaling (Windows 11 mixed-DPI rigs).
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
    app = QApplication(sys.argv)
    app.setApplicationName("POCOBoard")
    # Window / taskbar icon. When frozen, PyInstaller places data files
    # (including icon.ico) under sys._MEIPASS (= _internal/ in onedir mode);
    # when running from source, the file sits next to pocoboard.py.
    bundle_dir = getattr(sys, "_MEIPASS", here)
    for cand in (os.path.join(bundle_dir, "icon.ico"),
                 os.path.join(here, "icon.ico")):
        if os.path.isfile(cand):
            app.setWindowIcon(QIcon(cand))
            break
    # Allow clean Ctrl+C in the console.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    # Give Python signals a chance to be delivered.
    sig_timer = QTimer()
    sig_timer.start(200)
    sig_timer.timeout.connect(lambda: None)

    # ----- bridge + audio -----
    bridge = WebBridge()
    bridge.set_debounce_ms(debounce_ms)
    bridge.set_volume(startup_volume)
    bridge.set_accept(accept_on_boot)

    audio = AudioEngine()
    audio.set_volume(startup_volume)
    audio.preload()

    # Media queue — uploads land here and wait for the operator to press
    # 再生 on each item. Persisting files live under cache/uploads/.
    media_queue = MediaQueue()

    # ----- display window -----
    marquee_font = QFont("Segoe UI Variable Display", 1)
    marquee_font.setPixelSize(marquee_size)
    marquee_font.setBold(True)

    display = DisplayWindow(
        marquee_font=marquee_font,
        status_text_cb=lambda: _ready_footer(host, port, bridge),
    )
    display.set_image_display_sec(image_sec)
    display.set_media_min_play_sec(min_play_sec)
    audio.set_media_min_play_sec(min_play_sec)

    screens = QGuiApplication.screens()
    n = max(1, len(screens))
    ctrl_screen = _pick_control_screen(ctrl_screen_cfg, n)
    disp_screen = _pick_display_screen(disp_screen_cfg, ctrl_screen, n)

    # Place display first, then control, so control can reflect the actual target.
    display.place_on_screen(disp_screen, fullscreen=fs_default,
                            fallback_size=(disp_w, disp_h))

    # ----- control window -----
    ctrl = ControlWindow(bridge, audio, display, media_queue)
    ctrl.set_http_address(host, port)
    ctrl.set_initial_volume(startup_volume)
    ctrl.set_initial_accept(accept_on_boot)
    ctrl.set_selected_screen(disp_screen)
    if fs_default:
        ctrl.btnFullscreen.setChecked(True)
        ctrl.btnFullscreen.setText("全画面解除 (F11)")

    # Anchor control window on the chosen control screen, centered.
    if screens:
        cg = screens[ctrl_screen].availableGeometry()
        ctrl.move(cg.x() + (cg.width() - ctrl.width()) // 2,
                  cg.y() + max(40, (cg.height() - ctrl.height()) // 2))
    ctrl.show()

    # ----- signal wiring (bridge → display / audio / log) -----
    # Qt automatically uses queued connections because bridge lives in the
    # main thread and signals are emitted from HTTP worker threads.
    # Signals carry (client_id, label, ip, ...) now — adapt before delivery.
    bridge.fxRequested.connect(lambda cid, label, ip, kind:
                               display.trigger_fx(kind))
    bridge.fxRequested.connect(lambda cid, label, ip, kind:
                               audio.play_fx(kind))
    bridge.talkChunk.connect(lambda cid, label, ip, data, sr:
                             audio.play_talk_chunk(cid, label, ip, data, sr))
    bridge.talkChunk.connect(lambda *_args: display.mark_talk_activity())
    bridge.marqueeRequested.connect(lambda cid, label, ip, text, speed:
                                    display.add_marquee(text, speed))
    bridge.marqueeStop.connect(lambda cid, label, ip: display.stop_marquee())
    display.marqueeStatusChanged.connect(ctrl.on_marquee_changed)
    bridge.requestLogged.connect(ctrl.on_request_logged)
    bridge.clientsChanged.connect(ctrl.refresh_users)
    # Uploaded media flows through the control window: it enqueues, and
    # (if auto-play is ON, which is the default) also triggers immediate
    # display.  Push-play mode keeps items waiting for the ▶ button.
    bridge.mediaUploaded.connect(ctrl.on_media_uploaded)
    # Per-user 取消 (browser-side) — the handler stops only items owned
    # by the requesting client.
    bridge.myStopRequested.connect(ctrl.on_my_stop)
    # Display / audio report ownership changes so the bridge (and therefore
    # /my/status) stays in sync with what's actually on screen or playing.
    display.ownershipChanged.connect(bridge.set_owner)
    audio.ownershipChanged.connect(bridge.set_owner)

    # ----- HTTP server -----
    upload_dir = os.path.join(here, "cache", "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    try:
        srv, srv_thread = run_in_thread(host, port, bridge, upload_dir)
    except OSError as exc:
        QMessageBox.critical(
            None, "POCOBoard — HTTP server failed",
            f"ポート {port} をバインドできませんでした:\n{exc}\n\n"
            "config.ini の http_port を変更してください。")
        return 2

    print(f"[pocoboard] HTTP server listening on {host}:{port}")
    print(f"[pocoboard] LAN URL: http://{_lan_ip()}:{port}/")
    print(f"[pocoboard] upload cache: {upload_dir}")
    print(f"[pocoboard] screens: {[s.name() for s in screens]}")
    print(f"[pocoboard] control screen={ctrl_screen}, display screen={disp_screen}, "
          f"fullscreen={fs_default}")
    # Initial user-list render (usually empty at this point).
    ctrl.refresh_users()

    rc = app.exec()
    try:
        srv.shutdown()
    except Exception:
        pass
    return rc


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def _ready_footer(host: str, port: int, bridge: WebBridge) -> str:
    snap = bridge.snapshot()
    ip = _lan_ip() if host in ("0.0.0.0", "") else host
    return f"  POCOBoard  |  http://{ip}:{port}/  |  vol {snap['volume']}  |  {'ACCEPT' if snap['accept'] else 'REJECT'}  "


if __name__ == "__main__":
    sys.exit(main())
