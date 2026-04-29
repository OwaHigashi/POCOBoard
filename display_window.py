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

from PySide6.QtCore       import QRect, QRectF, QPointF, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui        import QColor, QFont, QFontMetricsF, QImage, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink
from PySide6.QtWidgets    import QWidget

from animations import ImageScene, PianoRollScene, Scene, make_scene
from marquee    import MarqueeEngine


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
        self._idle_return_ms  = 5 * 60 * 1000   # 5 minutes
        # Fade-in of the title when returning from dark — 0..1, updated each tick.
        self._title_fade = 1.0

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

    # ---------- activity tracking ----------
    def _mark_activity(self) -> None:
        """Called whenever the display receives a visible/audible request.

        Hides the idle title until IDLE_RETURN_MS of silence passes.
        """
        self._last_activity_ms = time.perf_counter_ns() / 1_000_000.0
        self._show_idle_title = False
        self._title_fade = 0.0

    @Slot()
    def mark_talk_activity(self) -> None:
        """Slot for talk chunks — TALK has no visuals but still counts as
        'someone is using this' so the title shouldn't reappear mid-chat."""
        self._mark_activity()

    # ---------- public slots (called from any thread via QueuedConnection) ----------
    @Slot(str)
    def trigger_fx(self, kind: str) -> None:
        self._marquee.stop_all()
        self._emit_marquee_status()
        self._scene = make_scene(kind, max(1, self.width()), max(1, self.height()))
        self._mark_activity()

    @Slot(str, int)
    def add_marquee(self, text: str, speed: int) -> str:
        res = self._marquee.add(
            text, max(1, self.width()), max(1, self.height()), speed)
        self._emit_marquee_status()
        self._mark_activity()
        return res

    @Slot()
    def stop_marquee(self) -> None:
        self._marquee.stop_all()
        self._emit_marquee_status()

    def _emit_marquee_status(self) -> None:
        self.marqueeStatusChanged.emit(
            self._marquee.lanes_in_use(), self._marquee.max_lanes())

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
    def set_piano_scroll_pps(self, pps: float) -> None:
        self._piano_scroll_pps = max(20.0, float(pps))
        if self._piano_scene is not None:
            self._piano_scene.scroll_pps = self._piano_scroll_pps

    @Slot(float)
    def set_piano_fx_opacity(self, opacity: float) -> None:
        self._piano_fx_opacity = max(0.0, min(1.0, float(opacity)))

    @Slot(float)
    def set_piano_image_opacity(self, opacity: float) -> None:
        self._piano_image_opacity = max(0.0, min(1.0, float(opacity)))

    @Slot(float)
    def set_piano_video_opacity(self, opacity: float) -> None:
        self._piano_video_opacity = max(0.0, min(1.0, float(opacity)))

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
            self._piano_scene = PianoRollScene(
                max(1, self.width()), max(1, self.height()),
                scroll_pps=self._piano_scroll_pps)
            self._mark_activity()
        else:
            # Release every held note and drop the scene.
            if self._piano_scene is not None:
                self._piano_scene.all_off()
            self._piano_scene = None
        self.pianoModeChanged.emit(on)
        self.update()

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

    def _clear_image_internal(self) -> bool:
        had_image = self._bg_image is not None
        self._image_timer.stop()
        self._bg_image = None
        self._bg_caption = ""
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
        self._video_audio.setVolume(0.8)
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
        # No explicit update() — _tick fires self.update() at 60 fps and
        # will pick this frame up on the next paint.

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
        pm = QPixmap(path)
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
        # Preserve the 5-minute idle timer rather than restarting it.

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self._piano_scene is not None:
            self._piano_scene.resize(max(1, self.width()), max(1, self.height()))

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

        # Idle-return: after a quiet period, fade the title back in.
        if not self._show_idle_title and self._last_activity_ms > 0:
            now_ms = now / 1_000_000.0
            if now_ms - self._last_activity_ms >= self._idle_return_ms:
                self._show_idle_title = True
                self._title_fade = 0.0
        if self._show_idle_title and self._title_fade < 1.0:
            # 1.2 s ease-in from black to the branded screen.
            self._title_fade = min(1.0, self._title_fade + dt_ms / 1200.0)

        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        w, h = self.width(), self.height()

        # Layer order (back → front).  Piano mode adds a piano-roll BASE
        # underneath everything; the visual slots (image / video) and
        # FX overlay semi-transparently on top so all four (roll +
        # image OR video + FX + marquee) stay visible together.
        #
        #   piano-mode ON:
        #     1. PianoRollScene (opaque base)
        #     2. Image, if any   @ piano_image_opacity
        #     2. Video frame, if any @ piano_video_opacity
        #        (image/video are mutually exclusive in the visual slot)
        #     3. FX scene, if any @ piano_fx_opacity
        #     4. Marquee
        #
        #   piano-mode OFF (legacy behavior):
        #     1. Video frame as full-screen background, OR
        #        Image background, OR
        #        Idle "POCOBOARD" title, OR
        #        Black fill
        #     2. FX scene (opaque normally; @0.75 over video so the video
        #        stays visible through the spark storm)
        #     3. Marquee
        has_video = self._video_active and self._latest_video_image is not None
        has_image = self._bg_image is not None and not self._bg_image.isNull()

        if self._piano_mode and self._piano_scene is not None:
            # Base layer: keyboard + scrolling note bars.
            self._piano_scene.draw(p, w, h)
            # Visual-slot overlays (image / video) on top, translucent.
            if has_video:
                p.setOpacity(self._piano_video_opacity)
                self._draw_video_frame(p, w, h)
                p.setOpacity(1.0)
            if has_image:
                p.setOpacity(self._piano_image_opacity)
                self._draw_bg_image(p, w, h)
                p.setOpacity(1.0)
        elif has_video:
            # Non-piano mode: video frame fills the screen as background.
            p.fillRect(0, 0, w, h, Qt.GlobalColor.black)
            self._draw_video_frame(p, w, h)
        elif has_image:
            p.fillRect(0, 0, w, h, Qt.GlobalColor.black)
            self._draw_bg_image(p, w, h)
        elif self._show_idle_title and self._scene is None:
            p.fillRect(0, 0, w, h, QColor(8, 10, 16))
            self._draw_idle(p, w, h, alpha=self._title_fade)
        else:
            p.fillRect(0, 0, w, h, Qt.GlobalColor.black)

        if self._scene is not None and self._scene.alive:
            if self._piano_mode:
                p.setOpacity(self._piano_fx_opacity)
                self._scene.draw(p, w, h)
                p.setOpacity(1.0)
            elif has_video:
                p.setOpacity(0.75)
                self._scene.draw(p, w, h)
                p.setOpacity(1.0)
            else:
                self._scene.draw(p, w, h)

        if self._marquee.tracks:
            self._marquee.draw(p, QRectF(0, 0, w, h))

    def _draw_video_frame(self, p: QPainter, w: int, h: int) -> None:
        img = self._latest_video_image
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
        p.drawImage(QRect(dx, dy, dw, dh), img)

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
        dw = int(pw * scale)
        dh = int(ph * scale)
        dx = (w - dw) // 2
        dy = (h - dh) // 2
        p.drawPixmap(dx, dy, dw, dh, pm)
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
