"""Particle-based FX scenes rendered through QPainter.

Each Scene has two methods:

* `update(dt_ms: float) -> bool` — advances state, returns True while the
  scene is still alive. Once it returns False, the display can drop it.
* `draw(painter: QPainter, w: int, h: int) -> None` — paints the current
  frame into a (0, 0, w, h) area.

All scenes are resolution-independent (particle sizes/velocities scale with
`min(w, h)`).  They're meant to run at 60 fps on a 1080p+ monitor — Qt's
QPainter routes through the RHI (D3D11) on Windows so it's effectively
hardware-accelerated.
"""
from __future__ import annotations
import math
import random
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui  import QBrush, QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient


def hsv(h: float, s: float, v: float, a: float = 1.0) -> QColor:
    c = QColor.fromHsvF(h % 1.0, max(0.0, min(1.0, s)),
                        max(0.0, min(1.0, v)))
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float      # 0..1 (1 = born, 0 = dead)
    decay: float     # subtracted per second
    size: float
    hue: float
    kind: int = 0    # scene-specific (0 = circle, 1 = star, 2 = heart, 3 = flake, ...)
    rot: float = 0.0
    spin: float = 0.0


class Scene:
    """Base Scene interface — subclasses implement update / draw."""

    duration_ms: float = 2000.0

    def __init__(self, w: int, h: int) -> None:
        self.w = w
        self.h = h
        self.age_ms = 0.0
        self.alive = True

    def update(self, dt_ms: float) -> bool:
        self.age_ms += dt_ms
        if self.age_ms >= self.duration_ms:
            self.alive = False
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        ...


# =====================================================
#  BOMB — pre-flash sparks → white flash → shockwave/fireball → smoke particles
# =====================================================
class BombScene(Scene):
    duration_ms = 2200.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.cx = w / 2.0
        self.cy = h / 2.0
        self.rmax = min(w, h) * 0.45
        self.particles: list[Particle] = []
        self._spawned_smoke = False

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        t = self.age_ms / 1000.0
        # Spawn smoke particles once at the fireball peak (~t = 1.0)
        if not self._spawned_smoke and t >= 1.0:
            self._spawned_smoke = True
            for _ in range(220):
                ang = random.uniform(0, math.tau)
                spd = random.uniform(60, 240)
                self.particles.append(Particle(
                    x=self.cx, y=self.cy,
                    vx=math.cos(ang) * spd,
                    vy=math.sin(ang) * spd - 30,  # slight upward drift
                    life=1.0,
                    decay=random.uniform(0.6, 1.1),
                    size=random.uniform(18, 48),
                    hue=random.uniform(0.02, 0.12),  # orange-to-red smoke tint
                ))
        # Integrate particles
        dt = dt_ms / 1000.0
        for part in self.particles:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.vy += 40 * dt          # slight rise/fall
            part.vx *= 0.985
            part.vy *= 0.985
            part.life -= part.decay * dt
        self.particles = [p for p in self.particles if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        p.fillRect(0, 0, w, h, Qt.GlobalColor.black)
        t = self.age_ms / 1000.0

        # --- Phase 1 (0.00-0.30): converging sparks
        if t < 0.30:
            phase = t / 0.30
            r = self.rmax * (0.90 - 0.80 * phase)
            p.setPen(Qt.PenStyle.NoPen)
            for _ in range(80):
                ang = random.uniform(0, math.tau)
                px = self.cx + math.cos(ang) * r
                py = self.cy + math.sin(ang) * r
                col = hsv(random.uniform(0.08, 0.17), 1.0, 1.0)
                p.setBrush(col)
                p.drawEllipse(QPointF(px, py), 4, 4)

        # --- Phase 2 (0.30-0.45): white strobe
        if 0.30 <= t < 0.45:
            frac = (t - 0.30) / 0.15
            alpha = 1.0 - frac
            p.fillRect(0, 0, w, h, QColor(255, 255, 255, int(alpha * 255)))

        # --- Phase 3 (0.30-1.10): expanding shockwave + fireball
        if 0.30 <= t < 1.10:
            frac = (t - 0.30) / 0.80
            r_core  = self.rmax * 0.28 * frac + 24
            r_glow  = self.rmax * 0.55 * frac + 24
            r_shock = self.rmax * 0.94 * frac + 10

            # Outer glow (radial gradient so edges feather)
            grad = QRadialGradient(QPointF(self.cx, self.cy), r_glow)
            grad.setColorAt(0.0, QColor(255, 220,  80, 230))
            grad.setColorAt(0.5, QColor(255, 100,  20, 180))
            grad.setColorAt(1.0, QColor(120,   0,   0,   0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(self.cx, self.cy), r_glow, r_glow)

            # Core
            core = QRadialGradient(QPointF(self.cx, self.cy), r_core)
            core.setColorAt(0.0, QColor(255, 255, 230, 255))
            core.setColorAt(0.6, QColor(255, 200,  60, 230))
            core.setColorAt(1.0, QColor(255,  60,   0,   0))
            p.setBrush(QBrush(core))
            p.drawEllipse(QPointF(self.cx, self.cy), r_core, r_core)

            # Shockwave rim
            alpha = int(255 * (1.0 - frac))
            p.setPen(QPen(QColor(255, 240, 120, alpha), 5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(self.cx, self.cy), r_shock, r_shock)
            p.setPen(QPen(QColor(255, 120,  40, alpha), 2))
            p.drawEllipse(QPointF(self.cx, self.cy), r_shock + 10, r_shock + 10)

        # --- Phase 4 (1.00+): smoke particles (spawned once in update)
        if t >= 1.0:
            p.setPen(Qt.PenStyle.NoPen)
            for part in self.particles:
                col = hsv(part.hue, 0.3, 0.35, part.life * 0.9)
                p.setBrush(col)
                r = part.size * (0.5 + 0.5 * part.life)
                p.drawEllipse(QPointF(part.x, part.y), r, r)


# =====================================================
#  CHEER — confetti rain + bursting stars + clap sparkles
# =====================================================
class CheerScene(Scene):
    duration_ms = 3200.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.particles: list[Particle] = []
        self.stars: list[Particle] = []
        for _ in range(220):
            self.particles.append(Particle(
                x=random.uniform(0, w),
                y=random.uniform(-h, 0),
                vx=random.uniform(-40, 40),
                vy=random.uniform(140, 320),
                life=1.0,
                decay=random.uniform(0.25, 0.45),
                size=random.uniform(8, 18),
                hue=random.uniform(0, 1),
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-6, 6),
            ))
        # 5 star bursts at random offsets across the first ~1s
        self._burst_schedule = sorted([random.uniform(0.05, 1.0) for _ in range(5)])
        self._burst_idx = 0

    def _spawn_burst(self, w: int, h: int) -> None:
        cx = random.uniform(w * 0.2, w * 0.8)
        cy = random.uniform(h * 0.2, h * 0.7)
        col_hue = random.uniform(0, 1)
        for _ in range(60):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(240, 520)
            self.stars.append(Particle(
                x=cx, y=cy,
                vx=math.cos(ang) * spd,
                vy=math.sin(ang) * spd - 80,
                life=1.0,
                decay=random.uniform(0.9, 1.4),
                size=random.uniform(10, 22),
                hue=(col_hue + random.uniform(-0.08, 0.08)) % 1.0,
                kind=1,
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-8, 8),
            ))

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        t = self.age_ms / 1000.0
        while self._burst_idx < len(self._burst_schedule) and t >= self._burst_schedule[self._burst_idx]:
            self._spawn_burst(self.w, self.h)
            self._burst_idx += 1
        dt = dt_ms / 1000.0
        for part in self.particles:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.vy += 80 * dt
            part.rot += part.spin * dt
            if part.y > self.h + 40:
                # respawn at top for continuous rain
                part.y = random.uniform(-80, 0)
                part.x = random.uniform(0, self.w)
                part.life = 1.0
            # After duration starts fading, let them die
            if self.age_ms > self.duration_ms - 700:
                part.life -= 1.5 * dt
        for part in self.stars:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.vy += 400 * dt
            part.vx *= 0.985
            part.rot += part.spin * dt
            part.life -= part.decay * dt
        self.particles = [p for p in self.particles if p.life > 0]
        self.stars     = [p for p in self.stars     if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        # Subtle warm backdrop
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(46,  20, 70))
        grad.setColorAt(1.0, QColor( 8,   4, 18))
        p.fillRect(0, 0, w, h, QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)

        # Confetti rectangles
        for part in self.particles:
            col = hsv(part.hue, 0.9, 1.0, min(1.0, part.life))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.setBrush(col)
            w2 = part.size
            h2 = part.size * 0.4
            p.drawRect(QRectF(-w2 / 2, -h2 / 2, w2, h2))
            p.restore()

        # Star bursts
        for part in self.stars:
            col = hsv(part.hue, 0.9, 1.0, min(1.0, part.life))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.setBrush(col)
            _draw_star(p, part.size)
            p.restore()


# =====================================================
#  HEARTS — hearts floating up bobbing side to side
# =====================================================
class HeartsScene(Scene):
    duration_ms = 4500.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.hearts: list[Particle] = []
        self._spawn_until = 3000.0
        self._next_spawn = 0.0

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        self._next_spawn -= dt_ms
        while self._next_spawn <= 0 and self.age_ms < self._spawn_until:
            self._next_spawn += random.uniform(40, 90)
            self.hearts.append(Particle(
                x=random.uniform(0, self.w),
                y=self.h + random.uniform(20, 120),
                vx=random.uniform(-30, 30),
                vy=random.uniform(-180, -110),
                life=1.0,
                decay=random.uniform(0.2, 0.35),
                size=random.uniform(32, 72),
                hue=random.uniform(0.93, 1.05) % 1.0,   # pink/red band
                kind=2,
                rot=random.uniform(-0.3, 0.3),
                spin=random.uniform(-1.2, 1.2),
            ))
        dt = dt_ms / 1000.0
        t  = self.age_ms / 1000.0
        for part in self.hearts:
            # sinusoidal side-to-side bob
            part.vx += math.sin((part.y + t * 60) * 0.02) * 20 * dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            part.spin *= 0.99
            part.life -= part.decay * dt
        self.hearts = [p for p in self.hearts if p.life > 0 and p.y > -200]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(70, 10, 30))
        grad.setColorAt(1.0, QColor(20,  2, 10))
        p.fillRect(0, 0, w, h, QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        for part in self.hearts:
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            col = hsv(part.hue, 0.85, 1.0, min(1.0, part.life))
            p.setBrush(col)
            _draw_heart(p, part.size)
            p.restore()


# =====================================================
#  STARS — glittering star shower
# =====================================================
class StarsScene(Scene):
    duration_ms = 3500.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.stars: list[Particle] = []
        self._next_spawn = 0.0

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        self._next_spawn -= dt_ms
        while self._next_spawn <= 0 and self.age_ms < self.duration_ms - 700:
            self._next_spawn += random.uniform(12, 28)
            self.stars.append(Particle(
                x=random.uniform(-40, self.w + 40),
                y=-random.uniform(20, 200),
                vx=random.uniform(-30, 30),
                vy=random.uniform(220, 460),
                life=1.0,
                decay=random.uniform(0.35, 0.6),
                size=random.uniform(18, 42),
                hue=random.uniform(0.12, 0.18),   # yellow band
                kind=1,
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-6, 6),
            ))
        dt = dt_ms / 1000.0
        for part in self.stars:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            part.life -= part.decay * dt
        self.stars = [p for p in self.stars if p.life > 0 and p.y < self.h + 80]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(20, 12, 60))
        grad.setColorAt(1.0, QColor( 4,  4, 20))
        p.fillRect(0, 0, w, h, QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        for part in self.stars:
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            col = hsv(part.hue, 0.85, 1.0, min(1.0, part.life))
            p.setBrush(col)
            _draw_star(p, part.size)
            p.restore()


# =====================================================
#  SNOW — gentle snowflake fall
# =====================================================
class SnowScene(Scene):
    duration_ms = 6000.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.flakes: list[Particle] = []
        for _ in range(280):
            self.flakes.append(Particle(
                x=random.uniform(0, w),
                y=random.uniform(-h, h),
                vx=random.uniform(-18, 18),
                vy=random.uniform(60, 140),
                life=1.0,
                decay=0.0,
                size=random.uniform(6, 16),
                hue=0.58,
                kind=3,
            ))
        self._fade_start = self.duration_ms - 1200

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        t  = self.age_ms / 1000.0
        for part in self.flakes:
            part.vx += math.sin((part.y + t * 30) * 0.015) * 8 * dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            if part.y > self.h + 20:
                part.y = -20
                part.x = random.uniform(0, self.w)
            if self.age_ms > self._fade_start:
                part.life -= 1.0 * dt
        self.flakes = [p for p in self.flakes if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(20,  48, 90))
        grad.setColorAt(1.0, QColor( 2,   8, 24))
        p.fillRect(0, 0, w, h, QBrush(grad))
        p.setPen(Qt.PenStyle.NoPen)
        for part in self.flakes:
            col = QColor(245, 250, 255, int(part.life * 235))
            p.setBrush(col)
            p.drawEllipse(QPointF(part.x, part.y), part.size * 0.4, part.size * 0.4)


# =====================================================
#  Shape helpers (star, heart — drawn at origin/scale=size)
# =====================================================
_STAR_PATH: QPainterPath | None = None
def _star_path() -> QPainterPath:
    global _STAR_PATH
    if _STAR_PATH is not None:
        return _STAR_PATH
    path = QPainterPath()
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        r = 1.0 if i % 2 == 0 else 0.45
        x = math.cos(ang) * r
        y = math.sin(ang) * r
        if i == 0:
            path.moveTo(x, y)
        else:
            path.lineTo(x, y)
    path.closeSubpath()
    _STAR_PATH = path
    return path


def _draw_star(p: QPainter, size: float) -> None:
    p.save()
    p.scale(size, size)
    p.drawPath(_star_path())
    p.restore()


_HEART_PATH: QPainterPath | None = None
def _heart_path() -> QPainterPath:
    global _HEART_PATH
    if _HEART_PATH is not None:
        return _HEART_PATH
    # Classic heart in [-0.5, 0.5] x [-0.5, 0.5] using a cubic curve.
    path = QPainterPath()
    path.moveTo(0.0, 0.30)
    path.cubicTo(0.55, -0.15, 0.55, -0.80, 0.00, -0.30)
    path.cubicTo(-0.55, -0.80, -0.55, -0.15, 0.00,  0.30)
    path.closeSubpath()
    _HEART_PATH = path
    return path


def _draw_heart(p: QPainter, size: float) -> None:
    p.save()
    p.scale(size, size)
    p.drawPath(_heart_path())
    p.restore()


# =====================================================
#  ImageScene — show an uploaded photo as a full-screen letterboxed poster
# =====================================================
class ImageScene(Scene):
    def __init__(self, w: int, h: int, pixmap: QPixmap,
                 caption: str = "", duration_ms: float = 8000.0) -> None:
        super().__init__(w, h)
        self.duration_ms = duration_ms
        self._pix = pixmap
        self._caption = caption

    def draw(self, p: QPainter, w: int, h: int) -> None:
        p.fillRect(0, 0, w, h, Qt.GlobalColor.black)
        if self._pix.isNull():
            return
        pw, ph = self._pix.width(), self._pix.height()
        if pw == 0 or ph == 0:
            return
        # Fit within (w, h) preserving aspect, leaving a tiny margin.
        margin = 8
        avail_w = max(1, w - 2 * margin)
        avail_h = max(1, h - 2 * margin)
        scale = min(avail_w / pw, avail_h / ph)
        dw = int(pw * scale)
        dh = int(ph * scale)
        dx = (w - dw) // 2
        dy = (h - dh) // 2

        # Fade in 0.3 s, fade out last 0.4 s.
        t = self.age_ms / self.duration_ms if self.duration_ms > 0 else 0
        fade_in_end  = 300 / self.duration_ms
        fade_out_start = 1 - (400 / self.duration_ms)
        if t < fade_in_end:
            fade = t / max(1e-6, fade_in_end)
        elif t > fade_out_start:
            fade = max(0.0, (1.0 - t) / max(1e-6, 1.0 - fade_out_start))
        else:
            fade = 1.0

        p.setOpacity(fade)
        p.drawPixmap(QRect(dx, dy, dw, dh), self._pix)
        if self._caption:
            cap_px = max(18, int(h * 0.03))
            f = QFont("Segoe UI Variable Text", 0)
            f.setPixelSize(cap_px)
            f.setBold(True)
            p.setFont(f)
            fm = QFontMetricsF(f)
            tw = fm.horizontalAdvance(self._caption)
            pad = int(cap_px * 0.6)
            tx = (w - tw) // 2
            ty = h - int(cap_px * 1.8)
            # semi-transparent pill under the caption for legibility
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, int(140 * fade)))
            p.drawRoundedRect(QRectF(tx - pad, ty - fm.ascent(),
                                     tw + pad * 2, fm.height() + 6),
                              8, 8)
            p.setPen(QColor(245, 250, 255, int(235 * fade)))
            p.drawText(int(tx), int(ty), self._caption)
        p.setOpacity(1.0)


# =====================================================
#  Scene factory
# =====================================================
def make_scene(name: str, w: int, h: int) -> Scene | None:
    name = name.lower()
    if name == "bomb":   return BombScene(w, h)
    if name == "clap":   return CheerScene(w, h)
    if name == "hearts": return HeartsScene(w, h)
    if name == "stars":  return StarsScene(w, h)
    if name == "snow":   return SnowScene(w, h)
    return None
