"""POCOBoard — Windows streamer sidekick (control + big-screen display).

Inspired by M5Tab-Poco.  Two windows, multi-screen aware:

  * Control window — fixed size, sits on the operator's monitor.
  * Display window — opens on a different monitor, fullscreen-capable.

Multiple browsers on the LAN can connect to the embedded HTTP server to
trigger BOMB/CHEER/HEARTS/STARS/SNOW/.../NOTES effects, send scrolling text, or
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
from midi_engine    import MidiEngine
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
    # Per-group volumes: FX one-shots vs external audio (TALK / uploaded
    # audio / video sound).  FX defaults to 30 (the synthesized one-shots
    # are loud); external audio falls back to startup_volume.
    startup_fx_volume  = cfg.get_int("startup_fx_volume", 30)
    startup_ext_volume = cfg.get_int("startup_ext_volume", startup_volume)
    accept_on_boot = cfg.get_bool("accept_on_boot", True)
    debounce_ms    = cfg.get_int("debounce_ms", 300)
    # Per-effect gain on top of the 効果音 slider (percent, 100 = as-is).
    # BOMB ships at 50 — it is synthesized far hotter than the others.
    fx_kind_gain_pct = {
        kind: cfg.get_int(f"fx_volume_{kind}_pct", 50 if kind == "bomb" else 100)
        for kind in ("bomb", "cheer", "hearts", "stars", "snow", "petals",
                     "aurora", "laser", "sunset", "leaves", "notes", "rainbow")
    }
    # Upload size caps (MB).  0 / absent = built-in default.
    upload_image_mb = cfg.get_int("upload_limit_image_mb", 0)
    upload_video_mb = cfg.get_int("upload_limit_video_mb", 0)
    upload_audio_mb = cfg.get_int("upload_limit_audio_mb", 0)

    fs_default = (cfg.get_bool("display_fullscreen_on_boot", True)
                  and not args.no_fullscreen)
    disp_w = cfg.get_int("display_width", 1600)
    disp_h = cfg.get_int("display_height", 900)
    marquee_size = cfg.get_int("marquee_size", 64)
    # Global size multiplier (percent).  150 = 1.5x baseline so on-screen
    # text is comfortably readable for the audience.  Operators can
    # retune live from the 横スクロール tab (50–500%).
    marquee_size_pct = cfg.get_int("marquee_size_pct", 150)
    # Scroll speed at speed-stop 1 (px/s) and pinned-message lifetime (s).
    marquee_scroll_pps = cfg.get_int("marquee_scroll_pps", 320)
    marquee_pin_sec    = cfg.get_float("marquee_pin_sec", 3.0)
    # COMMENT mode (おわくさ AI feed, comment_feed.py).  text_mode picks
    # where generic text lands at boot: 'marquee' (legacy Niconico lanes)
    # or 'comment' (upward feed).  comment_size_pct follows the marquee
    # size convention (100 = marquee_size); falls back to marquee_size_pct.
    text_mode          = cfg.get_str("text_mode", "marquee").strip().lower()
    comment_size_pct   = cfg.get_int("comment_size_pct", marquee_size_pct)
    comment_max_lines  = cfg.get_int("comment_max_lines", 12)
    comment_ttl_sec    = cfg.get_float("comment_ttl_sec", 0.0)
    comment_width_pct  = cfg.get_int("comment_width_pct", 92)
    comment_bottom_pct = cfg.get_int("comment_bottom_pct", 4)
    comment_height_pct = cfg.get_int("comment_height_pct", 90)
    comment_bg_pct     = cfg.get_int("comment_bg_pct", 45)
    comment_scroll_ms  = cfg.get_int("comment_scroll_ms", 350)
    comment_show_time  = cfg.get_bool("comment_show_time", False)
    # Shared secret for POST /ai (empty = any LAN client may drive the AI
    # screen buffer).  The おわくさ script sends it as X-Poco-AI-Token.
    ai_token           = cfg.get_str("ai_token", "")
    # Idle title: quiet seconds before it fades back in (0 = never) and
    # the fade-in duration.
    idle_return_sec    = cfg.get_int("idle_return_sec", 300)
    idle_title_fade_ms = cfg.get_int("idle_title_fade_ms", 1200)
    # FX opacity over an uploaded video background.
    video_fx_op        = cfg.get_int("video_fx_opacity_pct", 75)
    # image_display_sec: image background auto-clears after N seconds (0 = never).
    # media_min_play_sec: videos and uploaded audio loop until at least N seconds
    #                     have played, then stop at the next natural end (0 = play once).
    image_sec    = cfg.get_int("image_display_sec", 180)
    min_play_sec = cfg.get_int("media_min_play_sec", 60)
    # Live camera (USB / virtual camera) — ON by default: the camera feed
    # is the standard idle background, with FX / marquee overlaid
    # semi-transparently while it is visible.
    camera_on_boot = cfg.get_bool("camera_on_boot", False)
    camera_device  = cfg.get_str("camera_device", "")
    camera_fx_op   = cfg.get_int("camera_fx_opacity_pct", 55)
    camera_mq_op   = cfg.get_int("camera_marquee_opacity_pct", 75)
    camera_poll_fps = cfg.get_int("camera_dshow_poll_fps", 30)
    # Horizontal correction comes in two switchable presets (モード 1 /
    # モード 2), each holding a camera stretch (camera_hstretch_pctN,
    # vertical untouched, centred on the middle axis) and an output
    # stretch for the layers POCOBoard draws itself
    # (output_hstretch_pctN: FX / marquee / piano roll / photos /
    # videos).  Preset 1 = 100 % (no correction), preset 2 = 297 % (the
    # deploy rig's calibration, 2026-08-06).  hstretch_mode picks which
    # preset is active at boot (default 1 = no correction; the deploy
    # rig sets hstretch_mode=2 in config.ini); the operator flips them
    # with the 横補正モード buttons on the 表示 tab.  The legacy single-value keys
    # (camera_hstretch_pct / output_hstretch_pct) still seed preset 2.
    camera_hstretch1 = cfg.get_int("camera_hstretch_pct1", 100)
    output_hstretch1 = cfg.get_int("output_hstretch_pct1", 100)
    camera_hstretch2 = cfg.get_int("camera_hstretch_pct2",
                                   cfg.get_int("camera_hstretch_pct", 297))
    output_hstretch2 = cfg.get_int("output_hstretch_pct2",
                                   cfg.get_int("output_hstretch_pct", 297))
    hstretch_mode    = cfg.get_int("hstretch_mode", 1)
    piano_pps     = cfg.get_int("piano_scroll_pps", 110)
    piano_fx_op   = cfg.get_int("piano_fx_opacity_pct", 55)
    piano_roll_op = cfg.get_int("piano_roll_opacity_pct", 65)
    piano_img_op  = cfg.get_int("piano_image_opacity_pct", 35)
    piano_vid_op  = cfg.get_int("piano_video_opacity_pct", 35)
    # Piano-roll layout: full (roll covers the screen, photos / videos /
    # FX overlay translucently) or compact (roll confined to a strip at
    # the bottom — piano_compact_height_pct of the screen — while photos
    # / videos / FX show at full brightness above it).
    piano_compact     = cfg.get_bool("piano_compact", False)
    piano_compact_pct = cfg.get_int("piano_compact_height_pct", 25)
    piano_compact_op  = cfg.get_int("piano_compact_opacity_pct", 65)
    piano_compact_pos = cfg.get_str("piano_compact_position", "bottom")
    # Keyboard height (% of screen, before the output correction divides
    # it) and the key range drawn (MIDI note numbers, 21..108 = 88 keys).
    piano_kb_pct   = cfg.get_int("piano_keyboard_height_pct", 18)
    piano_note_min = cfg.get_int("piano_note_min", 21)
    piano_note_max = cfg.get_int("piano_note_max", 108)

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
    bridge.set_volume(startup_ext_volume)
    bridge.set_accept(accept_on_boot)
    bridge.set_upload_limits(upload_image_mb, upload_video_mb, upload_audio_mb)
    bridge.set_ai_token(ai_token)

    audio = AudioEngine()
    audio.set_fx_volume(startup_fx_volume)
    audio.set_ext_volume(startup_ext_volume)
    for kind, pct in fx_kind_gain_pct.items():
        audio.set_fx_kind_gain(kind, max(0, min(400, pct)) / 100.0)
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
    display.set_marquee_scale(max(50, min(500, marquee_size_pct)) / 100.0)
    display.set_piano_scroll_pps(float(piano_pps))
    display.set_piano_fx_opacity(max(0, min(100, piano_fx_op)) / 100.0)
    display.set_piano_roll_opacity(max(0, min(100, piano_roll_op)) / 100.0)
    display.set_piano_image_opacity(max(0, min(100, piano_img_op)) / 100.0)
    display.set_piano_video_opacity(max(0, min(100, piano_vid_op)) / 100.0)
    audio.set_media_min_play_sec(min_play_sec)
    display.set_video_volume(max(0, min(100, startup_ext_volume)) / 100.0)
    display.set_camera_fx_opacity(max(0, min(100, camera_fx_op)) / 100.0)
    display.set_camera_marquee_opacity(max(0, min(100, camera_mq_op)) / 100.0)
    display.set_piano_compact_frac(max(10, min(50, piano_compact_pct)) / 100.0)
    display.set_piano_compact_opacity(max(0, min(100, piano_compact_op)) / 100.0)
    display.set_piano_compact_position(piano_compact_pos)
    display.set_piano_keyboard_height(max(2, min(60, piano_kb_pct)) / 100.0)
    display.set_piano_note_range(piano_note_min, piano_note_max)
    display.set_piano_compact(piano_compact)
    display.set_idle_return_sec(idle_return_sec)
    display.set_idle_title_fade_ms(idle_title_fade_ms)
    display.set_video_fx_opacity(max(0, min(100, video_fx_op)) / 100.0)
    display.set_camera_poll_fps(float(camera_poll_fps))
    display.set_marquee_scroll_pps(float(marquee_scroll_pps))
    display.set_marquee_pin_sec(marquee_pin_sec)
    display.set_comment_scale(max(50, min(500, comment_size_pct)) / 100.0)
    display.set_comment_max_entries(max(1, min(60, comment_max_lines)))
    display.set_comment_ttl_sec(max(0.0, comment_ttl_sec))
    display.set_comment_layout(max(20, min(100, comment_width_pct)) / 100.0,
                               max(0, min(50, comment_bottom_pct)) / 100.0,
                               max(10, min(100, comment_height_pct)) / 100.0)
    display.set_comment_bg_opacity(max(0, min(100, comment_bg_pct)) / 100.0)
    display.set_comment_scroll_ms(float(comment_scroll_ms))
    display.set_comment_show_time(comment_show_time)
    display.set_text_mode("comment" if text_mode.startswith("c") else "marquee")
    bridge.set_text_mode(display.text_mode())
    display.set_hstretch_preset(
        1, max(50, min(400, camera_hstretch1)) / 100.0,
        max(100, min(400, output_hstretch1)) / 100.0)
    display.set_hstretch_preset(
        2, max(50, min(400, camera_hstretch2)) / 100.0,
        max(100, min(400, output_hstretch2)) / 100.0)
    display.set_hstretch_mode(2 if hstretch_mode == 2 else 1)
    if camera_device:
        display.set_camera_device(camera_device)
    display.set_camera_mode(camera_on_boot)

    # USB MIDI input (optional — degrades gracefully when mido is missing).
    midi = MidiEngine()
    if not MidiEngine.is_available():
        print(f"[pocoboard] MIDI: unavailable ({MidiEngine.import_error()})")
    else:
        ports = midi.list_ports()
        print(f"[pocoboard] MIDI ports: {ports if ports else '(none)'}")
    # IMPORTANT: force QueuedConnection.  These signals are emitted from
    # the winmm worker thread (callback registered via midiInOpen with
    # CALLBACK_FUNCTION).  Qt::AutoConnection should detect the cross-
    # thread emit and queue automatically, but if that detection ever
    # mis-fires the slot would run on the worker thread and modify
    # PianoRollScene._active concurrently with paintEvent's iteration —
    # producing a "dictionary changed size during iteration" crash that
    # silently freezes new note rendering until the app restarts.
    # Pinning the connection type removes any chance of that happening.
    midi.noteOn.connect(display.piano_note_on,  Qt.ConnectionType.QueuedConnection)
    midi.noteOff.connect(display.piano_note_off, Qt.ConnectionType.QueuedConnection)

    screens = QGuiApplication.screens()
    n = max(1, len(screens))
    ctrl_screen = _pick_control_screen(ctrl_screen_cfg, n)
    disp_screen = _pick_display_screen(disp_screen_cfg, ctrl_screen, n)

    # Place display first, then control, so control can reflect the actual target.
    display.place_on_screen(disp_screen, fullscreen=fs_default,
                            fallback_size=(disp_w, disp_h))

    # ----- control window -----
    ctrl = ControlWindow(bridge, audio, display, media_queue, midi=midi)
    ctrl.set_http_address(host, port)
    ctrl.set_initial_volumes(startup_fx_volume, startup_ext_volume)
    ctrl.set_initial_accept(accept_on_boot)
    ctrl.set_selected_screen(disp_screen)
    if fs_default:
        ctrl.set_fullscreen_ui(True)

    # Anchor control window on the chosen control screen, centered.
    # If the window is taller than the available area (small monitor +
    # piano-roll panel makes the panel ~1080 px tall), shrink it first
    # to fit so we never push the title bar above the screen edge.
    if screens:
        cg = screens[ctrl_screen].availableGeometry()
        cw = min(ctrl.width(),  cg.width())
        ch = min(ctrl.height(), cg.height())
        if cw != ctrl.width() or ch != ctrl.height():
            ctrl.resize(cw, ch)
        ctrl.move(cg.x() + max(0, (cg.width()  - cw) // 2),
                  cg.y() + max(0, (cg.height() - ch) // 2))
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
    # おわくさ AI (POST /ai) — executed on the Qt thread by the control
    # window, which also routes 'say' to the active MARQUEE / COMMENT mode.
    bridge.aiRequested.connect(ctrl.on_ai_command)
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
        srv, srv_thread = run_in_thread(
            host, port, bridge, upload_dir, active_paths_cb=media_queue.protected_paths)
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
    print(f"[pocoboard] text mode={display.text_mode()}  "
          f"(POST /ai {'token required' if ai_token else 'open on LAN'})")
    # Initial user-list render (usually empty at this point).
    ctrl.refresh_users()

    rc = app.exec()
    try:
        display.set_camera_mode(False)
    except Exception:
        pass
    try:
        midi.close_port()
    except Exception:
        pass
    try:
        srv.shutdown()
    except Exception:
        pass
    try:
        srv.server_close()
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
