"""Niconico-style multi-track text overlay — unlimited, overlap-friendly.

Message positioning (Niconico command convention):

  (default)             scrolling right→left across the screen
  <ue>...   <top>...    pinned at the top-center for ~3 s
  <shita>.. <bottom>... pinned at the bottom-center for ~3 s
  <naka>... <middle>... explicit scroll (same as default)

Styling markup (subset of M5Tab-Poco's vocabulary, extended with Niconico
color names):

  <r> <red>            <g> <green>      <b> <blue>
  <y> <yellow>         <c> <cyan>       <m> <purple>  <pink>
  <w> <white>          <o> <orange>     — closed by </> or </color>
  <small>/<s1>  <normal>/<s2>  <big>/<s3>
  <u>...</u>                underline
  <hl>/<mark>...</>         highlight background

There is **no lane cap**.  The engine picks the scroll lane with the most
tail clearance; if every lane is tight, it simply reuses one and lets the
messages overlap.  Top/bottom pins stack downward/upward and also allow
overlap when the stack fills the screen.
"""
from __future__ import annotations
import math
import random
import re
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui  import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen


_COLORS = {
    # short forms (back-compat with M5Tab-Poco markup)
    "r": QColor(255,  70,  70),
    "g": QColor( 90, 235,  90),
    "b": QColor(110, 150, 255),
    "y": QColor(255, 230,  90),
    "c": QColor(120, 235, 235),
    "m": QColor(220, 120, 235),
    "w": QColor(255, 255, 255),
    "o": QColor(255, 160,  50),
    # Niconico-style long names
    "red":    QColor(255,  70,  70),
    "green":  QColor( 90, 235,  90),
    "blue":   QColor(110, 150, 255),
    "yellow": QColor(255, 230,  90),
    "cyan":   QColor(120, 235, 235),
    "purple": QColor(220, 120, 235),
    "white":  QColor(255, 255, 255),
    "orange": QColor(255, 160,  50),
    "pink":   QColor(255, 140, 200),
}

_SIZE_SCALE = {
    "small": 0.70, "s1": 0.70,
    "normal": 1.0, "s2": 1.0,
    "big":    1.7, "s3": 1.7,
}

# Tags that control position (Niconico convention).  Presence of any of
# these in the text chooses its kind; they're stripped from the displayed
# string.
_POS_TAGS = {
    "ue": "top",     "top":    "top",
    "shita": "bottom", "bottom": "bottom",
    "naka": "scroll",  "middle": "scroll",
}
_POS_RE = re.compile(r"<(/?)(?:ue|top|shita|bottom|naka|middle)>", re.IGNORECASE)

# Default on-screen lifetime for pinned messages.
PIN_DURATION_S = 3.0
# Default traversal speed: 6 seconds for speed=1 (Niconico-ish).
# scroll_time_s = 6 / speed → speed=1 6s, speed=3 2s, speed=5 1.2s.
SCROLL_BASE_TIME_S = 6.0


@dataclass
class Run:
    text: str
    color: QColor
    size_scale: float = 1.0
    underline: bool = False
    highlight: bool = False


@dataclass
class _LaidRun(Run):
    width: float = 0.0
    ascent: float = 0.0
    descent: float = 0.0


@dataclass
class Track:
    kind: str                          # 'scroll' | 'top' | 'bottom'
    runs: list[_LaidRun]
    total_width: float
    max_ascent: float
    max_descent: float
    lane: int                          # vertical slot index (used for placement)
    # scroll-only
    x: float = 0.0                     # leftmost px (may drift negative)
    speed: int = 1
    px_per_s: float = 0.0
    # pin-only
    lifetime_s: float = 0.0
    finished: bool = False


# ---------- parser ----------
_TAG = re.compile(r"</?[a-zA-Z0-9_]+/?>|</>", re.UNICODE)


def _detect_position_and_strip(text: str) -> tuple[str, str]:
    """Return (kind, text_without_position_tags). First position tag wins."""
    kind = "scroll"
    for m in _POS_RE.finditer(text):
        closing = bool(m.group(1))
        if closing:
            continue
        tag_name = m.group(0).lower().strip("</>")
        k = _POS_TAGS.get(tag_name, "scroll")
        if k != "scroll":
            kind = k
            break
    # Remove all position tags (open and close) — they're meta, not content.
    cleaned = _POS_RE.sub("", text)
    return kind, cleaned


def _parse_runs(text: str) -> list[Run]:
    """Parse markup into a flat Run list."""
    pos = 0
    color_stack: list[QColor] = [QColor(255, 255, 255)]
    size_stack:  list[float]  = [1.0]
    underline = False
    highlight = False

    runs: list[Run] = []

    def emit(piece: str) -> None:
        if not piece:
            return
        runs.append(Run(
            text=piece,
            color=QColor(color_stack[-1]),
            size_scale=size_stack[-1],
            underline=underline,
            highlight=highlight,
        ))

    for m in _TAG.finditer(text):
        emit(text[pos:m.start()])
        tag = m.group().lower().strip("<>").strip()
        pos = m.end()

        if tag in ("/", "/color"):
            if len(color_stack) > 1:
                color_stack.pop()
            continue

        close = tag.startswith("/")
        name = tag[1:] if close else tag

        if name in _COLORS:
            if close:
                if len(color_stack) > 1:
                    color_stack.pop()
            else:
                color_stack.append(_COLORS[name])
            continue
        if name in _SIZE_SCALE:
            if close:
                if len(size_stack) > 1:
                    size_stack.pop()
            else:
                size_stack.append(_SIZE_SCALE[name])
            continue
        if name == "u":
            underline = not close
            continue
        if name in ("hl", "mark"):
            highlight = not close
            continue
        # Unknown tag: emit as literal so users can see & fix it.
        emit(m.group())

    emit(text[pos:])
    return [r for r in runs if r.text]


# ---------- engine ----------
class MarqueeEngine:
    """Unlimited-capacity Niconico-style overlay.

    No hard lane cap; overflow just overlaps gracefully.
    """

    def __init__(self, base_font: QFont) -> None:
        self.base_font = QFont(base_font)
        self.tracks: list[Track] = []
        self._metrics_cache: dict[tuple, QFontMetricsF] = {}

    # --- measurement ---
    def _font_at(self, scale: float) -> QFont:
        f = QFont(self.base_font)
        f.setPixelSize(max(8, int(self.base_font.pixelSize() * scale)))
        return f

    def _metrics(self, font: QFont) -> QFontMetricsF:
        key = (font.family(), font.pixelSize(), font.weight())
        fm = self._metrics_cache.get(key)
        if fm is None:
            fm = QFontMetricsF(font)
            self._metrics_cache[key] = fm
        return fm

    def _lay_out(self, runs: list[Run]) -> tuple[list[_LaidRun], float, float, float]:
        laid: list[_LaidRun] = []
        total = 0.0
        max_asc = 0.0
        max_desc = 0.0
        for r in runs:
            f = self._font_at(r.size_scale)
            fm = self._metrics(f)
            w = fm.horizontalAdvance(r.text)
            asc, desc = fm.ascent(), fm.descent()
            laid.append(_LaidRun(
                text=r.text, color=r.color, size_scale=r.size_scale,
                underline=r.underline, highlight=r.highlight,
                width=w, ascent=asc, descent=desc,
            ))
            total += w
            if asc  > max_asc:  max_asc  = asc
            if desc > max_desc: max_desc = desc
        return laid, total, max_asc, max_desc

    # --- lane geometry (dynamic based on area height) ---
    def _lane_height(self) -> float:
        return max(24.0, self.base_font.pixelSize() * 1.15)

    def _n_lanes(self, area_h: float) -> int:
        return max(4, int(area_h // self._lane_height()))

    # --- lane selection for scroll tracks ---
    def _pick_scroll_lane(self, n_lanes: int, area_w: float) -> int:
        """Return the lane with the most right-edge clearance.

        If every lane has a track whose right edge is still on-screen, we
        pick the one with the largest clearance — which happens to be
        whichever lane had its track farthest along in its scroll.
        """
        best_lane = random.randrange(n_lanes)
        best_clearance = -float("inf")
        for lane in range(n_lanes):
            # Find the rightmost "tail" pixel of any scroll track on this lane.
            rightmost_right_edge = -float("inf")
            seen = False
            for t in self.tracks:
                if t.kind != "scroll" or t.lane != lane:
                    continue
                seen = True
                right_edge = t.x + t.total_width
                if right_edge > rightmost_right_edge:
                    rightmost_right_edge = right_edge
            clearance = area_w if not seen else (area_w - rightmost_right_edge)
            if clearance > best_clearance:
                best_clearance = clearance
                best_lane = lane
        return best_lane

    def _pick_pin_lane(self, n_lanes: int, kind: str) -> int:
        """Return the least-occupied top/bottom pin lane.

        For 'top' we count from lane 0 downward; for 'bottom' from the last
        lane upward.  Ties are broken by random, so many concurrent pins
        don't all stack on the same row.
        """
        # Build occupancy for the first/last few lanes
        max_probe = min(n_lanes, 6)
        lane_counts = {}
        for t in self.tracks:
            if t.kind != kind:
                continue
            lane_counts[t.lane] = lane_counts.get(t.lane, 0) + 1
        if kind == "top":
            candidates = list(range(max_probe))
        else:
            candidates = list(range(n_lanes - 1, n_lanes - 1 - max_probe, -1))
        # Pick the candidate with the fewest current pins (random among ties).
        best_count = min(lane_counts.get(l, 0) for l in candidates)
        picks = [l for l in candidates if lane_counts.get(l, 0) == best_count]
        return random.choice(picks)

    # --- public API ---
    def add(self, text: str, area_w: float, area_h: float, speed: int) -> str:
        if not text.strip():
            return "EMPTY"
        kind, body = _detect_position_and_strip(text)
        runs = _parse_runs(body)
        if not runs:
            return "EMPTY"
        laid, total_w, asc, desc = self._lay_out(runs)
        n_lanes = self._n_lanes(area_h)

        speed = max(1, min(5, int(speed)))

        if kind == "scroll":
            lane = self._pick_scroll_lane(n_lanes, area_w)
            duration_s = SCROLL_BASE_TIME_S / speed
            px_per_s = (area_w + total_w + 40) / duration_s
            self.tracks.append(Track(
                kind="scroll",
                runs=laid, total_width=total_w, max_ascent=asc, max_descent=desc,
                lane=lane, x=area_w + 20, speed=speed, px_per_s=px_per_s,
            ))
        else:  # 'top' or 'bottom'
            lane = self._pick_pin_lane(n_lanes, kind)
            self.tracks.append(Track(
                kind=kind,
                runs=laid, total_width=total_w, max_ascent=asc, max_descent=desc,
                lane=lane, lifetime_s=PIN_DURATION_S,
            ))
        return "OK"

    def step(self, dt_ms: float) -> None:
        dt = dt_ms / 1000.0
        for t in self.tracks:
            if t.kind == "scroll":
                t.x -= t.px_per_s * dt
                if t.x + t.total_width < -40:
                    t.finished = True
            else:
                t.lifetime_s -= dt
                if t.lifetime_s <= 0:
                    t.finished = True
        self.tracks = [t for t in self.tracks if not t.finished]

    def stop_all(self) -> None:
        self.tracks.clear()

    def active_count(self) -> int:
        return len(self.tracks)

    # Kept for legacy /status — now reports total tracks, max is 0 (unlimited).
    def lanes_in_use(self) -> int:
        return len(self.tracks)

    def max_lanes(self) -> int:
        return 0   # 0 = unlimited

    # --- drawing ---
    def draw(self, p: QPainter, area: QRectF) -> None:
        if not self.tracks:
            return
        lane_h = self._lane_height()
        n_lanes = self._n_lanes(area.height())

        for t in self.tracks:
            if t.kind == "scroll":
                lane_cy = area.y() + lane_h * (t.lane + 0.5)
                cursor_x = area.x() + t.x
                self._draw_runs(p, t.runs, cursor_x, lane_cy)
            elif t.kind == "top":
                lane_cy = area.y() + lane_h * (t.lane + 0.5)
                cursor_x = area.x() + (area.width() - t.total_width) / 2
                alpha = self._pin_alpha(t.lifetime_s)
                self._draw_runs(p, t.runs, cursor_x, lane_cy, alpha=alpha)
            elif t.kind == "bottom":
                lane_cy = area.y() + area.height() - lane_h * (n_lanes - t.lane - 0.5)
                # clamp so the bottom pin stays on-screen
                if lane_cy < area.y() + lane_h:
                    lane_cy = area.y() + lane_h
                cursor_x = area.x() + (area.width() - t.total_width) / 2
                alpha = self._pin_alpha(t.lifetime_s)
                self._draw_runs(p, t.runs, cursor_x, lane_cy, alpha=alpha)

    def _pin_alpha(self, remaining_s: float) -> float:
        """Fade pinned messages in the last 0.4 s so they don't pop out."""
        if remaining_s > 0.4:
            return 1.0
        return max(0.0, remaining_s / 0.4)

    def _draw_runs(self, p: QPainter, runs: list[_LaidRun],
                   cursor_x: float, lane_cy: float, alpha: float = 1.0) -> None:
        for r in runs:
            f = self._font_at(r.size_scale)
            p.setFont(f)
            baseline_y = lane_cy + r.ascent * 0.5 - r.descent * 0.5
            col = QColor(r.color)
            if alpha < 1.0:
                col.setAlphaF(alpha * col.alphaF())
            if r.highlight:
                top = baseline_y - r.ascent
                h   = r.ascent + r.descent
                hl = QColor(255, 255, 160, int(90 * alpha))
                p.fillRect(QRectF(cursor_x - 4, top - 2, r.width + 8, h + 4), hl)
            p.setPen(col)
            p.drawText(int(cursor_x), int(baseline_y), r.text)
            if r.underline:
                y = baseline_y + max(2, r.descent * 0.5)
                pen = QPen(col, max(2, r.size_scale * 2.5))
                p.setPen(pen)
                p.drawLine(int(cursor_x), int(y),
                           int(cursor_x + r.width), int(y))
            cursor_x += r.width
