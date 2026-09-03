"""Display window — fullscreen FX + marquee canvas for the "big screen".

Rendered via QPainter.  On Windows with Qt 6 the painter routes through
the RHI (D3D11 by default), so particle effects stay smooth on a 4K
monitor.  The window has no widgets — it's one giant paint surface.

paintEvent draws, in order:
  1. Scene background (or black idle backdrop with branding)
  2. Marquee tracks (when no scene is active — scenes blank the frame)
  3. Optional status pill (bottom-right, tiny text with server URL)

All state-change entry points are Qt slots, so they can be called from
signals fired on any thread.
"""
from __future__ import annotations
import os
import time
from typing import Optional

from PySide6.QtCore       import QRectF, QPointF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui        import QColor, QFont, QFontMetricsF, QImage, QImageReader, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import (
    QAudioOutput, QCamera, QCameraDevice, QMediaCaptureSession, QMediaDevices,
    QMediaPlayer, QVideoSink,
)
from PySide6.QtWidgets    import QWidget

from animations import ImageScene, PianoRollScene, Scene, make_scene
from marquee    import MarqueeEngine

# DirectShow fallback for cameras invisible to Qt/Media Foundation
# (ManyCam Virtual Webcam, OBS Virtual Camera, ...).  Pure ctypes COM —
# guarded import so an unexpected platform issue degrades to Qt-only.
try:
    from dshow_camera import DShowCamera, list_dshow_cameras
    _DSHOW_AVAILABLE = True
except Exception as _dshow_exc:   # pragma: no cover
    print(f"[dshow] unavailable: {_dshow_exc!r}")
    _DSHOW_AVAILABLE = False


class DisplayWindow(QWidget):
    """Full-area canvas. Fullscreen-capable; no decorations when fullscreen."""

    marqueeStatusChanged = Signal(int, int)   # (used, max)
    # Emitted whenever the "owner" (uploader client_id) of a currently
    # visible media slot changes.  args = (kind, owner_cid_or_empty)
    # kind ∈ {'image', 'video'}.  Lets WebBridge know who is allowed to
    # stop the current background from the browser-side "自分のを取消" button.
    ownershipChanged = Signal(str, str)
    visualPlaybackStopped = Signal()
    # Emitted whenever piano-roll mode toggles. `bool` = active.
    pianoModeChanged = Signal(bool)
    # (compact) — emitted whenever the piano-roll layout flips between
    # full-screen and the compact bottom strip.
    pianoCompactChanged = Signal(bool)
    # Emitted with the newly active horizontal-correction preset (1 / 2)
    # so the control window can mirror the button state + spinboxes.
    hstretchModeChanged = Signal(int)

    def __init__(self, marquee_font: QFont, status_text_cb=None) -> None:
        super().__init__()
        self.setWindowTitle("POCOBoard — Display")
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self.setMouseTracking(False)
        # A dark background so resize transitions don't flash white.
        self.setStyleSheet("background:#000;")
        self.setMinimumSize(640, 360)

        self._scene: Optional[Scene] = None
        self._marquee = MarqueeEngine(marquee_font)
        self._last_ns = time.perf_counter_ns()
        self._cursor_hidden = False
        self._status_text_cb = status_text_cb    # () -> str|None, for the idle footer

        # Repaint gating — the 16 ms tick only schedules a repaint when
        # something on screen can actually have changed: an animation is
        # running, a new camera/video frame arrived (_frame_dirty), or a
        # state-changing slot requested one (_dirty).  A slow heartbeat
        # repaint (~2 Hz) keeps the tiny status footer fresh and
        # self-heals any missed invalidation.  Idle sessions drop from
        # 60 full-window paints per second to 2.
        self._dirty: bool = True
        self._frame_dirty: bool = False
        self._heartbeat_ms: float = 0.0
        self._last_mq_status: Optional[tuple[int, int]] = None
        # Single-slot cache of the letterboxed/cropped frame scaled to its
        # on-screen size — (key, QPixmap).  Frames arrive at camera/video
        # rate (~30 fps) while paints can run at 60 fps (marquee over
        # video etc.); caching halves the scaling work and skips the
        # QImage→backing-store conversion on repeat paints.
        self._frame_cache_key: Optional[tuple] = None
        self._frame_cache_pm: Optional[QPixmap] = None
        # Same idea for the static photo background (scaled smoothly once
        # per size instead of fast-scaled on every paint).
        self._bg_cache_key: Optional[tuple] = None
        self._bg_cache_pm: Optional[QPixmap] = None

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # branding font (scales with window)
        self._title_font = QFont("Segoe UI Variable Display", 72)
        self._title_font.setBold(True)
        self._sub_font   = QFont("Segoe UI Variable Text", 24)
        self._footer_font = QFont("Consolas", 13)

        # --- idle / title state machine ---
        # Show POCOBOARD title at boot; any activity (FX / marquee / TALK /
        # video) switches to "black idle" — the post-effect calm state.
        # After IDLE_RETURN_MS of no activity, fade back into the title.
        self._show_idle_title = True
        self._last_activity_ms: float = 0.0
        self._idle_return_ms  = 5 * 60 * 1000   # 5 minutes (config idle_return_sec)
        # Fade-in of the title when returning from dark — 0..1, updated each tick.
        self._title_fade = 1.0
        self._title_fade_ms: float = 1200.0     # config idle_title_fade_ms
        # FX opacity while an uploaded video is the background (config
        # video_fx_opacity_pct).
        self._video_fx_opacity: float = 0.75
        # DirectShow camera poll interval (config camera_dshow_poll_fps).
        self._dshow_poll_ms: float = 1000.0 / 30.0

        # --- background layer (persistent; cleared only by operator) ---
        # Both image and video are now composited inside paintEvent so
        # that piano-roll mode can draw them as semi-transparent overlays
        # on top of the keyboard scene.  Video frames are sourced from a
        # QVideoSink (no QVideoWidget child anymore — that one drew
        # straight to the GPU and ignored painter opacity).
        self._bg_image: Optional[QPixmap] = None
        self._bg_caption: str = ""
        self._bg_image_owner: str = ""    # uploader client_id

        # --- video overlay (QMediaPlayer + QVideoSink) ---
        # Created lazily the first time a video request arrives.
        self._video_sink:   Optional[QVideoSink]   = None
        self._video_player: Optional[QMediaPlayer] = None
        self._video_audio:  Optional[QAudioOutput] = None
        # Video sound belongs to the "external audio" group (it arrives from
        # uploaders, like TALK / audio files) — the control window pushes the
        # external-volume slider value here.
        self._video_volume: float = 0.8
        self._video_active: bool = False
        self._video_owner:  str  = ""     # uploader client_id
        self._video_url:    Optional[QUrl] = None
        self._video_start_ms: float = 0.0
        # Latest decoded frame from QVideoSink, drawn each paintEvent.
        # Cleared on stop / error so we don't keep a stale poster on
        # screen after playback finishes.
        self._latest_video_image: Optional[QImage] = None
        # Minimum playback duration (seconds).  If the natural clip length is
        # shorter than this, the player restarts from position 0 on each
        # end-of-media until the total elapsed playback meets the minimum.
        # 0 = play once, no looping.
        self._media_min_play_sec: int = 60

        # --- image auto-clear timer ---
        # Images uploaded from remote (or opened locally) stay on screen for
        # this many seconds, then the background is cleared automatically.
        # 0 disables auto-clear (image persists until 停止).
        self._image_display_sec: int = 180
        self._image_timer = QTimer(self)
        self._image_timer.setSingleShot(True)
        self._image_timer.timeout.connect(self._on_image_timeout)

        # --- piano roll (MIDI) mode ---
        # When True, the 88-key keyboard + scrolling note bars cover the
        # full window as the BASE layer.  Image / video / FX may all
        # be live simultaneously and are rendered on top translucently
        # (each with its own configurable opacity) so all four layers
        # stay visible together.
        self._piano_mode: bool = False
        self._piano_scene: Optional[PianoRollScene] = None
        self._piano_scroll_pps: float = 110.0
        self._piano_image_opacity: float = 0.35
        self._piano_video_opacity: float = 0.35
        self._piano_fx_opacity:    float = 0.55
        # Opacity of the piano-roll scene itself when a live camera feed
        # is underneath — the roll must NOT hide the camera (user spec:
        # ピアノロール画面自体が半透明).  1.0 (opaque) when no camera.
        self._piano_roll_opacity:  float = 0.65
        # Layout: False = the roll covers the whole screen and photos /
        # videos / FX overlay it translucently (dimmed by the opacities
        # above).  True = "compact": the roll is confined to a strip at
        # the bottom (_piano_compact_frac of the height) and photos /
        # videos / FX show at full brightness above it, exactly as they
        # do outside piano mode.
        self._piano_compact: bool = False
        self._piano_compact_frac: float = 0.25
        # Opacity of the compact strip when something shows underneath
        # (config piano_compact_opacity_pct) and where it sits
        # ("bottom" / "top", config piano_compact_position).
        self._piano_compact_opacity: float = 0.65
        self._piano_compact_position: str = "bottom"
        # Keyboard height as a fraction of the screen BEFORE the output
        # correction divides it (config piano_keyboard_height_pct).
        self._piano_kb_base_frac: float = PianoRollScene.KEYBOARD_HEIGHT_FRAC
        # Key range (config piano_note_min / piano_note_max).
        self._piano_note_min: int = PianoRollScene.MIN_NOTE
        self._piano_note_max: int = PianoRollScene.MAX_NOTE

        # --- live camera (USB / virtual camera) mode ---
        # When on, the camera feed acts as the idle background: it fills
        # the frame whenever no uploaded image / video is showing and
        # piano mode is off.  FX scenes and the marquee are then drawn
        # semi-transparently on top (each with its own tunable opacity)
        # so the camera picture stays visible through them.
        self._camera_mode: bool = False
        self._camera:         Optional[QCamera] = None
        self._camera_session: Optional[QMediaCaptureSession] = None
        self._camera_sink:    Optional[QVideoSink] = None
        self._camera_device:  Optional[QCameraDevice] = None
        self._latest_camera_image: Optional[QImage] = None
        # DirectShow fallback backend (ManyCam / OBS virtual cams that
        # Media Foundation — and therefore QCamera — cannot see).
        # backend 'qt' uses QCamera+QVideoSink push frames; 'dshow' polls
        # DShowCamera.grab() from _tick at ~30 fps.
        self._camera_backend: str = "qt"
        self._dshow_cam:   Optional["DShowCamera"] = None
        self._dshow_ident: str = ""
        self._dshow_desc:  str = ""
        self._dshow_poll_accum: float = 0.0
        self._camera_fx_opacity:      float = 0.55
        self._camera_marquee_opacity: float = 0.75
        # Horizontal-only stretch of the camera picture.  The operator's
        # capture chain delivers a horizontally squeezed picture; the fix
        # they want is literal: keep the vertical size, stretch the
        # picture horizontally by an adjustable factor about the window's
        # center axis (parts pushed past the edges are simply clipped).
        # 1.0 = no stretch.  Default set from config (camera_hstretch_pct,
        # shipped default 297 % — calibrated on the operator's rig
        # 2026-08-06.  Measurement showed the camera needs the SAME
        # correction as the drawn layers (the chain has one squeeze, at
        # the output; an earlier camera-is-squeezed-twice model predicted
        # camera = drawn^2 and did not survive the rig test).
        self._camera_hstretch: float = 1.0

        # --- output horizontal correction for the DRAWN layers ---
        # The output signal goes through one downstream horizontal
        # squeeze (landscape signal crammed onto the portrait panel), so
        # everything POCOBoard draws itself — FX scenes, marquee text,
        # piano roll, uploaded photos / videos, idle title — must be
        # pre-stretched to look right on the final display.  Rig
        # calibration (2026-08-06) put this at the SAME 297 % as the
        # camera; the two remain independently tunable in case the
        # chain ever changes.
        # Implementation: those layers compose on a NARROWER virtual
        # canvas (round(w / factor), h) and paintEvent stretches the
        # composition horizontally to fill the physical window — nothing
        # is clipped, the vertical size is untouched, and e.g. the piano
        # keyboard lays out all 88 keys across the virtual width so the
        # full keyboard spans the final screen.  1.0 = off.  Config
        # output_hstretch_pct, shipped default 297.
        self._output_hstretch: float = 1.0
        # Two switchable presets of (camera_hstretch, output_hstretch):
        # preset 1 = no correction (100 %), preset 2 = the rig's 297 %.
        # Editing either spinbox on the control window rewrites the
        # ACTIVE preset; the 横補正モード buttons flip between them.
        self._hstretch_presets: dict[int, tuple[float, float]] = {
            1: (1.0, 1.0),
            2: (2.97, 2.97),
        }
        # Boot default = preset 1 (補正なし); config hstretch_mode=2
        # switches the rig back to the calibrated 297 %.
        self._hstretch_mode: int = 1

    # ---------- activity tracking ----------
    def _mark_activity(self) -> None:
        """Called whenever the display receives a visible/audible request.

        Hides the idle title until IDLE_RETURN_MS of silence passes.
        """
        self._last_activity_ms = time.perf_counter_ns() / 1_000_000.0
        self._show_idle_title = False
        self._title_fade = 0.0
        self._dirty = True

    @Slot()
    def mark_talk_activity(self) -> None:
        """Slot for talk chunks — TALK has no visuals but still counts as
        'someone is using this' so the title shouldn't reappear mid-chat."""
        self._mark_activity()

    # ---------- virtual canvas (output-hstretch aware) ----------
    def _virtual_size(self) -> tuple[int, int]:
        """Logical composition size for the layers POCOBoard draws
        itself (FX / marquee / piano / photos / videos / idle title).
        Horizontally shrunk by the output correction factor; paintEvent
        stretches the composition back to the full window width so the
        downstream squeeze restores true proportions.  The camera layer
        does NOT use this — it draws in physical coordinates with its
        own (squared) correction."""
        w = max(1, self.width())
        h = max(1, self.height())
        if self._output_hstretch > 1.001:
            return max(1, int(round(w / self._output_hstretch))), h
        return w, h

    def _piano_scene_size(self) -> tuple[int, int]:
        """Canvas the piano-roll scene composes on: the full virtual
        canvas in the normal layout, or the bottom strip in compact."""
        vw, vh = self._virtual_size()
        if self._piano_compact:
            return vw, max(60, int(round(vh * self._piano_compact_frac)))
        return vw, vh

    def _piano_kb_frac(self) -> float:
        """Keyboard height as a fraction of the piano scene's canvas.

        The output correction narrows key widths on the composition
        canvas, so the height follows the same ratio (÷ factor) to keep
        real piano key proportions on the final screen.  In the compact
        layout the scene canvas is only a strip, so the fraction is
        scaled back up to keep the keyboard the same ABSOLUTE height
        (PianoRollScene clamps it at half the strip)."""
        frac = self._piano_kb_base_frac / self._output_hstretch
        if self._piano_compact:
            frac /= max(0.05, self._piano_compact_frac)
        return frac

    def _relayout_piano_scene(self) -> None:
        if self._piano_scene is None:
            return
        sw, sh = self._piano_scene_size()
        self._piano_scene.resize(sw, sh)
        self._piano_scene.set_kb_frac(self._piano_kb_frac())

    @Slot(float)
    def set_output_hstretch(self, factor: float) -> None:
        """Horizontal pre-stretch for the drawn layers (1.0 = off).
        Also rewrites the output half of the ACTIVE preset."""
        factor = max(1.0, min(4.0, float(factor)))
        cam, _ = self._hstretch_presets[self._hstretch_mode]
        self._hstretch_presets[self._hstretch_mode] = (cam, factor)
        if abs(factor - self._output_hstretch) < 1e-6:
            return
        self._output_hstretch = factor
        # In-flight marquee tracks and a running FX scene were laid out
        # against the old canvas geometry — clear them (same policy as
        # marquee size changes); the piano scene can simply re-layout.
        self._marquee.stop_all()
        self._emit_marquee_status()
        self._scene = None
        self._relayout_piano_scene()
        self._dirty = True

    # ---------- horizontal-correction presets (モード 1 / 2) ----------
    def hstretch_mode(self) -> int:
        return self._hstretch_mode

    def hstretch_preset(self, mode: int) -> tuple[float, float]:
        """(camera_factor, output_factor) stored for preset `mode`."""
        return self._hstretch_presets[1 if mode == 1 else 2]

    def set_hstretch_preset(self, mode: int, camera: float,
                            output: float) -> None:
        """Store a preset without activating it.  If `mode` IS the active
        preset the new values take effect immediately."""
        mode = 1 if mode == 1 else 2
        camera = max(0.5, min(4.0, float(camera)))
        output = max(1.0, min(4.0, float(output)))
        self._hstretch_presets[mode] = (camera, output)
        if mode == self._hstretch_mode:
            self.set_camera_hstretch(camera)
            self.set_output_hstretch(output)

    @Slot(int)
    def set_hstretch_mode(self, mode: int) -> None:
        """Activate preset 1 or 2 (applies both stretches at once)."""
        mode = 1 if mode == 1 else 2
        camera, output = self._hstretch_presets[mode]
        changed = mode != self._hstretch_mode
        self._hstretch_mode = mode
        self.set_camera_hstretch(camera)
        self.set_output_hstretch(output)
        if changed:
            self.hstretchModeChanged.emit(mode)

    # ---------- public slots (called from any thread via QueuedConnection) ----------
    @Slot(str)
    def trigger_fx(self, kind: str) -> None:
        self._marquee.stop_all()
        self._emit_marquee_status()
        vw, vh = self._virtual_size()
        self._scene = make_scene(kind, vw, vh)
        self._mark_activity()

    @Slot(str, int)
    def add_marquee(self, text: str, speed: int) -> str:
        vw, vh = self._virtual_size()
        res = self._marquee.add(text, vw, vh, speed)
        self._emit_marquee_status()
        self._mark_activity()
        return res

    @Slot()
    def stop_marquee(self) -> None:
        self._marquee.stop_all()
        self._emit_marquee_status()
        self._dirty = True

    def _emit_marquee_status(self) -> None:
        # Emit only on change — this used to fire at 60 Hz while any
        # marquee was scrolling, pushing a cross-object signal + a locked
        # bridge update per tick for a value that rarely changes.
        cur = (self._marquee.lanes_in_use(), self._marquee.max_lanes())
        if cur != self._last_mq_status:
            self._last_mq_status = cur
            self.marqueeStatusChanged.emit(*cur)

    # ---------- screen targeting ----------
    def place_on_screen(self, screen_idx: int, fullscreen: bool,
                        fallback_size: tuple[int, int]) -> None:
        from PySide6.QtGui import QGuiApplication
        screens = QGuiApplication.screens()
        if not screens:
            return
        if screen_idx < 0 or screen_idx >= len(screens):
            screen_idx = 0
        target = screens[screen_idx]
        self.setScreen(target)
        geom = target.geometry()
        # Center the window on its target screen at the fallback size before
        # deciding whether to fullscreen — ensures fullscreen picks the right monitor.
        w, h = fallback_size
        self.setGeometry(
            geom.x() + (geom.width()  - w) // 2,
            geom.y() + (geom.height() - h) // 2,
            w, h,
        )
        if fullscreen:
            self.showFullScreen()
        else:
            self.show()

    # ---------- configuration setters ----------
    @Slot(int)
    def set_image_display_sec(self, sec: int) -> None:
        """Set the auto-clear timeout for uploaded images (0 = never)."""
        self._image_display_sec = max(0, int(sec))
        # If an image is currently displayed, re-arm the timer so changes
        # from the control window take effect immediately.
        if self._bg_image is not None:
            self._image_timer.stop()
            if self._image_display_sec > 0:
                self._image_timer.start(self._image_display_sec * 1000)

    @Slot(float)
    def set_marquee_scale(self, scale: float) -> None:
        """Resize the marquee text globally (1.0 = config baseline).

        Range is left to the caller — the control window clamps to
        50%–500% (0.5..5.0).  Currently-scrolling messages are cleared
        as a side effect (see MarqueeEngine.set_scale).
        """
        self._marquee.set_scale(float(scale))
        self._emit_marquee_status()
        self.update()

    @Slot(float)
    def set_piano_scroll_pps(self, pps: float) -> None:
        self._piano_scroll_pps = max(20.0, float(pps))
        if self._piano_scene is not None:
            self._piano_scene.scroll_pps = self._piano_scroll_pps

    @Slot(float)
    def set_piano_fx_opacity(self, opacity: float) -> None:
        self._piano_fx_opacity = max(0.0, min(1.0, float(opacity)))

    @Slot(float)
    def set_piano_roll_opacity(self, opacity: float) -> None:
        """Opacity of the piano-roll scene over a live camera feed."""
        self._piano_roll_opacity = max(0.0, min(1.0, float(opacity)))
        self._dirty = True

    @Slot(float)
    def set_piano_image_opacity(self, opacity: float) -> None:
        self._piano_image_opacity = max(0.0, min(1.0, float(opacity)))

    @Slot(float)
    def set_piano_video_opacity(self, opacity: float) -> None:
        self._piano_video_opacity = max(0.0, min(1.0, float(opacity)))

    # ---------- live camera (USB / virtual camera) mode ----------
    def is_camera_mode(self) -> bool:
        return self._camera_mode

    @staticmethod
    def available_cameras() -> list[tuple[str, str, str]]:
        """Union of every capture device: [(ident, description, backend)].

        Qt/Media-Foundation devices come first (ident = QCameraDevice
        id).  DirectShow-only devices — ManyCam Virtual Webcam, OBS
        Virtual Camera and friends, which MF cannot see — follow with
        their moniker display name as ident.  DShow entries whose name
        matches a Qt device are dropped (same hardware, Qt path wins).
        """
        out: list[tuple[str, str, str]] = []
        qt_names: set[str] = set()
        for dev in QMediaDevices.videoInputs():
            ident = bytes(dev.id()).decode("utf-8", "replace")
            out.append((ident, dev.description(), "qt"))
            qt_names.add(dev.description().strip().lower())
        if _DSHOW_AVAILABLE:
            for ident, name in list_dshow_cameras():
                if name.strip().lower() in qt_names:
                    continue
                out.append((ident, name, "dshow"))
        return out

    def current_camera_id(self) -> str:
        if self._camera_backend == "dshow":
            return self._dshow_ident
        if self._camera_device is None or self._camera_device.isNull():
            return ""
        return bytes(self._camera_device.id()).decode("utf-8", "replace")

    def current_camera_description(self) -> str:
        if self._camera_backend == "dshow":
            return self._dshow_desc
        if self._camera_device is None or self._camera_device.isNull():
            return ""
        return self._camera_device.description()

    @Slot(float)
    def set_camera_fx_opacity(self, opacity: float) -> None:
        self._camera_fx_opacity = max(0.0, min(1.0, float(opacity)))
        self._dirty = True

    @Slot(float)
    def set_camera_marquee_opacity(self, opacity: float) -> None:
        self._camera_marquee_opacity = max(0.0, min(1.0, float(opacity)))
        self._dirty = True

    @Slot(float)
    def set_camera_hstretch(self, factor: float) -> None:
        """Horizontal-only stretch factor for the camera picture.

        1.0 = undistorted letterbox; larger values widen the picture
        about the center axis while the vertical size stays put.
        Overflow past the window edges is clipped.  Also rewrites the
        camera half of the ACTIVE preset."""
        self._camera_hstretch = max(0.5, min(4.0, float(factor)))
        _, out = self._hstretch_presets[self._hstretch_mode]
        self._hstretch_presets[self._hstretch_mode] = (
            self._camera_hstretch, out)
        self._dirty = True

    def _ingest_camera_frame(self, img: QImage) -> None:
        """Common ingest for both camera backends: publish the frame for
        the next paint."""
        self._latest_camera_image = img
        self._frame_dirty = True

    @Slot(bool)
    def set_camera_mode(self, on: bool) -> None:
        on = bool(on)
        if on == self._camera_mode:
            return
        self._camera_mode = on
        if on:
            self._start_camera()
        else:
            self._stop_camera()
        self.update()

    @Slot(str)
    def set_camera_device(self, ident: str) -> bool:
        """Select a capture device by id (exact) or description (substring).

        Empty string picks the system default camera.  Resolution spans
        both backends: Qt/Media-Foundation devices first, then
        DirectShow-only virtual cameras (ManyCam / OBS 等).  Returns
        True when a device was resolved; if camera mode is on the feed
        is restarted on the new device immediately.
        """
        res = self._resolve_camera_any(ident)
        if res is None:
            print(f"[camera] no capture device matches {ident!r}")
            return False
        backend, dev_ident, desc = res
        if backend == self._camera_backend and dev_ident == self.current_camera_id():
            return True
        self._camera_backend = backend
        if backend == "qt":
            self._camera_device = self._qt_device_by_id(dev_ident)
            self._dshow_ident = ""
            self._dshow_desc = ""
        else:
            self._dshow_ident = dev_ident
            self._dshow_desc = desc
            self._camera_device = None
        if self._camera_mode:
            self._start_camera()
        return True

    @staticmethod
    def _qt_device_by_id(ident: str) -> Optional[QCameraDevice]:
        for dev in QMediaDevices.videoInputs():
            if bytes(dev.id()).decode("utf-8", "replace") == ident:
                return dev
        return None

    @classmethod
    def _resolve_camera_any(cls, ident: str) -> Optional[tuple[str, str, str]]:
        """Resolve id-or-name to (backend, ident, description)."""
        devices = cls.available_cameras()
        if not devices:
            return None
        if not ident:
            default = QMediaDevices.defaultVideoInput()
            if default is not None and not default.isNull():
                return ("qt",
                        bytes(default.id()).decode("utf-8", "replace"),
                        default.description())
            d = devices[0]
            return (d[2], d[0], d[1])
        for d_ident, desc, backend in devices:
            if d_ident == ident:
                return (backend, d_ident, desc)
        low = ident.lower()
        for d_ident, desc, backend in devices:
            if low in desc.lower():
                return (backend, d_ident, desc)
        return None

    def _start_camera(self) -> None:
        self._stop_camera()
        if self._camera_backend == "dshow":
            self._start_camera_dshow()
            return
        dev = self._camera_device
        if dev is None or dev.isNull():
            res = self._resolve_camera_any("")
            if res is None:
                print("[camera] no capture devices available")
                return
            backend, dev_ident, desc = res
            if backend == "dshow":
                # No MF-visible camera at all, but a DirectShow one
                # exists (e.g. only ManyCam on this host) — use it.
                self._camera_backend = "dshow"
                self._dshow_ident = dev_ident
                self._dshow_desc = desc
                self._start_camera_dshow()
                return
            dev = self._qt_device_by_id(dev_ident)
            if dev is None:
                print("[camera] no capture devices available")
                return
            self._camera_device = dev
        try:
            self._camera_sink = QVideoSink(self)
            self._camera_sink.videoFrameChanged.connect(self._on_camera_frame)
            self._camera_session = QMediaCaptureSession(self)
            self._camera = QCamera(dev, self)
            self._camera.errorOccurred.connect(self._on_camera_error)
            self._camera_session.setCamera(self._camera)
            self._camera_session.setVideoSink(self._camera_sink)
            self._camera.start()
            print(f"[camera] started: {dev.description()}")
        except Exception as exc:
            print(f"[camera] start failed: {exc!r}")
            self._stop_camera()

    def _start_camera_dshow(self) -> None:
        if not _DSHOW_AVAILABLE:
            print("[camera] DirectShow backend unavailable")
            return
        try:
            cam = DShowCamera()
            if cam.open(self._dshow_ident):
                self._dshow_cam = cam
                self._dshow_poll_accum = 0.0
            else:
                cam.close()
        except Exception as exc:
            print(f"[camera] dshow start failed: {exc!r}")

    def _stop_camera(self) -> None:
        if self._camera is not None:
            try:
                self._camera.stop()
            except Exception:
                pass
            self._camera.deleteLater()
            self._camera = None
        if self._camera_session is not None:
            self._camera_session.deleteLater()
            self._camera_session = None
        if self._camera_sink is not None:
            self._camera_sink.deleteLater()
            self._camera_sink = None
        if self._dshow_cam is not None:
            try:
                self._dshow_cam.close()
            except Exception:
                pass
            self._dshow_cam = None
        self._latest_camera_image = None
        self._frame_cache_key = None
        self._frame_cache_pm = None

    def _on_camera_frame(self, frame) -> None:
        # Same cheap path as the video sink: drop invalid frames so a
        # brief capture hiccup keeps the previous picture instead of
        # black-flashing.  paintEvent picks the image up on the next tick.
        if frame is None or not frame.isValid():
            return
        # While the camera is hidden behind an upload, skip the per-frame
        # QImage conversion entirely — it's pure CPU burn for pixels
        # nobody sees.  The feed stays open, so the next frame after the
        # camera becomes visible again (~1/30 s later) refreshes the
        # picture.  Piano mode does NOT occlude: the roll renders
        # semi-transparently over the camera, so frames keep flowing.
        if self._video_active or self._bg_image is not None:
            return
        img = frame.toImage()
        if img is None or img.isNull():
            return
        self._ingest_camera_frame(img)

    def _on_camera_error(self, err, msg) -> None:
        print(f"[camera] error {err}: {msg}")

    # ---------- piano roll (MIDI) mode ----------
    def is_piano_mode(self) -> bool:
        return self._piano_mode

    @Slot(bool)
    def set_piano_mode(self, on: bool) -> None:
        on = bool(on)
        if on == self._piano_mode:
            return
        self._piano_mode = on
        if on:
            # Image / video do NOT get cleared — they continue playing as
            # semi-transparent overlays on top of the keyboard scene
            # (see paintEvent).  Triggers a repaint so the new base layer
            # appears immediately.
            sw, sh = self._piano_scene_size()
            # Keyboard height shrinks with the output correction — the
            # correction narrows key widths on the composition canvas,
            # so the height follows the same ratio to keep real piano
            # key proportions on the final screen (see _piano_kb_frac).
            self._piano_scene = PianoRollScene(
                sw, sh, scroll_pps=self._piano_scroll_pps,
                kb_frac=self._piano_kb_frac(),
                note_min=self._piano_note_min,
                note_max=self._piano_note_max)
            self._mark_activity()
        else:
            # Release every held note and drop the scene.
            if self._piano_scene is not None:
                self._piano_scene.all_off()
            self._piano_scene = None
        self.pianoModeChanged.emit(on)
        self.update()

    def is_piano_compact(self) -> bool:
        return self._piano_compact

    @Slot(bool)
    def set_piano_compact(self, on: bool) -> None:
        """Switch the piano-roll layout.

        False (normal): the roll covers the whole screen; photos /
        videos / FX overlay it translucently.
        True (compact): the roll is a strip at the bottom
        (_piano_compact_frac of the height) drawn ON TOP of the normal
        visual stack, so photos / videos / FX keep full brightness.
        Held / scrolling notes survive the switch."""
        on = bool(on)
        if on == self._piano_compact:
            return
        self._piano_compact = on
        self._relayout_piano_scene()
        self.pianoCompactChanged.emit(on)
        self._dirty = True
        self.update()

    @Slot(float)
    def set_piano_compact_frac(self, frac: float) -> None:
        """Height of the compact strip as a fraction of the screen."""
        self._piano_compact_frac = max(0.1, min(0.5, float(frac)))
        if self._piano_compact:
            self._relayout_piano_scene()
            self._dirty = True

    @Slot(float)
    def set_piano_compact_opacity(self, opacity: float) -> None:
        """Opacity of the compact strip over an underlying picture."""
        self._piano_compact_opacity = max(0.0, min(1.0, float(opacity)))
        self._dirty = True

    @Slot(str)
    def set_piano_compact_position(self, pos: str) -> None:
        """'bottom' (default) or 'top' — where the compact strip sits."""
        self._piano_compact_position = ("top" if str(pos).strip().lower() == "top"
                                        else "bottom")
        self._dirty = True

    @Slot(float)
    def set_piano_keyboard_height(self, frac: float) -> None:
        """Keyboard height as a fraction of the screen (before the output
        correction divides it).  Default 0.18."""
        self._piano_kb_base_frac = max(0.02, min(0.6, float(frac)))
        self._relayout_piano_scene()
        self._dirty = True

    def set_piano_note_range(self, note_min: int, note_max: int) -> None:
        """MIDI note range drawn (defaults 21..108 = 88 keys).  Applies to
        the next piano-mode ON (the running scene keeps its layout)."""
        lo = max(0, min(127, int(note_min)))
        hi = max(lo, min(127, int(note_max)))
        self._piano_note_min, self._piano_note_max = lo, hi

    # ---------- misc config-driven tunables ----------
    @Slot(int)
    def set_idle_return_sec(self, sec: int) -> None:
        """Quiet time before the POCOBOARD title fades back in (0 = never)."""
        sec = max(0, int(sec))
        self._idle_return_ms = sec * 1000 if sec > 0 else float("inf")

    @Slot(int)
    def set_idle_title_fade_ms(self, ms: int) -> None:
        self._title_fade_ms = max(1.0, float(ms))

    @Slot(float)
    def set_video_fx_opacity(self, opacity: float) -> None:
        """FX opacity while an uploaded video is the background."""
        self._video_fx_opacity = max(0.0, min(1.0, float(opacity)))
        self._dirty = True

    @Slot(float)
    def set_camera_poll_fps(self, fps: float) -> None:
        """Poll rate for the DirectShow camera backend."""
        fps = max(1.0, min(120.0, float(fps)))
        self._dshow_poll_ms = 1000.0 / fps

    @Slot(float)
    def set_marquee_scroll_pps(self, pps: float) -> None:
        """Marquee speed at speed-stop 1, in px/s (stops 1..5 multiply it)."""
        self._marquee.scroll_px_per_s = max(20.0, float(pps))

    @Slot(float)
    def set_marquee_pin_sec(self, sec: float) -> None:
        """On-screen lifetime of <ue>/<shita> pinned messages."""
        self._marquee.pin_duration_s = max(0.5, float(sec))

    @Slot(int, int)
    def piano_note_on(self, note: int, velocity: int) -> None:
        if not self._piano_mode or self._piano_scene is None:
            return
        # Defensive: if a single note event ever throws (corrupt scene
        # state, surprise edge case), swallow it so the next paintEvent
        # still runs.  Without this, an exception inside the slot can
        # propagate up through Qt and quietly stop the meta-call queue
        # for the rest of the session — exactly the "MIDI 来てるのに
        # 何も出ない、再起動で直る" symptom the user reported.
        try:
            self._piano_scene.note_on(int(note), int(velocity))
            self._mark_activity()
        except Exception as exc:
            print(f"[piano] note_on({note},{velocity}) failed: {exc!r}")

    @Slot(int)
    def piano_note_off(self, note: int) -> None:
        if not self._piano_mode or self._piano_scene is None:
            return
        try:
            self._piano_scene.note_off(int(note))
        except Exception as exc:
            print(f"[piano] note_off({note}) failed: {exc!r}")

    @Slot(int)
    def set_media_min_play_sec(self, sec: int) -> None:
        """Set the minimum playback duration for videos (and audio files).

        When a clip's natural length is shorter than this, we restart
        playback from position 0 on each end-of-media until the total
        elapsed playback time reaches this many seconds.  0 disables the
        loop-to-minimum behavior (videos play once, then stop).
        """
        self._media_min_play_sec = max(0, int(sec))

    @Slot(float)
    def set_video_volume(self, vol: float) -> None:
        """Set video-audio gain (0.0..1.0) — driven by the 外部音声 slider."""
        self._video_volume = max(0.0, min(1.0, float(vol)))
        if self._video_audio is not None:
            self._video_audio.setVolume(self._video_volume)

    def _clear_image_internal(self) -> bool:
        had_image = self._bg_image is not None
        self._image_timer.stop()
        self._bg_image = None
        self._bg_caption = ""
        self._bg_cache_key = None
        self._bg_cache_pm = None
        self._dirty = True
        if self._bg_image_owner:
            self._bg_image_owner = ""
            self.ownershipChanged.emit("image", "")
        if had_image:
            self.visualPlaybackStopped.emit()
        return had_image

    # ---------- video overlay ----------
    def _ensure_video_player(self) -> None:
        if self._video_player is not None:
            return
        # Frame-by-frame compositing path.  QVideoSink hands us QImages
        # via videoFrameChanged; paintEvent picks up the latest frame and
        # blits it (with opacity, in piano-roll mode).  The previous
        # QVideoWidget approach drew straight to the GPU which made
        # painter opacity a no-op.
        self._video_sink = QVideoSink(self)
        self._video_sink.videoFrameChanged.connect(self._on_video_frame)
        self._video_audio = QAudioOutput(self)
        self._video_audio.setVolume(self._video_volume)
        self._video_player = QMediaPlayer(self)
        self._video_player.setVideoSink(self._video_sink)
        self._video_player.setAudioOutput(self._video_audio)
        # Play each clip exactly once; we reschedule via setPosition(0) +
        # play() inside _on_video_status if the min-play window still
        # hasn't elapsed.  That way the loop count auto-matches each
        # clip's natural length (short clips loop, long clips play once).
        self._video_player.setLoops(1)
        self._video_player.errorOccurred.connect(self._on_video_error)
        self._video_player.mediaStatusChanged.connect(self._on_video_status)

    def _on_video_frame(self, frame) -> None:
        # Cheap path: drop invalid / empty frames so paintEvent keeps
        # showing the previous one (e.g., during a brief decoder hiccup).
        if frame is None or not frame.isValid():
            return
        img = frame.toImage()
        if img is None or img.isNull():
            return
        self._latest_video_image = img
        # No explicit update() — _tick repaints on the next 16 ms tick
        # when it sees the dirty flag.
        self._frame_dirty = True

    @Slot(str)
    @Slot(str, str)
    @Slot(str, str, str)
    def show_image(self, path: str, caption: str = "", owner: str = "") -> bool:
        """Install an uploaded photo as the background.

        The image stays on screen — underneath any FX and marquee — for
        `image_display_sec` seconds (configured at boot, live-tunable from
        the control window), after which it is auto-cleared.  Setting the
        duration to 0 makes the image persist until the operator presses
        停止.  `owner` is the uploader's client_id so that uploader (but
        no one else) can dismiss it from the browser.

        Returns True if the image loaded and was installed, False if the
        file could not be decoded (any prior background is left untouched).

        While piano-roll mode is active the image is rendered as a
        semi-transparent overlay on top of the keyboard scene (see
        paintEvent), so it remains useful to upload images during the
        performance.
        """
        # Honor EXIF orientation: smartphones often store portrait photos
        # as landscape pixels + an Orientation tag asking the viewer to
        # rotate. QPixmap(path) ignores that tag, so portrait shots came
        # out sideways. QImageReader.setAutoTransform(True) reads the tag
        # and applies the rotation/mirroring before we get the pixels.
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        img = reader.read()
        if img.isNull():
            return False
        pm = QPixmap.fromImage(img)
        if pm.isNull():
            return False
        # Image background replaces video background (but not ongoing FX).
        # Image / video stay mutually exclusive in the visual slot — the
        # piano roll is rendered as a separate base layer, not as one of
        # the visual-slot kinds.
        self._stop_video_internal()
        self._bg_image = pm
        self._bg_caption = caption or ""
        self._bg_image_owner = owner or ""
        self.ownershipChanged.emit("image", self._bg_image_owner)
        self._mark_activity()
        self._image_timer.stop()
        if self._image_display_sec > 0:
            self._image_timer.start(self._image_display_sec * 1000)
        return True

    def _on_image_timeout(self) -> None:
        """Auto-clear handler: drop the image background only.

        Leaves FX / marquee / video alone — those have their own lifecycles.
        No-op if the image has already been replaced or cleared.
        """
        self._clear_image_internal()

    @Slot()
    def clear_image_bg(self) -> None:
        """Drop just the image background (per-user 取消 from the browser)."""
        self._clear_image_internal()

    @Slot(str)
    @Slot(str, str)
    def play_video(self, path: str, owner: str = "") -> None:
        """Play a video; stops at first natural end past
        `media_min_play_sec` (see _on_video_status).

        While piano-roll mode is active the video is composited on top
        of the keyboard scene as a semi-transparent overlay (see
        paintEvent).  Outside piano mode it acts as the full-screen
        background.
        """
        self._ensure_video_player()
        assert self._video_player is not None
        # Image and video share the visual slot — clear any image first.
        self._clear_image_internal()
        # Drop any leftover frame from a previous clip so the first paint
        # after play() doesn't briefly show the old poster.
        self._latest_video_image = None
        url = QUrl.fromLocalFile(path) if os.path.isfile(path) else QUrl(path)
        self._video_url = url
        self._video_start_ms = time.perf_counter_ns() / 1_000_000.0
        self._video_player.setSource(url)
        self._video_player.play()
        self._video_active = True
        self._video_owner = owner or ""
        self.ownershipChanged.emit("video", self._video_owner)
        self._mark_activity()

    def _stop_video_internal(self) -> None:
        had_video = self._video_active or self._video_url is not None
        if self._video_player is not None:
            self._video_player.stop()
            self._video_player.setSource(QUrl())
        self._video_active = False
        self._video_url = None
        self._latest_video_image = None
        self._frame_cache_key = None
        self._frame_cache_pm = None
        self._dirty = True
        if self._video_owner:
            self._video_owner = ""
            self.ownershipChanged.emit("video", "")
        if had_video:
            self.visualPlaybackStopped.emit()

    def _on_video_status(self, status) -> None:
        # On EndOfMedia, decide whether to loop (min-play-sec not yet met)
        # or stop (natural end past the minimum).
        end_val = getattr(QMediaPlayer.MediaStatus, "EndOfMedia", None)
        if end_val is None or status != end_val:
            return
        if not self._video_active or self._video_player is None:
            return
        elapsed_ms = (time.perf_counter_ns() / 1_000_000.0) - self._video_start_ms
        min_ms = self._media_min_play_sec * 1000
        if elapsed_ms < min_ms and self._video_url is not None:
            # Loop: seek to start and keep playing.  setPosition + play is
            # cheaper than re-setSource on Qt 6 / FFmpeg backends.
            try:
                self._video_player.setPosition(0)
                self._video_player.play()
                return
            except Exception:
                # Fall through to stop on any backend misbehavior.
                pass
        self._stop_video_internal()

    def _on_video_error(self, err, msg) -> None:
        print(f"[video] error {err}: {msg}")
        self._stop_video_internal()

    @Slot()
    def stop_video(self) -> None:
        self._stop_video_internal()

    @Slot()
    def clear_display(self) -> None:
        """Hard reset: drop image/video background, stop any FX mid-flight.

        Marquee and audio are left alone intentionally — the caller in
        pocoboard.py stops file-audio separately.  Keeping the marquee
        running lets the operator clear just the visuals without wiping a
        long scrolling announcement.
        """
        self._stop_video_internal()
        self._clear_image_internal()
        self._scene = None
        # Bring us back to the black idle state (not the title) — the
        # operator explicitly asked for "quiet black" after clearing.
        self._show_idle_title = False
        self._title_fade = 0.0
        self._dirty = True
        # Preserve the 5-minute idle timer rather than restarting it.

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._relayout_piano_scene()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            if self._cursor_hidden:
                self.unsetCursor()
                self._cursor_hidden = False
        else:
            self.showFullScreen()

    # ---------- key handling ----------
    def keyPressEvent(self, ev: QKeyEvent) -> None:
        k = ev.key()
        if k == Qt.Key.Key_Escape and self.isFullScreen():
            self.showNormal()
            if self._cursor_hidden:
                self.unsetCursor()
                self._cursor_hidden = False
            return
        if k == Qt.Key.Key_F11:
            self.toggle_fullscreen()
            return
        if k == Qt.Key.Key_C:
            # toggle cursor hide (useful in fullscreen)
            if self._cursor_hidden:
                self.unsetCursor()
                self._cursor_hidden = False
            else:
                self.setCursor(Qt.CursorShape.BlankCursor)
                self._cursor_hidden = True
            return
        super().keyPressEvent(ev)

    # ---------- tick / paint ----------
    def _tick(self) -> None:
        now = time.perf_counter_ns()
        dt_ms = (now - self._last_ns) / 1_000_000.0
        self._last_ns = now
        if dt_ms > 100:
            dt_ms = 100
        if self._scene is not None:
            if not self._scene.update(dt_ms):
                self._scene = None
                self._dirty = True   # paint once more to erase FX remnants
        if self._piano_scene is not None:
            try:
                self._piano_scene.update(dt_ms)
            except Exception as exc:
                # Same defensive philosophy as the note-on slot — never
                # let a bad frame stop subsequent ticks.
                print(f"[piano] scene.update failed: {exc!r}")
        if self._marquee.tracks:
            self._marquee.step(dt_ms)
            self._emit_marquee_status()
            if not self._marquee.tracks:
                self._dirty = True   # last message left — erase it

        # DirectShow camera backend is pull-based: poll ~30 fps, and only
        # while the camera is actually visible (same occlusion rule as
        # the Qt sink's conversion skip — piano mode keeps polling since
        # the roll is a translucent overlay above the camera).
        if (self._dshow_cam is not None and self._camera_mode
                and not self._video_active
                and self._bg_image is None):
            self._dshow_poll_accum += dt_ms
            if self._dshow_poll_accum >= self._dshow_poll_ms:
                self._dshow_poll_accum = 0.0
                try:
                    img = self._dshow_cam.grab()
                except Exception as exc:
                    print(f"[dshow] grab failed: {exc!r}")
                    img = None
                if img is not None:
                    self._ingest_camera_frame(img)

        # Idle-return: after a quiet period, fade the title back in.
        if not self._show_idle_title and self._last_activity_ms > 0:
            now_ms = now / 1_000_000.0
            if now_ms - self._last_activity_ms >= self._idle_return_ms:
                self._show_idle_title = True
                self._title_fade = 0.0
        if self._show_idle_title and self._title_fade < 1.0:
            # Ease-in from black to the branded screen (idle_title_fade_ms).
            self._title_fade = min(1.0, self._title_fade + dt_ms / self._title_fade_ms)

        animating = (self._scene is not None
                     or self._piano_scene is not None
                     or bool(self._marquee.tracks)
                     or (self._show_idle_title and self._title_fade < 1.0))
        if animating or self._dirty or self._frame_dirty:
            self._dirty = False
            self._frame_dirty = False
            self._heartbeat_ms = 0.0
            self.update()
        else:
            # Nothing moving: repaint at ~2 Hz so the footer stays fresh
            # and any missed invalidation heals itself within 500 ms.
            self._heartbeat_ms += dt_ms
            if self._heartbeat_ms >= 500.0:
                self._heartbeat_ms = 0.0
                self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        # Two coordinate spaces:
        #  - PHYSICAL (pw, ph): the camera layer and background fills —
        #    the camera applies its own (squared) horizontal correction.
        #  - VIRTUAL (w, h): everything POCOBoard draws itself — FX,
        #    marquee, piano roll, photos, videos, idle title — composes
        #    on the horizontally-shrunk virtual canvas and is stretched
        #    to full width by _vpush/_vpop, so the downstream squeeze
        #    restores true proportions (BOMB circles stay round, the
        #    piano keyboard spans the whole final screen).
        pw = max(1, self.width())
        ph = max(1, self.height())
        w, h = self._virtual_size()
        _stretched = w != pw

        def _vpush() -> None:
            if _stretched:
                p.save()
                p.scale(pw / w, 1.0)

        def _vpop() -> None:
            if _stretched:
                p.restore()

        # Layer order (back → front).  Piano mode adds a piano-roll BASE
        # underneath everything; the visual slots (image / video) and
        # FX overlay semi-transparently on top so all four (roll +
        # image OR video + FX + marquee) stay visible together.
        #
        #   piano-mode ON, normal layout:
        #     1. PianoRollScene (opaque base)
        #     2. Image, if any   @ piano_image_opacity
        #     2. Video frame, if any @ piano_video_opacity
        #        (image/video are mutually exclusive in the visual slot)
        #     3. FX scene, if any @ piano_fx_opacity
        #     4. Marquee
        #
        #   piano-mode ON, compact layout:
        #     1-2. exactly the piano-mode-OFF stack below (photos /
        #          videos / camera / FX at full brightness) ...
        #     3. ... then the PianoRollScene as a strip along the bottom
        #        (or top: piano_compact_position; piano_compact_height_pct
        #        of the screen), translucent @ piano_compact_opacity over
        #        whatever is beneath it
        #     4. Marquee
        #
        #   piano-mode OFF (legacy behavior):
        #     1. Video frame as full-screen background, OR
        #        Image background, OR
        #        Live camera feed (camera mode — the default idle base), OR
        #        Idle "POCOBOARD" title, OR
        #        Black fill
        #     2. FX scene (opaque normally; @0.75 over video / tunable
        #        @camera_fx_opacity over the camera feed)
        #     3. Marquee (tunable @camera_marquee_opacity over the camera)
        has_video = self._video_active and self._latest_video_image is not None
        has_image = self._bg_image is not None and not self._bg_image.isNull()
        piano_on = self._piano_mode and self._piano_scene is not None
        # Full-screen roll as the base layer (normal layout) vs. a strip
        # painted over the ordinary stack (compact layout).
        piano_full    = piano_on and not self._piano_compact
        piano_compact = piano_on and self._piano_compact
        # The camera acts as the bottom of the visual stack: uploaded
        # image / video and the full-screen piano roll all take
        # precedence over it.
        camera_visible = (not piano_full and not has_video
                          and not has_image and self._camera_mode
                          and self._latest_camera_image is not None
                          and not self._latest_camera_image.isNull())

        if piano_full:
            # Base layer: live camera (if any) with the keyboard +
            # scrolling note bars over it SEMI-TRANSPARENTLY, so the
            # camera picture stays visible through the whole roll.
            # Without a camera the roll paints opaque as before.
            has_camera_frame = (self._camera_mode
                                and self._latest_camera_image is not None
                                and not self._latest_camera_image.isNull())
            if has_camera_frame:
                p.fillRect(0, 0, pw, ph, Qt.GlobalColor.black)
                self._draw_camera_frame(p, pw, ph)
                _vpush()
                p.setOpacity(self._piano_roll_opacity)
                self._piano_scene.draw(p, w, h)
                p.setOpacity(1.0)
                _vpop()
            else:
                p.fillRect(0, 0, pw, ph, Qt.GlobalColor.black)
                _vpush()
                self._piano_scene.draw(p, w, h)
                _vpop()
            # Visual-slot overlays (image / video) on top, translucent.
            if has_video:
                _vpush()
                p.setOpacity(self._piano_video_opacity)
                self._draw_video_frame(p, w, h)
                p.setOpacity(1.0)
                _vpop()
            if has_image:
                _vpush()
                p.setOpacity(self._piano_image_opacity)
                self._draw_bg_image(p, w, h)
                p.setOpacity(1.0)
                _vpop()
        elif has_video:
            # Non-piano mode: video frame fills the screen as background.
            p.fillRect(0, 0, pw, ph, Qt.GlobalColor.black)
            _vpush()
            self._draw_video_frame(p, w, h)
            _vpop()
        elif has_image:
            p.fillRect(0, 0, pw, ph, Qt.GlobalColor.black)
            _vpush()
            self._draw_bg_image(p, w, h)
            _vpop()
        elif camera_visible:
            p.fillRect(0, 0, pw, ph, Qt.GlobalColor.black)
            self._draw_camera_frame(p, pw, ph)
        elif self._show_idle_title and self._scene is None:
            p.fillRect(0, 0, pw, ph, QColor(8, 10, 16))
            _vpush()
            self._draw_idle(p, w, h, alpha=self._title_fade)
            _vpop()
        else:
            p.fillRect(0, 0, pw, ph, Qt.GlobalColor.black)

        if self._scene is not None and self._scene.alive:
            _vpush()
            if piano_full:
                p.setOpacity(self._piano_fx_opacity)
                self._scene.draw(p, w, h)
                p.setOpacity(1.0)
            elif camera_visible:
                p.setOpacity(self._camera_fx_opacity)
                self._scene.draw(p, w, h)
                p.setOpacity(1.0)
            elif has_video:
                p.setOpacity(self._video_fx_opacity)
                self._scene.draw(p, w, h)
                p.setOpacity(1.0)
            else:
                self._scene.draw(p, w, h)
            _vpop()

        if piano_compact:
            # Compact strip along the bottom, over the full-brightness
            # stack above.  Translucent whenever something is showing
            # underneath (camera / photo / video / idle title) so it
            # never blacks out the bottom of the picture; opaque over a
            # plain black background.
            sw, sh = self._piano_scene_size()
            has_base = (camera_visible or has_video or has_image
                        or (self._show_idle_title and self._scene is None))
            _vpush()
            p.save()
            p.translate(0, 0 if self._piano_compact_position == "top" else h - sh)
            p.setClipRect(0, 0, sw, sh)
            if has_base:
                p.setOpacity(self._piano_compact_opacity)
            self._piano_scene.draw(p, sw, sh)
            p.setOpacity(1.0)
            p.restore()
            _vpop()

        if self._marquee.tracks:
            _vpush()
            if camera_visible:
                p.setOpacity(self._camera_marquee_opacity)
                self._marquee.draw(p, QRectF(0, 0, w, h))
                p.setOpacity(1.0)
            else:
                self._marquee.draw(p, QRectF(0, 0, w, h))
            _vpop()

    def _draw_video_frame(self, p: QPainter, w: int, h: int) -> None:
        self._draw_letterboxed(p, w, h, self._latest_video_image)

    def _draw_camera_frame(self, p: QPainter, w: int, h: int) -> None:
        """Camera layer.  Draws in PHYSICAL window coordinates — the
        camera picture arrives pre-squeezed by the capture board, so its
        own _camera_hstretch (squeeze squared) is the complete
        correction; it must NOT additionally pass through the virtual
        canvas used by the drawn layers."""
        img = self._latest_camera_image
        if img is None or img.isNull():
            return
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return
        # Letterbox fit, then stretch ONLY the width by the operator's
        # factor about the window's center axis.  The vertical size is
        # untouched; whatever the widening pushes past the window edges
        # is clipped away.
        scale = min(w / iw, h / ih)
        dw = max(1, int(iw * scale * self._camera_hstretch))
        dh = max(1, int(ih * scale))
        dy = (h - dh) // 2
        if dw <= w:
            p.drawPixmap((w - dw) // 2,
                         dy, self._cached_frame_pixmap(img, None, dw, dh))
            return
        # Wider than the window: only the central w/dw fraction of the
        # frame is visible — crop that from the source and scale it once
        # to exactly window width instead of rendering offscreen pixels.
        src_w = iw * w / dw
        sx = (iw - src_w) / 2.0
        pm = self._cached_frame_pixmap(
            img, (int(sx), 0, max(1, int(src_w)), ih), w, dh)
        p.drawPixmap(0, dy, pm)

    def _draw_letterboxed(self, p: QPainter, w: int, h: int,
                          img: Optional[QImage]) -> None:
        if img is None or img.isNull():
            return
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return
        scale = min(w / iw, h / ih)
        dw = max(1, int(iw * scale))
        dh = max(1, int(ih * scale))
        dx = (w - dw) // 2
        dy = (h - dh) // 2
        p.drawPixmap(dx, dy, self._cached_frame_pixmap(img, None, dw, dh))

    def _cached_frame_pixmap(self, img: QImage, crop: Optional[tuple],
                             dw: int, dh: int) -> QPixmap:
        """Crop + scale `img` to (dw, dh), cached until the frame changes.

        Frames arrive at capture rate (~30 fps) but paints can run at
        60 fps (e.g. marquee scrolling over the camera feed).  Keying on
        QImage.cacheKey() means the crop/scale/convert work happens once
        per *frame*, not once per *paint* — repeat paints just blit the
        cached QPixmap.  Single slot: only one live frame source (camera
        or video) is ever the visual base at a time.
        """
        key = (img.cacheKey(), crop, dw, dh)
        if key == self._frame_cache_key and self._frame_cache_pm is not None:
            return self._frame_cache_pm
        src = img if crop is None else img.copy(*crop)
        scaled = src.scaled(dw, dh,
                            Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.FastTransformation)
        pm = QPixmap.fromImage(scaled)
        self._frame_cache_key = key
        self._frame_cache_pm = pm
        return pm

    def _draw_bg_image(self, p: QPainter, w: int, h: int) -> None:
        pm = self._bg_image
        assert pm is not None
        pw, ph = pm.width(), pm.height()
        if pw == 0 or ph == 0:
            return
        margin = 0
        avail_w = max(1, w - 2 * margin)
        avail_h = max(1, h - 2 * margin)
        scale = min(avail_w / pw, avail_h / ph)
        dw = max(1, int(pw * scale))
        dh = max(1, int(ph * scale))
        dx = (w - dw) // 2
        dy = (h - dh) // 2
        # Scale the (potentially multi-megapixel) photo once per size and
        # reuse — the previous per-paint `drawPixmap(dx, dy, dw, dh, pm)`
        # rescaled the full-resolution pixmap on every repaint (60 fps
        # while a marquee scrolls over it).  Smooth transformation is
        # affordable here precisely because it runs once, and it looks
        # noticeably better on downscaled photos than the painter's fast
        # path did.
        key = (pm.cacheKey(), dw, dh)
        if key != self._bg_cache_key or self._bg_cache_pm is None:
            self._bg_cache_key = key
            self._bg_cache_pm = pm.scaled(
                dw, dh,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        p.drawPixmap(dx, dy, self._bg_cache_pm)
        if self._bg_caption:
            cap_px = max(18, int(h * 0.028))
            f = QFont("Segoe UI Variable Text", 0)
            f.setPixelSize(cap_px)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(self._bg_caption)
            pad = int(cap_px * 0.6)
            tx = (w - tw) // 2
            ty = h - int(cap_px * 1.4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(QRectF(tx - pad, ty - fm.ascent(),
                                     tw + pad * 2, fm.height() + 6),
                              8, 8)
            p.setPen(QColor(245, 250, 255, 235))
            p.drawText(int(tx), int(ty), self._bg_caption)

        # Footer status (tiny, bottom-right)
        if self._status_text_cb is not None:
            txt = self._status_text_cb() or ""
            if txt:
                p.setFont(self._footer_font)
                fm = QFontMetricsF(self._footer_font)
                tw = fm.horizontalAdvance(txt)
                th = fm.height()
                pad = 10
                p.fillRect(
                    QRectF(w - tw - pad * 2 - 12, h - th - pad - 10, tw + pad * 2, th + pad),
                    QColor(0, 0, 0, 140),
                )
                p.setPen(QColor(210, 220, 255, 230))
                p.drawText(int(w - tw - pad - 12),
                           int(h - pad - 10 + fm.ascent()), txt)

    def _draw_idle(self, p: QPainter, w: int, h: int, alpha: float = 1.0) -> None:
        # Big "POCOBOARD" title + subtitle. `alpha` fades the whole branding
        # in from black when we return from the quiet "black" state.
        if alpha <= 0.0:
            return
        title_px = max(48, int(h * 0.18))
        sub_px   = max(16, int(h * 0.035))
        title_f = QFont(self._title_font)
        title_f.setPixelSize(title_px)
        sub_f = QFont(self._sub_font)
        sub_f.setPixelSize(sub_px)

        p.setFont(title_f)
        fm_t = QFontMetricsF(title_f)
        tw = fm_t.horizontalAdvance("POCOBOARD")
        p.setPen(QColor(50, 80, 120, int(240 * alpha)))
        p.drawText(int((w - tw) / 2 + 4), int(h / 2 + 4), "POCOBOARD")
        p.setPen(QColor(200, 220, 255, int(230 * alpha)))
        p.drawText(int((w - tw) / 2),     int(h / 2),     "POCOBOARD")

        p.setFont(sub_f)
        fm_s = QFontMetricsF(sub_f)
        sub = "READY — waiting for FX / marquee"
        sw = fm_s.horizontalAdvance(sub)
        p.setPen(QColor(150, 180, 210, int(180 * alpha)))
        p.drawText(int((w - sw) / 2), int(h / 2 + title_px * 0.55), sub)
