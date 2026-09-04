"""COMMENT mode — chat-style feed that scrolls *upward*.

Companion to marquee.py.  Where the marquee flies text right→left in
Niconico lanes, the CommentFeed keeps a *buffer* of lines anchored to
the bottom of the screen: a new line appears at the bottom and pushes
the older ones up (animated), the oldest fall off the top.  This is the
canvas the おわくさ AI writes to in COMMENT mode ("AI による自動コメント
応答"): viewer comment → AI reply pairs, answers to questions, or any
text the operator / AI wants to leave on screen.

Each entry is `who` + `text`.  `text` accepts the same colour / size /
decoration markup as the marquee (<r> <big> <u> ...), so an AI reply can
be styled; position tags (<ue> <shita>) are stripped — position is the
feed's business.

Sizing follows the marquee convention: the feed shares the marquee base
font (config marquee_size) and has its own global percentage
(config comment_size_pct, 50..500, operator-tunable and AI-settable).
Unlike the marquee, changing the size does NOT wipe the buffer — the
entries keep their source text and are simply re-wrapped.
"""
from __future__ import annotations
import math
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui  import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen

from marquee import Run, _detect_position_and_strip, _parse_runs


# Colour of the `who` prefix per entry kind.
#   viewer : a Pococha viewer's comment (the trigger)
#   ai     : おわくさ's reply
#   text   : plain line (operator test input, AI free text)
#   info   : system notice (mode switched, etc.)
_WHO_COLORS = {
    "viewer": QColor(120, 235, 235),
    "ai":     QColor(255, 230,  90),
    "text":   QColor(255, 255, 255),
    "info":   QColor(180, 180, 200),
}
_TEXT_COLORS = {
    "viewer": QColor(235, 235, 235),
    "ai":     QColor(255, 255, 255),
    "text":   QColor(255, 255, 255),
    "info":   QColor(200, 200, 215),
}

FADE_IN_S  = 0.25
FADE_OUT_S = 0.6


@dataclass
class _Seg:
    text: str
    color: QColor
    size_scale: float
    underline: bool
    highlight: bool
    bold: bool
    width: float = 0.0
    ascent: float = 0.0
    descent: float = 0.0


@dataclass
class _Line:
    segs: list[_Seg]
    width: float
    ascent: float
    descent: float

    @property
    def height(self) -> float:
        return self.ascent + self.descent


@dataclass
class Entry:
    kind: str
    who: str
    text: str
    runs: list[Run]
    born: float = field(default_factory=time.monotonic)
    stamp: str = field(default_factory=lambda: time.strftime("%H:%M"))
    # Layout cache (valid for `layout_key`).
    layout_key: tuple = ()
    lines: list[_Line] = field(default_factory=list)
    height: float = 0.0
    # Lifecycle
    ttl_s: float = 0.0            # 0 = until pushed off the top
    fading_out: float = -1.0      # >=0: seconds left in the fade-out
    finished: bool = False

    def alpha(self, now: float) -> float:
        a = min(1.0, (now - self.born) / FADE_IN_S) if FADE_IN_S > 0 else 1.0
        if self.fading_out >= 0:
            a *= max(0.0, self.fading_out / FADE_OUT_S)
        return a


class CommentFeed:
    """Bottom-anchored, upward-scrolling text buffer."""

    def __init__(self, base_font: QFont) -> None:
        self.base_font = QFont(base_font)
        self.entries: list[Entry] = []
        # --- tunables (config comment_*; see pocoboard.py) ---
        self.scale: float = 1.0          # comment_size_pct / 100
        self.max_entries: int = 12       # comment_max_lines
        self.ttl_s: float = 0.0          # comment_ttl_sec (0 = never)
        self.width_frac: float = 0.92    # comment_width_pct
        self.bottom_frac: float = 0.04   # comment_bottom_pct
        self.height_frac: float = 0.90   # comment_height_pct (max stack height)
        self.bg_alpha: float = 0.45      # comment_bg_pct
        self.scroll_ms: float = 350.0    # comment_scroll_ms
        self.show_time: bool = False     # comment_show_time
        # Animation: pixels the stack still has to travel upward.
        self._offset: float = 0.0
        self._font_cache: dict[tuple[float, bool], QFont] = {}
        self._metrics_cache: dict[tuple, QFontMetricsF] = {}
        self._layout_gen: int = 0        # bumps whenever fonts change → relayout

    # ---------- configuration ----------
    def set_scale(self, scale: float) -> None:
        new = max(0.1, float(scale))
        if abs(new - self.scale) < 1e-3:
            return
        self.scale = new
        self._font_cache.clear()
        self._layout_gen += 1

    def set_max_entries(self, n: int) -> None:
        self.max_entries = max(1, int(n))
        self._trim()

    def set_ttl(self, sec: float) -> None:
        self.ttl_s = max(0.0, float(sec))
        for e in self.entries:
            e.ttl_s = self.ttl_s

    # ---------- buffer ops ----------
    def add(self, text: str, who: str = "", kind: str = "text",
            area_w: float | None = None) -> str:
        """Append one entry.  With `area_w` the entry is laid out at once
        and the stack is nudged so the older lines glide upward."""
        text = (text or "").strip()
        if not text and not who:
            return "EMPTY"
        _, body = _detect_position_and_strip(text)
        runs = _parse_runs(body) if body.strip() else []
        if not runs and not who:
            return "EMPTY"
        kind = kind if kind in _WHO_COLORS else "text"
        e = Entry(kind=kind, who=(who or "").strip(), text=body, runs=runs,
                  ttl_s=self.ttl_s)
        self.entries.append(e)
        self._trim()
        if area_w is not None:
            self._layout(e, self._max_width(area_w))
            self._offset += e.height + self._entry_gap()
        return "OK"

    def clear(self) -> None:
        self.entries.clear()
        self._offset = 0.0

    def count(self) -> int:
        return len(self.entries)

    def _trim(self) -> None:
        if len(self.entries) > self.max_entries:
            del self.entries[: len(self.entries) - self.max_entries]

    # ---------- fonts / metrics ----------
    def _font_at(self, size_scale: float, bold: bool) -> QFont:
        key = (size_scale, bold)
        f = self._font_cache.get(key)
        if f is None:
            f = QFont(self.base_font)
            f.setPixelSize(max(8, int(self.base_font.pixelSize() * size_scale * self.scale)))
            f.setBold(bold)
            self._font_cache[key] = f
        return f

    def _metrics(self, font: QFont) -> QFontMetricsF:
        key = (font.family(), font.pixelSize(), font.weight())
        fm = self._metrics_cache.get(key)
        if fm is None:
            fm = QFontMetricsF(font)
            self._metrics_cache[key] = fm
        return fm

    def _line_gap(self) -> float:
        return max(2.0, self.base_font.pixelSize() * self.scale * 0.18)

    def _pad(self) -> float:
        return max(4.0, self.base_font.pixelSize() * self.scale * 0.22)

    # ---------- layout (word/char wrap) ----------
    def _segments(self, e: Entry) -> list[_Seg]:
        segs: list[_Seg] = []
        if e.who:
            prefix = e.who
            if self.show_time:
                prefix = e.stamp + " " + prefix
            segs.append(_Seg(text=prefix + "  ", color=QColor(_WHO_COLORS[e.kind]),
                             size_scale=1.0, underline=False, highlight=False, bold=True))
        default_col = _TEXT_COLORS[e.kind]
        for r in e.runs:
            col = r.color
            # _parse_runs defaults to white; recolour the default so the
            # kind palette shows, but keep explicit <r>/<g>... choices.
            if col == QColor(255, 255, 255):
                col = QColor(default_col)
            segs.append(_Seg(text=r.text, color=QColor(col), size_scale=r.size_scale,
                             underline=r.underline, highlight=r.highlight, bold=False))
        return segs

    def _layout(self, e: Entry, max_w: float) -> None:
        key = (round(max_w), self._layout_gen, self.show_time)
        if e.layout_key == key:
            return
        lines: list[_Line] = []
        cur: list[_Seg] = []
        cur_w = 0.0

        def flush() -> None:
            nonlocal cur, cur_w
            if not cur:
                return
            asc = max(s.ascent for s in cur)
            desc = max(s.descent for s in cur)
            lines.append(_Line(segs=cur, width=cur_w, ascent=asc, descent=desc))
            cur, cur_w = [], 0.0

        for seg in self._segments(e):
            f = self._font_at(seg.size_scale, seg.bold)
            fm = self._metrics(f)
            asc, desc = fm.ascent(), fm.descent()
            text = seg.text
            i = 0
            n = len(text)
            while i < n:
                if text[i] == "\n":
                    flush()
                    i += 1
                    continue
                avail = max_w - cur_w
                # First char does not fit on a non-empty line → wrap first.
                if cur and fm.horizontalAdvance(text[i]) > avail:
                    flush()
                    continue
                # Greedy: take as many characters as fit.  Prefer breaking
                # after a space / punctuation for Latin runs; CJK breaks
                # anywhere.
                j = i
                acc = 0.0
                last_break = -1
                while j < n:
                    ch = text[j]
                    if ch == "\n":
                        break
                    cw = fm.horizontalAdvance(ch)
                    if acc + cw > avail and j > i:
                        break
                    acc += cw
                    j += 1
                    if ch in " 、。,.!?！？　":
                        last_break = j
                wrapped = j < n and text[j] != "\n"
                if wrapped and last_break > i and not _is_cjk(text[j]):
                    j = last_break
                piece = text[i:j]
                i = j
                if piece:
                    w = fm.horizontalAdvance(piece)
                    cur.append(_Seg(text=piece, color=seg.color, size_scale=seg.size_scale,
                                    underline=seg.underline, highlight=seg.highlight,
                                    bold=seg.bold, width=w, ascent=asc, descent=desc))
                    cur_w += w
                if wrapped:
                    flush()
        flush()
        if not lines:
            f = self._font_at(1.0, False)
            fm = self._metrics(f)
            lines.append(_Line(segs=[], width=0.0, ascent=fm.ascent(), descent=fm.descent()))
        gap = self._line_gap()
        e.lines = lines
        e.height = sum(l.height for l in lines) + gap * (len(lines) - 1) + self._pad() * 2
        e.layout_key = key

    # ---------- animation ----------
    def _entry_gap(self) -> float:
        return max(3.0, self.base_font.pixelSize() * self.scale * 0.12)

    def _max_width(self, area_w: float) -> float:
        return max(40.0, area_w * self.width_frac - self._pad() * 2)

    @property
    def animating(self) -> bool:
        if self._offset > 0.0:
            return True
        now = time.monotonic()
        for e in self.entries:
            if now - e.born < FADE_IN_S or e.fading_out >= 0:
                return True
        return False

    def step(self, dt_ms: float) -> bool:
        """Advance animations; returns True while anything is moving."""
        dt = dt_ms / 1000.0
        if self._offset > 0.0:
            tau = max(0.02, self.scroll_ms / 1000.0 / 3.0)
            self._offset *= math.exp(-dt / tau)
            if self._offset < 0.5:
                self._offset = 0.0
        now = time.monotonic()
        changed = False
        for e in self.entries:
            if e.fading_out >= 0:
                e.fading_out -= dt
                if e.fading_out <= 0:
                    e.finished = True
            elif e.ttl_s > 0 and now - e.born >= e.ttl_s:
                e.fading_out = FADE_OUT_S
        if any(e.finished for e in self.entries):
            self.entries = [e for e in self.entries if not e.finished]
            changed = True
        return self.animating or changed

    # ---------- drawing ----------
    def draw(self, p: QPainter, area: QRectF) -> None:
        if not self.entries:
            return
        max_w = self._max_width(area.width())
        gap = self._entry_gap()
        pad = self._pad()
        now = time.monotonic()
        x0 = area.x() + (area.width() - area.width() * self.width_frac) / 2
        bottom = area.y() + area.height() * (1.0 - self.bottom_frac) + self._offset
        top_limit = area.y() + area.height() * (1.0 - self.height_frac)

        # Lay out newest→oldest from the bottom up.
        y = bottom
        drop_before = -1
        for idx in range(len(self.entries) - 1, -1, -1):
            e = self.entries[idx]
            self._layout(e, max_w)
            y_top = y - e.height
            if y_top < top_limit - e.height:
                # Fully above the visible band → this and everything older goes.
                drop_before = idx
                break
            alpha = e.alpha(now)
            # Fade entries that poke above the band so the top edge is soft.
            if y_top < top_limit:
                alpha *= max(0.0, 1.0 - (top_limit - y_top) / max(1.0, e.height))
            if alpha > 0.01:
                self._draw_entry(p, e, x0, y_top, pad, alpha)
            y = y_top - gap
        if drop_before >= 0:
            del self.entries[: drop_before + 1]

    def _draw_entry(self, p: QPainter, e: Entry, x0: float, y_top: float,
                    pad: float, alpha: float) -> None:
        gap = self._line_gap()
        # Translucent backing plate for legibility over camera / video.
        widest = max((l.width for l in e.lines), default=0.0)
        if self.bg_alpha > 0.005 and widest > 0:
            bg = QColor(0, 0, 0, int(255 * self.bg_alpha * alpha))
            r = QRectF(x0, y_top, widest + pad * 2, e.height)
            path = QPainterPath()
            path.addRoundedRect(r, pad * 0.8, pad * 0.8)
            p.fillPath(path, bg)
        y = y_top + pad
        for line in e.lines:
            baseline = y + line.ascent
            cx = x0 + pad
            for s in line.segs:
                f = self._font_at(s.size_scale, s.bold)
                p.setFont(f)
                col = QColor(s.color)
                col.setAlphaF(col.alphaF() * alpha)
                if s.highlight:
                    hl = QColor(255, 255, 160, int(90 * alpha))
                    p.fillRect(QRectF(cx - 2, baseline - s.ascent - 1,
                                      s.width + 4, s.ascent + s.descent + 2), hl)
                # Soft shadow so white text survives a bright camera frame.
                sh = QColor(0, 0, 0, int(170 * alpha))
                p.setPen(sh)
                off = max(1.0, f.pixelSize() * 0.04)
                p.drawText(int(cx + off), int(baseline + off), s.text)
                p.setPen(col)
                p.drawText(int(cx), int(baseline), s.text)
                if s.underline:
                    uy = baseline + max(2, s.descent * 0.5)
                    p.setPen(QPen(col, max(2, s.size_scale * 2.5)))
                    p.drawLine(int(cx), int(uy), int(cx + s.width), int(uy))
                cx += s.width
            y += line.height + gap


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (0x3000 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF)
