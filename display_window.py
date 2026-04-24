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
from PySide6.QtGui        import QColor, QFont, QFontMetricsF, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets    import QWidget

from animations import ImageScene, Scene, make_scene
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
        # Image: we keep a pixmap and draw it in paintEvent, letterboxed.
        # Video: QVideoWidget overlay; the minimum-play-time rule decides
        #        when it stops (see _on_video_status).
        self._bg_image: Optional[QPixmap] = None
        self._bg_caption: str = ""
        self._bg_image_owner: str = ""    # uploader client_id

        # --- video overlay (QMediaPlayer + QVideoWidget) ---
        # Created lazily the first time a video request arrives.
        self._video_widget: Optional[QVideoWidget] = None
        self._video_player: Optional[QMediaPlayer] = None
        self._video_audio:  Optional[QAudioOutput] = None
        self._video_active: bool = False
        self._video_owner: str = ""       # uploader client_id
        self._video_url: Optional[QUrl] = None
        self._video_start_ms: float = 0.0
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
    def _ensure_video_widgets(self) -> None:
        if self._video_widget is not None:
            return
        self._video_widget = QVideoWidget(self)
        self._video_widget.setStyleSheet("background:#000;")
        self._video_widget.hide()
        self._video_audio  = QAudioOutput(self)
        self._video_audio.setVolume(0.8)
        self._video_player = QMediaPlayer(self)
        self._video_player.setVideoOutput(self._video_widget)
        self._video_player.setAudioOutput(self._video_audio)
        # Play each clip exactly once; we reschedule via setPosition(0) +
        # play() inside _on_video_status if the min-play window still
        # hasn't elapsed.  That way the loop count auto-matches each clip's
        # natural length (short clips loop, long clips play once).
        self._video_player.setLoops(1)
        self._video_player.errorOccurred.connect(self._on_video_error)
        self._video_player.mediaStatusChanged.connect(self._on_video_status)

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
        """
        pm = QPixmap(path)
        if pm.isNull():
            return False
        # Image background replaces video background (but not ongoing FX).
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
        """Play a video as the background, then stop at first natural end
        past `media_min_play_sec` (see _on_video_status).
        """
        self._ensure_video_widgets()
        assert self._video_widget and self._video_player
        # Clear any image background (and cancel its auto-clear timer); FX
        # can still run as a transient overlay because it paints the whole
        # window each frame.
        self._clear_image_internal()
        self._video_widget.setGeometry(0, 0, self.width(), self.height())
        self._video_widget.lower()
        self._video_widget.show()
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
        if self._video_widget is not None:
            self._video_widget.hide()
        self._video_active = False
        self._video_url = None
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
        if self._video_widget is not None and self._video_widget.isVisible():
            self._video_widget.setGeometry(0, 0, self.width(), self.height())

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

        # Layer order (back → front):
        #   1. Black (always the real backdrop)
        #   2. Background image, if any (persistent until clear_display)
        #      — video background draws itself as a child widget, so we
        #        DON'T fill the frame when video is active (else we'd
        #        erase each new frame).
        #   3. Idle title, if in the long-idle "welcome" state AND no
        #      other visual is present
        #   4. FX scene (opaque; covers background for its duration)
        #   5. Marquee tracks — always on top of everything visual
        has_video = self._video_active and self._video_widget is not None \
                    and self._video_widget.isVisible()

        if not has_video:
            if self._bg_image is not None and not self._bg_image.isNull():
                p.fillRect(0, 0, w, h, Qt.GlobalColor.black)
                self._draw_bg_image(p, w, h)
            elif self._show_idle_title and self._scene is None:
                p.fillRect(0, 0, w, h, QColor(8, 10, 16))
                self._draw_idle(p, w, h, alpha=self._title_fade)
            else:
                p.fillRect(0, 0, w, h, Qt.GlobalColor.black)

        if self._scene is not None and self._scene.alive:
            # FX covers the whole frame. For video backgrounds we render the
            # scene translucently, so the video stays visible underneath
            # the BOMB/CHEER spark storm — matches the "effect on top" spec.
            if has_video:
                p.setOpacity(0.75)
                self._scene.draw(p, w, h)
                p.setOpacity(1.0)
            else:
                self._scene.draw(p, w, h)

        if self._marquee.tracks:
            self._marquee.draw(p, QRectF(0, 0, w, h))

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
