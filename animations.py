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


def _draw_glow(p: QPainter, x: float, y: float, radius: float, color: QColor,
               edge_alpha: float = 0.0) -> None:
    grad = QRadialGradient(QPointF(x, y), max(1.0, radius))
    c0 = QColor(color)
    c1 = QColor(color)
    c0.setAlphaF(max(0.0, min(1.0, color.alphaF())))
    c1.setAlphaF(max(0.0, min(1.0, edge_alpha)))
    grad.setColorAt(0.0, c0)
    grad.setColorAt(1.0, c1)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(grad))
    p.drawEllipse(QPointF(x, y), radius, radius)


def _fill_vignette(p: QPainter, w: int, h: int, alpha: int = 120) -> None:
    edge = QRadialGradient(QPointF(w / 2.0, h / 2.0), max(w, h) * 0.72)
    edge.setColorAt(0.55, QColor(0, 0, 0, 0))
    edge.setColorAt(1.00, QColor(0, 0, 0, alpha))
    p.fillRect(0, 0, w, h, QBrush(edge))


def _draw_twinkle(p: QPainter, x: float, y: float, length: float, color: QColor) -> None:
    """4-point cross-shaped highlight — sells "this thing twinkles"."""
    p.setPen(Qt.PenStyle.NoPen)
    for ang_deg, l in ((0, length), (90, length), (45, length * 0.55), (135, length * 0.55)):
        p.save()
        p.translate(x, y)
        p.rotate(ang_deg)
        path = QPainterPath()
        path.moveTo(-l, 0)
        path.lineTo(0, -l * 0.12)
        path.lineTo(l, 0)
        path.lineTo(0, l * 0.12)
        path.closeSubpath()
        p.setBrush(color)
        p.drawPath(path)
        p.restore()


# =====================================================
#  BOMB — converging sparks → double strobe → multi-rim shockwave + fireball → smoke + ember rain
# =====================================================
class BombScene(Scene):
    duration_ms = 2400.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.cx = w / 2.0
        self.cy = h * 0.52
        self.rmax = min(w, h) * 0.48
        self.smoke: list[Particle] = []
        self.embers: list[Particle] = []
        self._spawned_smoke = False

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        t = self.age_ms / 1000.0
        if not self._spawned_smoke and t >= 1.05:
            self._spawned_smoke = True
            for _ in range(260):
                ang = random.uniform(0, math.tau)
                spd = random.uniform(70, 280)
                self.smoke.append(Particle(
                    x=self.cx, y=self.cy,
                    vx=math.cos(ang) * spd,
                    vy=math.sin(ang) * spd - 70,    # rise
                    life=1.0,
                    decay=random.uniform(0.55, 0.95),
                    size=random.uniform(22, 56),
                    hue=random.uniform(0.02, 0.10),
                ))
            for _ in range(140):
                ang = random.uniform(0, math.tau)
                spd = random.uniform(180, 520)
                self.embers.append(Particle(
                    x=self.cx, y=self.cy,
                    vx=math.cos(ang) * spd,
                    vy=math.sin(ang) * spd - 30,
                    life=1.0,
                    decay=random.uniform(0.9, 1.6),
                    size=random.uniform(2, 5),
                    hue=random.uniform(0.04, 0.13),
                ))
        dt = dt_ms / 1000.0
        for part in self.smoke:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.vy += 28 * dt
            part.vx *= 0.985
            part.vy *= 0.985
            part.life -= part.decay * dt
        self.smoke = [p for p in self.smoke if p.life > 0]
        for part in self.embers:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.vy += 220 * dt        # embers fall fast
            part.vx *= 0.985
            part.life -= part.decay * dt
        self.embers = [p for p in self.embers if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        bg = QRadialGradient(QPointF(self.cx, self.cy), max(w, h) * 0.78)
        bg.setColorAt(0.0, QColor(54, 22, 12))
        bg.setColorAt(0.4, QColor(18, 8, 8))
        bg.setColorAt(1.0, QColor(0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(bg))
        t = self.age_ms / 1000.0

        # --- Phase 1 (0.00-0.30): converging sparks
        if t < 0.30:
            phase = t / 0.30
            r = self.rmax * (0.95 - 0.85 * phase)
            p.setPen(Qt.PenStyle.NoPen)
            for _ in range(96):
                ang = random.uniform(0, math.tau)
                jitter = (1.0 - phase) * random.uniform(-0.12, 0.12) * self.rmax
                px = self.cx + math.cos(ang) * (r + jitter)
                py = self.cy + math.sin(ang) * (r + jitter)
                col = hsv(random.uniform(0.06, 0.18), 1.0, 1.0)
                p.setBrush(col)
                rad = 4 * (1.0 + phase * 1.4)
                p.drawEllipse(QPointF(px, py), rad, rad)

        # --- Phase 2 (0.30-0.50): double-pulse white strobe
        if 0.30 <= t < 0.50:
            frac = (t - 0.30) / 0.20
            pulse = max(0.0, 1.0 - frac) * (0.55 + 0.45 * abs(math.sin(frac * math.pi * 2)))
            p.fillRect(0, 0, w, h, QColor(255, 255, 255, int(pulse * 240)))

        # --- Phase 3 (0.30-1.30): expanding shockwave + fireball
        if 0.30 <= t < 1.30:
            frac = (t - 0.30) / 1.00
            ease = 1.0 - (1.0 - frac) ** 2
            r_core  = self.rmax * 0.30 * ease + 24
            r_glow  = self.rmax * 0.62 * ease + 24
            r_shock = self.rmax * 1.08 * ease + 10

            grad = QRadialGradient(QPointF(self.cx, self.cy), r_glow)
            grad.setColorAt(0.0, QColor(255, 230, 110, 240))
            grad.setColorAt(0.45, QColor(255, 120, 30, 200))
            grad.setColorAt(0.85, QColor(140, 30, 0, 60))
            grad.setColorAt(1.0, QColor(60, 0, 0, 0))
            p.setBrush(QBrush(grad))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(self.cx, self.cy), r_glow, r_glow)

            core = QRadialGradient(QPointF(self.cx, self.cy), r_core)
            core.setColorAt(0.0, QColor(255, 255, 235, 255))
            core.setColorAt(0.4, QColor(255, 220, 110, 240))
            core.setColorAt(0.85, QColor(255, 100, 20, 130))
            core.setColorAt(1.0, QColor(180, 30, 0, 0))
            p.setBrush(QBrush(core))
            p.drawEllipse(QPointF(self.cx, self.cy), r_core, r_core)

            # Three-rim shockwave gives a stronger "boom" feel than a single ring.
            for k, (off, w_pen) in enumerate(((0, 5), (10, 3), (28, 2))):
                rim_r = r_shock + off
                a = int(255 * (1.0 - frac) * (1.0 - k * 0.22))
                if a > 0:
                    p.setPen(QPen(QColor(255, 240, 140, a), w_pen))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QPointF(self.cx, self.cy), rim_r, rim_r)

            # Ember streaks fanning outward — gradient lines so the heads glow hot.
            for i in range(28):
                ang = i * math.tau / 28 + frac * 0.8
                x1 = self.cx + math.cos(ang) * (r_core * 0.5)
                y1 = self.cy + math.sin(ang) * (r_core * 0.5)
                x2 = self.cx + math.cos(ang) * (r_shock + 80 + 50 * frac)
                y2 = self.cy + math.sin(ang) * (r_shock + 80 + 50 * frac)
                a = int(220 * (1.0 - frac))
                if a > 0:
                    grad_line = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
                    grad_line.setColorAt(0.0, QColor(255, 230, 140, a))
                    grad_line.setColorAt(1.0, QColor(255, 110, 40, 0))
                    p.setPen(QPen(QBrush(grad_line), 4))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # --- Phase 4 (1.05+): smoke + falling embers
        p.setPen(Qt.PenStyle.NoPen)
        for part in self.smoke:
            _draw_glow(p, part.x, part.y, part.size * 1.4,
                       QColor(255, 110, 30, int(part.life * 38)))
            col = hsv(part.hue, 0.32, 0.30, part.life * 0.85)
            r = part.size * (0.45 + 0.55 * part.life)
            p.setBrush(col)
            p.drawEllipse(QPointF(part.x, part.y), r, r)
        for part in self.embers:
            col = hsv(part.hue, 1.0, 1.0, part.life)
            _draw_glow(p, part.x, part.y, part.size * 3.0,
                       QColor(255, 180, 60, int(part.life * 80)))
            p.setBrush(col)
            p.drawEllipse(QPointF(part.x, part.y), part.size, part.size)

        # Hot ground reflection just under the blast.
        gg = QLinearGradient(0, h * 0.84, 0, h)
        gg.setColorAt(0.0, QColor(200, 60, 20, 0))
        gg.setColorAt(1.0, QColor(255, 90, 30, 70))
        p.fillRect(QRectF(0, h * 0.84, w, h * 0.16), QBrush(gg))
        _fill_vignette(p, w, h, 175)


# =====================================================
#  CHEER — confetti rain + streamers + bursting stars + spotlight cones
# =====================================================
class CheerScene(Scene):
    duration_ms = 3400.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.particles: list[Particle] = []
        self.stars: list[Particle] = []
        self.streamers: list[dict] = []
        for _ in range(260):
            self.particles.append(Particle(
                x=random.uniform(0, w),
                y=random.uniform(-h, 0),
                vx=random.uniform(-50, 50),
                vy=random.uniform(140, 340),
                life=1.0,
                decay=random.uniform(0.20, 0.40),
                size=random.uniform(8, 20),
                hue=random.uniform(0, 1),
                kind=random.randint(0, 2),    # 0 rect, 1 triangle, 2 circle
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-7, 7),
            ))
        # Streamers (curly ribbons): each falls + curls
        for _ in range(14):
            self.streamers.append({
                "x":  random.uniform(0, w),
                "y":  random.uniform(-h * 0.4, 0),
                "vy": random.uniform(80, 180),
                "phase": random.uniform(0, math.tau),
                "freq": random.uniform(0.012, 0.022),
                "amp": random.uniform(28, 60),
                "len": random.randint(80, 140),
                "hue": random.uniform(0, 1),
                "thickness": random.uniform(2.5, 4.5),
            })
        self._burst_schedule = sorted([random.uniform(0.05, 1.4) for _ in range(6)])
        self._burst_idx = 0

    def _spawn_burst(self, w: int, h: int) -> None:
        cx = random.uniform(w * 0.18, w * 0.82)
        cy = random.uniform(h * 0.18, h * 0.70)
        col_hue = random.uniform(0, 1)
        for _ in range(72):
            ang = random.uniform(0, math.tau)
            spd = random.uniform(260, 560)
            self.stars.append(Particle(
                x=cx, y=cy,
                vx=math.cos(ang) * spd,
                vy=math.sin(ang) * spd - 90,
                life=1.0,
                decay=random.uniform(0.85, 1.4),
                size=random.uniform(11, 24),
                hue=(col_hue + random.uniform(-0.10, 0.10)) % 1.0,
                kind=1,
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-9, 9),
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
                part.y = random.uniform(-100, 0)
                part.x = random.uniform(0, self.w)
                part.life = 1.0
            if self.age_ms > self.duration_ms - 800:
                part.life -= 1.5 * dt
        for part in self.stars:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.vy += 380 * dt
            part.vx *= 0.985
            part.rot += part.spin * dt
            part.life -= part.decay * dt
        for s in self.streamers:
            s["y"] += s["vy"] * dt
            s["phase"] += dt * 1.6
            if s["y"] > self.h + 80:
                s["y"] = random.uniform(-150, -40)
                s["x"] = random.uniform(0, self.w)
                s["hue"] = random.uniform(0, 1)
        self.particles = [p for p in self.particles if p.life > 0]
        self.stars     = [p for p in self.stars     if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(96, 42, 118))
        grad.setColorAt(0.55, QColor(48, 18, 70))
        grad.setColorAt(1.0, QColor(18, 8, 28))
        p.fillRect(0, 0, w, h, QBrush(grad))

        # Stage spotlight cones from top corners.
        for cx, hue in ((w * 0.12, 0.14), (w * 0.88, 0.84)):
            cone = QPainterPath()
            cone.moveTo(cx, -20)
            cone.lineTo(cx - w * 0.34, h)
            cone.lineTo(cx + w * 0.34, h)
            cone.closeSubpath()
            sp_grad = QLinearGradient(QPointF(cx, 0), QPointF(cx, h))
            sp_grad.setColorAt(0.0, hsv(hue, 0.35, 1.0, 0.16))
            sp_grad.setColorAt(1.0, hsv(hue, 0.35, 1.0, 0.0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(sp_grad))
            p.drawPath(cone)

        # Soft golden glow halos near top.
        for sx in (w * 0.18, w * 0.50, w * 0.82):
            _draw_glow(p, sx, h * 0.18, min(w, h) * 0.18, QColor(255, 240, 200, 26))
        p.setPen(Qt.PenStyle.NoPen)

        # Streamers (curly ribbons drawn as wavy paths).
        for s in self.streamers:
            path = QPainterPath()
            x0 = s["x"]; y0 = s["y"]
            path.moveTo(x0, y0)
            for i in range(1, s["len"] + 1):
                yy = y0 - i * 2.4
                xx = x0 + math.sin((yy + s["phase"] * 30) * s["freq"]) * s["amp"]
                path.lineTo(xx, yy)
            col = hsv(s["hue"], 0.85, 1.0, 0.78)
            p.setPen(QPen(col, s["thickness"]))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)

        # Confetti — rectangle / triangle / circle for shape variety.
        for part in self.particles:
            col = hsv(part.hue, 0.9, 1.0, min(1.0, part.life))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.setBrush(col)
            sz = part.size
            if part.kind == 0:
                p.drawRect(QRectF(-sz / 2, -sz * 0.2, sz, sz * 0.4))
            elif part.kind == 1:
                tri = QPainterPath()
                tri.moveTo(0, -sz * 0.55)
                tri.lineTo(sz * 0.5, sz * 0.4)
                tri.lineTo(-sz * 0.5, sz * 0.4)
                tri.closeSubpath()
                p.drawPath(tri)
            else:
                p.drawEllipse(QPointF(0, 0), sz * 0.35, sz * 0.35)
            p.restore()

        # Star bursts.
        for part in self.stars:
            col = hsv(part.hue, 0.9, 1.0, min(1.0, part.life))
            _draw_glow(p, part.x, part.y, part.size * 2.0,
                       QColor(col.red(), col.green(), col.blue(), int(56 * part.life)))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.setBrush(col)
            _draw_star(p, part.size)
            p.restore()
        _fill_vignette(p, w, h, 130)


# =====================================================
#  HEARTS — pulsing hearts rise with sparkle trails over a soft pink mist
# =====================================================
class HeartsScene(Scene):
    duration_ms = 4800.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.hearts: list[Particle] = []
        self.trail: list[Particle] = []
        self._spawn_until = 3300.0
        self._next_spawn = 0.0

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        self._next_spawn -= dt_ms
        while self._next_spawn <= 0 and self.age_ms < self._spawn_until:
            self._next_spawn += random.uniform(36, 80)
            size = random.uniform(28, 84)
            self.hearts.append(Particle(
                x=random.uniform(0, self.w),
                y=self.h + random.uniform(20, 120),
                vx=random.uniform(-30, 30),
                vy=random.uniform(-200, -120),
                life=1.0,
                decay=random.uniform(0.18, 0.32),
                size=size,
                hue=random.uniform(0.93, 1.04) % 1.0,
                kind=2,
                rot=random.uniform(-0.3, 0.3),
                spin=random.uniform(-1.2, 1.2),
            ))
        dt = dt_ms / 1000.0
        t  = self.age_ms / 1000.0
        for part in self.hearts:
            part.vx += math.sin((part.y + t * 60) * 0.02) * 22 * dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            part.spin *= 0.99
            part.life -= part.decay * dt
            # Emit a trail sparkle from larger hearts.
            if part.size > 50 and random.random() < 0.22:
                self.trail.append(Particle(
                    x=part.x + random.uniform(-part.size * 0.25, part.size * 0.25),
                    y=part.y + part.size * 0.3,
                    vx=random.uniform(-12, 12),
                    vy=random.uniform(40, 90),
                    life=1.0,
                    decay=random.uniform(1.2, 1.8),
                    size=random.uniform(4, 9),
                    hue=part.hue,
                ))
        for tr in self.trail:
            tr.x += tr.vx * dt
            tr.y += tr.vy * dt
            tr.life -= tr.decay * dt
        self.hearts = [p for p in self.hearts if p.life > 0 and p.y > -200]
        self.trail  = [p for p in self.trail  if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(108, 24, 56))
        grad.setColorAt(0.55, QColor(70, 14, 40))
        grad.setColorAt(1.0, QColor(36, 6, 18))
        p.fillRect(0, 0, w, h, QBrush(grad))

        # Pink mist along the bottom — adds depth.
        mist = QLinearGradient(0, h * 0.55, 0, h)
        mist.setColorAt(0.0, QColor(255, 170, 195, 0))
        mist.setColorAt(1.0, QColor(255, 170, 195, 60))
        p.fillRect(QRectF(0, h * 0.55, w, h * 0.45), QBrush(mist))

        # Background bokeh hearts (large, very soft).
        for i in range(6):
            x = (i * 247 + self.age_ms * 0.04) % max(1, w * 1.1) - w * 0.05
            y = (i * 173 + self.age_ms * 0.012) % max(1, h)
            _draw_glow(p, x, y, 60 + (i % 3) * 18, QColor(255, 200, 220, 22))

        # Trail sparkles drawn first (behind hearts).
        p.setPen(Qt.PenStyle.NoPen)
        for tr in self.trail:
            col = hsv(tr.hue, 0.45, 1.0, min(1.0, tr.life))
            _draw_glow(p, tr.x, tr.y, tr.size * 1.6,
                       QColor(255, 220, 230, int(40 * tr.life)))
            p.setBrush(col)
            p.drawEllipse(QPointF(tr.x, tr.y), tr.size * 0.4, tr.size * 0.4)

        # Hearts with pulsing glow halo.
        t = self.age_ms / 1000.0
        for part in self.hearts:
            pulse = 1.0 + 0.07 * math.sin(t * 4.0 + part.x * 0.01)
            _draw_glow(p, part.x, part.y, part.size * 1.8 * pulse,
                       QColor(255, 175, 200, int(part.life * 56)))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.scale(pulse, pulse)
            col = hsv(part.hue, 0.85, 1.0, min(1.0, part.life))
            p.setBrush(col)
            _draw_heart(p, part.size)
            # inner highlight (white-pink) for a glossy feel
            hl = QColor(255, 230, 240, int(min(1.0, part.life) * 130))
            p.setBrush(hl)
            p.translate(-part.size * 0.18, -part.size * 0.18)
            _draw_heart(p, part.size * 0.4)
            p.restore()

        # Tiny ambient shimmer.
        for i in range(22):
            x = (i * 91 + self.age_ms * 0.08) % max(1, w)
            y = (i * 57 + self.age_ms * 0.03) % max(1, h)
            _draw_glow(p, x, y, 12 + (i % 4) * 4, QColor(255, 245, 250, 10))
        _fill_vignette(p, w, h, 110)


# =====================================================
#  STARS — shooting stars with long trails, twinkles, and a quiet starfield
# =====================================================
class StarsScene(Scene):
    duration_ms = 3800.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.stars: list[Particle] = []
        self._next_spawn = 0.0
        # quiet background star field — fixed positions, twinkle via age
        self._field = []
        for _ in range(140):
            self._field.append((
                random.uniform(0, w),
                random.uniform(0, h),
                random.uniform(0.6, 2.1),
                random.uniform(0, math.tau),
                random.uniform(2.0, 5.0),
            ))

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        self._next_spawn -= dt_ms
        while self._next_spawn <= 0 and self.age_ms < self.duration_ms - 700:
            self._next_spawn += random.uniform(10, 26)
            wishing = random.random() < 0.10
            self.stars.append(Particle(
                x=random.uniform(-40, self.w + 40),
                y=-random.uniform(20, 200),
                vx=random.uniform(-40, 40),
                vy=random.uniform(220, 480),
                life=1.0,
                decay=random.uniform(0.35, 0.6),
                size=random.uniform(46, 64) if wishing else random.uniform(18, 40),
                hue=random.uniform(0.10, 0.18),
                kind=1 if not wishing else 4,    # 4 = wishing star (extra big + twinkle)
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
        grad.setColorAt(0.0, QColor(28, 18, 86))
        grad.setColorAt(0.55, QColor(14, 10, 50))
        grad.setColorAt(1.0, QColor(4, 4, 22))
        p.fillRect(0, 0, w, h, QBrush(grad))

        # Quiet starfield (twinkles in/out via sin).
        t = self.age_ms / 1000.0
        p.setPen(Qt.PenStyle.NoPen)
        for fx, fy, fr, fphase, ffreq in self._field:
            tw = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * ffreq + fphase))
            col = QColor(255, 245, 200, int(180 * tw))
            _draw_glow(p, fx, fy, fr * 3, QColor(255, 240, 200, int(40 * tw)))
            p.setBrush(col)
            p.drawEllipse(QPointF(fx, fy), fr, fr)

        # Subtle nebula tint near top.
        neb = QRadialGradient(QPointF(w * 0.5, h * 0.2), max(w, h) * 0.55)
        neb.setColorAt(0.0, QColor(80, 60, 180, 28))
        neb.setColorAt(1.0, QColor(20, 10, 50, 0))
        p.fillRect(0, 0, w, h, QBrush(neb))

        # Shooting stars with long trails.
        for part in self.stars:
            tlen = max(40.0, abs(part.vy) * 0.18)
            grad_line = QLinearGradient(
                QPointF(part.x - part.vx * 0.06, part.y - part.vy * 0.06),
                QPointF(part.x, part.y))
            grad_line.setColorAt(0.0, QColor(255, 245, 180, 0))
            grad_line.setColorAt(1.0, QColor(255, 245, 180, int(part.life * 200)))
            p.setPen(QPen(QBrush(grad_line), 3 if part.kind == 1 else 5))
            p.drawLine(QPointF(part.x - part.vx * 0.06, part.y - part.vy * 0.06),
                       QPointF(part.x, part.y))

            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            col = hsv(part.hue, 0.85, 1.0, min(1.0, part.life))
            _draw_glow(p, 0, 0, part.size * (2.6 if part.kind == 4 else 2.0),
                       QColor(col.red(), col.green(), col.blue(), int((68 if part.kind == 4 else 48) * part.life)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            _draw_star(p, part.size)
            # Twinkle cross on the wishing stars.
            if part.kind == 4:
                _draw_twinkle(p, 0, 0, part.size * 1.6,
                              QColor(255, 255, 230, int(180 * part.life)))
            p.restore()
        _fill_vignette(p, w, h, 130)


# =====================================================
#  SNOW — six-pointed flakes drift in three depth layers under moonlight
# =====================================================
class SnowScene(Scene):
    duration_ms = 6200.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.flakes: list[Particle] = []
        # Three depth layers: distant (small/blurry/slow) → near (large/sharp/fast)
        layers = (
            (160, (3.0, 7.0),  (40, 80),   0.55),   # far
            (110, (6.0, 12.0), (70, 130),  0.80),   # mid
            (60,  (12.0, 22.0),(110, 180), 1.00),   # near
        )
        for count, size_r, vy_r, depth in layers:
            for _ in range(count):
                self.flakes.append(Particle(
                    x=random.uniform(0, w),
                    y=random.uniform(-h, h),
                    vx=random.uniform(-22, 22),
                    vy=random.uniform(*vy_r),
                    life=depth,            # reuse `life` as depth/alpha factor
                    decay=0.0,
                    size=random.uniform(*size_r),
                    hue=0.58,
                    kind=3,
                    rot=random.uniform(0, math.tau),
                    spin=random.uniform(-0.6, 0.6),
                ))
        self._fade_start = self.duration_ms - 1200
        self._fade_alpha = 1.0

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        t  = self.age_ms / 1000.0
        for part in self.flakes:
            part.vx += math.sin((part.y + t * 30) * 0.014) * 9 * dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            if part.y > self.h + 24:
                part.y = -24
                part.x = random.uniform(0, self.w)
        if self.age_ms > self._fade_start:
            self._fade_alpha = max(0.0, 1.0 - (self.age_ms - self._fade_start) / 1200.0)
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(46, 92, 138))
        grad.setColorAt(0.55, QColor(20, 44, 80))
        grad.setColorAt(1.0, QColor(8, 18, 40))
        p.fillRect(0, 0, w, h, QBrush(grad))

        # Soft aurora hint up high.
        aur = QLinearGradient(0, 0, 0, h * 0.5)
        aur.setColorAt(0.0, QColor(140, 220, 200, 40))
        aur.setColorAt(0.6, QColor(140, 180, 220, 20))
        aur.setColorAt(1.0, QColor(140, 180, 220, 0))
        p.fillRect(QRectF(0, 0, w, h * 0.5), QBrush(aur))

        # Moonlight glow on right.
        _draw_glow(p, w * 0.78, h * 0.18, min(w, h) * 0.20, QColor(245, 250, 255, 50))
        # Inner moon disk for clarity.
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(250, 252, 255, 220))
        moon_r = min(w, h) * 0.045
        p.drawEllipse(QPointF(w * 0.78, h * 0.18), moon_r, moon_r)
        # subtle moon crater hint
        p.setBrush(QColor(225, 230, 240, 110))
        p.drawEllipse(QPointF(w * 0.78 - moon_r * 0.3, h * 0.18 - moon_r * 0.2),
                      moon_r * 0.18, moon_r * 0.18)
        p.drawEllipse(QPointF(w * 0.78 + moon_r * 0.18, h * 0.18 + moon_r * 0.25),
                      moon_r * 0.12, moon_r * 0.12)

        # Distant-side glow blob.
        _draw_glow(p, w * 0.20, h * 0.25, min(w, h) * 0.18, QColor(230, 240, 255, 22))

        # Snowflakes — depth-sorted: small/dim first, large/sharp on top.
        flakes_sorted = sorted(self.flakes, key=lambda f: f.size)
        for part in flakes_sorted:
            depth = part.life            # 0.55 .. 1.0
            a = self._fade_alpha * depth
            # Outer glow scales with depth.
            _draw_glow(p, part.x, part.y, part.size * 1.1,
                       QColor(255, 255, 255, int(40 * a)))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            line_col = QColor(245, 250, 255, int(235 * a))
            p.setPen(QPen(line_col, max(0.6, part.size * 0.10)))
            _draw_snowflake(p, part.size * 0.45)
            p.restore()
        _fill_vignette(p, w, h, 90)


# =====================================================
#  PETALS — sakura petals drift in three depth layers with bokeh sparkle
# =====================================================
class PetalsScene(Scene):
    duration_ms = 5200.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.petals: list[Particle] = []
        # Three depth layers
        layers = (
            (90,  (6.0, 12.0),  (35, 70),   0.55),
            (80,  (12.0, 22.0), (55, 110),  0.80),
            (50,  (22.0, 38.0), (90, 150),  1.00),
        )
        for count, size_r, vy_r, depth in layers:
            for _ in range(count):
                self.petals.append(Particle(
                    x=random.uniform(0, w),
                    y=random.uniform(-h * 0.2, h),
                    vx=random.uniform(-40, 40),
                    vy=random.uniform(*vy_r),
                    life=depth,
                    decay=random.uniform(0.06, 0.16),
                    size=random.uniform(*size_r),
                    hue=random.uniform(0.92, 0.98),
                    rot=random.uniform(0, math.tau),
                    spin=random.uniform(-3.4, 3.4),
                ))
        self._fade_start = self.duration_ms - 1100

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        t = self.age_ms / 1000.0
        for part in self.petals:
            part.vx += math.sin((part.y * 0.015) + t * 1.8) * 28 * dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            if part.x < -40:
                part.x = self.w + 40
            elif part.x > self.w + 40:
                part.x = -40
            if part.y > self.h + 30:
                part.y = -20
                part.x = random.uniform(0, self.w)
            if self.age_ms > self._fade_start:
                # fade only the alpha multiplier, preserve depth
                pass
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        # Pink-cream sky with sun glow.
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(255, 244, 248))
        grad.setColorAt(0.65, QColor(255, 224, 232))
        grad.setColorAt(1.0, QColor(252, 206, 220))
        p.fillRect(0, 0, w, h, QBrush(grad))

        _draw_glow(p, w * 0.18, h * 0.16, min(w, h) * 0.22, QColor(255, 255, 255, 38))
        _draw_glow(p, w * 0.82, h * 0.18, min(w, h) * 0.16, QColor(255, 230, 240, 32))

        # Cherry blossom branch silhouettes near the top corners.
        p.setPen(QPen(QColor(110, 70, 60, 150), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # Upper-left branch
        path_l = QPainterPath()
        path_l.moveTo(-20, 60)
        path_l.cubicTo(w * 0.15, 30, w * 0.22, 120, w * 0.32, 60)
        p.drawPath(path_l)
        # twigs
        p.setPen(QPen(QColor(110, 70, 60, 130), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for x_frac, dy, dx in ((0.06, 30, 6), (0.13, 50, -10), (0.22, 22, 14), (0.27, 40, -8)):
            p.drawLine(QPointF(w * x_frac, 60 + dy * 0.3),
                       QPointF(w * x_frac + dx, 60 + dy))
        # Upper-right branch
        p.setPen(QPen(QColor(110, 70, 60, 150), 6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        path_r = QPainterPath()
        path_r.moveTo(w + 20, 50)
        path_r.cubicTo(w * 0.85, 22, w * 0.78, 110, w * 0.68, 56)
        p.drawPath(path_r)

        # Bokeh sparkles.
        for i in range(26):
            x = (i * 137 + self.age_ms * 0.05) % max(1, w * 1.05) - w * 0.025
            y = (i * 71 + self.age_ms * 0.03) % max(1, h)
            _draw_glow(p, x, y, 8 + (i % 4) * 4, QColor(255, 255, 255, 22))

        # Petals — depth-sorted (smaller/farther first).
        sorted_petals = sorted(self.petals, key=lambda f: f.size)
        fade_left = max(0.0, 1.0 - max(0.0, self.age_ms - self._fade_start) / 1100.0)
        p.setPen(Qt.PenStyle.NoPen)
        for part in sorted_petals:
            depth = part.life
            alpha = depth * fade_left
            col = hsv(part.hue, 0.30 + 0.10 * depth, 1.0, alpha)
            _draw_glow(p, part.x, part.y, part.size * 1.4,
                       QColor(255, 210, 225, int(34 * alpha)))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.setBrush(col)
            _draw_petal(p, part.size)
            # subtle inner gradient tip — gives the petal volume.
            p.setBrush(QColor(255, 240, 246, int(120 * alpha)))
            p.translate(0, -part.size * 0.35)
            _draw_petal(p, part.size * 0.5)
            p.restore()
        _fill_vignette(p, w, h, 70)


# =====================================================
#  AURORA — luminous color ribbons over stars + mountains, with vertical light pillars
# =====================================================
class AuroraScene(Scene):
    duration_ms = 4900.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.sparkles: list[Particle] = []
        for _ in range(140):
            self.sparkles.append(Particle(
                x=random.uniform(0, w),
                y=random.uniform(0, h * 0.78),
                vx=random.uniform(-8, 8),
                vy=random.uniform(-6, 6),
                life=1.0,
                decay=random.uniform(0.06, 0.14),
                size=random.uniform(4, 11),
                hue=random.uniform(0.42, 0.72),
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-3, 3),
            ))
        # Fixed background star field
        self._stars = []
        for _ in range(100):
            self._stars.append((
                random.uniform(0, w),
                random.uniform(0, h * 0.55),
                random.uniform(0.6, 1.8),
                random.uniform(0, math.tau),
            ))
        # Mountain skyline (deterministic per scene)
        self._skyline = []
        rng = random.Random(42)
        x_pos = -50
        while x_pos < w + 50:
            x_pos += rng.randint(60, 160)
            self._skyline.append((x_pos, h * (0.78 + rng.uniform(-0.08, 0.05))))

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        t = self.age_ms / 1000.0
        for part in self.sparkles:
            part.x += (part.vx + math.sin(t + part.y * 0.01) * 8) * dt
            part.y += (part.vy + math.cos(t * 1.2 + part.x * 0.008) * 6) * dt
            part.rot += part.spin * dt
            if part.x < -10:
                part.x = self.w + 10
            elif part.x > self.w + 10:
                part.x = -10
            if part.y < -10:
                part.y = self.h * 0.78
            elif part.y > self.h * 0.85:
                part.y = 0
            if self.age_ms > self.duration_ms - 900:
                part.life -= part.decay * 2.0 * dt
        self.sparkles = [p for p in self.sparkles if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(4, 14, 30))
        grad.setColorAt(0.55, QColor(2, 8, 20))
        grad.setColorAt(1.0, QColor(0, 4, 12))
        p.fillRect(0, 0, w, h, QBrush(grad))
        time_s = self.age_ms / 1000.0

        # Star field (subtle twinkle).
        p.setPen(Qt.PenStyle.NoPen)
        for sx, sy, sr, sphase in self._stars:
            tw = 0.5 + 0.5 * math.sin(time_s * 2.4 + sphase)
            p.setBrush(QColor(255, 245, 220, int(180 * tw)))
            p.drawEllipse(QPointF(sx, sy), sr, sr)

        # Aurora bands — four layers with blended hues.
        bands = (
            (0.42, 28.0, 0.18, 0.30),
            (0.50, 34.0, 0.30, 0.28),
            (0.62, 28.0, 0.42, 0.22),
            (0.78, 22.0, 0.54, 0.18),
        )
        for band_idx, (base_hue, amp, y_off, alpha) in enumerate(bands):
            path = QPainterPath()
            top = QPainterPath()
            step = max(10, w // 36)
            ys = []
            for x in range(0, w + step, step):
                phase = x * 0.012 + time_s * (1.4 + band_idx * 0.32)
                y = h * y_off + math.sin(phase) * amp + math.cos(phase * 0.55) * (amp * 0.6)
                ys.append((x, y))

            # Filled band (down to floor)
            path.moveTo(0, h)
            for (x, y) in ys:
                path.lineTo(x, y)
            path.lineTo(w, h)
            path.closeSubpath()
            band_grad = QLinearGradient(QPointF(0, h * y_off - amp), QPointF(0, h))
            band_grad.setColorAt(0.0, hsv(base_hue, 0.55, 1.0, alpha))
            band_grad.setColorAt(0.6, hsv(base_hue + 0.08, 0.45, 1.0, alpha * 0.55))
            band_grad.setColorAt(1.0, hsv(base_hue + 0.12, 0.35, 1.0, 0.0))
            p.setBrush(QBrush(band_grad))
            p.drawPath(path)

            # Vertical light pillars rising from the brightest crests.
            for (x, y) in ys[::4]:
                pillar = QLinearGradient(QPointF(x, y), QPointF(x, y - h * 0.22))
                pillar.setColorAt(0.0, hsv(base_hue, 0.4, 1.0, alpha * 0.4))
                pillar.setColorAt(1.0, hsv(base_hue, 0.4, 1.0, 0.0))
                p.setBrush(QBrush(pillar))
                p.drawRect(QRectF(x - 4, y - h * 0.22, 8, h * 0.22))

        # Mountain silhouette.
        sky = QPainterPath()
        sky.moveTo(0, h)
        sky.lineTo(0, h * 0.82)
        for (mx, my) in self._skyline:
            sky.lineTo(mx, my)
        sky.lineTo(w, h * 0.82)
        sky.lineTo(w, h)
        sky.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(2, 8, 18, 230))
        p.drawPath(sky)

        # Faint reflection of aurora on water just above mountains' base (subtle band).
        refl = QLinearGradient(0, h * 0.82, 0, h)
        refl.setColorAt(0.0, QColor(90, 180, 200, 50))
        refl.setColorAt(1.0, QColor(20, 40, 70, 0))
        p.fillRect(QRectF(0, h * 0.82, w, h * 0.18), QBrush(refl))

        # Sparkles.
        for part in self.sparkles:
            alpha = min(1.0, part.life)
            col = hsv(part.hue, 0.32, 1.0, alpha)
            _draw_glow(p, part.x, part.y, part.size * 2.6,
                       QColor(col.red(), col.green(), col.blue(), int(28 * alpha)))
            p.setBrush(col)
            p.drawEllipse(QPointF(part.x, part.y), part.size * 0.35, part.size * 0.35)
        _fill_vignette(p, w, h, 95)


# =====================================================
#  LASER — five stage beams with volumetric haze, lens flares, occasional strobe
# =====================================================
class LaserScene(Scene):
    duration_ms = 2800.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.sparks: list[Particle] = []
        for _ in range(120):
            self.sparks.append(Particle(
                x=random.uniform(0, w),
                y=random.uniform(h * 0.10, h * 0.88),
                vx=random.uniform(-30, 30),
                vy=random.uniform(-14, 14),
                life=1.0,
                decay=random.uniform(0.12, 0.22),
                size=random.uniform(3, 11),
                hue=random.choice((0.0, 0.16, 0.34, 0.52, 0.78, 0.92)),
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-8, 8),
            ))
        # Strobe schedule: a few sharp flashes during the scene
        self._strobes = sorted([random.uniform(0.4, 2.2) for _ in range(4)])

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        for part in self.sparks:
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            if part.x < 0 or part.x > self.w:
                part.vx *= -1
            if part.y < 0 or part.y > self.h:
                part.vy *= -1
            if self.age_ms > self.duration_ms - 700:
                part.life -= part.decay * 2.4 * dt
        self.sparks = [p for p in self.sparks if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(8, 10, 16))
        grad.setColorAt(1.0, QColor(0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(grad))
        time_s = self.age_ms / 1000.0

        # Strobe flash (very brief).
        for s in self._strobes:
            if abs(time_s - s) < 0.04:
                p.fillRect(0, 0, w, h, QColor(255, 255, 255, 120))

        # Atmospheric haze backdrop — soft gradient that pulses with the music.
        haze_alpha = int(30 + 18 * (0.5 + 0.5 * math.sin(time_s * 5.4)))
        haze = QRadialGradient(QPointF(w * 0.5, h * 0.6), max(w, h) * 0.6)
        haze.setColorAt(0.0, QColor(40, 30, 60, haze_alpha))
        haze.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(0, 0, w, h, QBrush(haze))

        # Five beams sweeping in unison.
        origins = (
            (w * 0.10, h * 0.96, 0.0),
            (w * 0.30, h * 0.96, 0.30),
            (w * 0.50, h * 0.96, 0.55),
            (w * 0.70, h * 0.96, 0.75),
            (w * 0.90, h * 0.96, 0.95),
        )
        for idx, (ox, oy, hue) in enumerate(origins):
            sweep = math.sin(time_s * (2.4 + idx * 0.22)) * w * 0.30
            target_x = ox + sweep
            target_y = h * (0.16 + 0.05 * (idx % 2))

            # Volumetric beam — wide translucent quad with gradient.
            beam = QPainterPath()
            beam.moveTo(ox - 22, oy)
            beam.lineTo(ox + 22, oy)
            beam.lineTo(target_x + 16, target_y)
            beam.lineTo(target_x - 16, target_y)
            beam.closeSubpath()
            beam_grad = QLinearGradient(QPointF((ox + target_x) / 2, oy),
                                        QPointF((ox + target_x) / 2, target_y))
            beam_grad.setColorAt(0.0, hsv(hue, 0.7, 1.0, 0.30))
            beam_grad.setColorAt(1.0, hsv(hue, 0.7, 1.0, 0.05))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(beam_grad))
            p.drawPath(beam)

            # Sharp core beam line.
            p.setPen(QPen(hsv(hue, 0.9, 1.0, 0.85), 4))
            p.drawLine(QPointF(ox, oy), QPointF(target_x, target_y))
            p.setPen(QPen(QColor(255, 255, 255, 140), 1.5))
            p.drawLine(QPointF(ox, oy), QPointF(target_x, target_y))

            # Lens flare at origin and target.
            _draw_glow(p, ox, oy, 32, hsv(hue, 0.55, 1.0, 0.75))
            _draw_glow(p, target_x, target_y, 38,
                       QColor(255, 255, 255, 130))
            _draw_glow(p, target_x, target_y, 70, hsv(hue, 0.6, 1.0, 0.35))

        # Floating sparks in the haze.
        for part in self.sparks:
            alpha = min(1.0, part.life)
            col = hsv(part.hue, 0.65, 1.0, alpha)
            _draw_glow(p, part.x, part.y, part.size * 2.4,
                       QColor(col.red(), col.green(), col.blue(), int(36 * alpha)))
            p.setBrush(col)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(part.x, part.y), part.size * 0.28, part.size * 0.28)
        _fill_vignette(p, w, h, 165)


# =====================================================
#  SUNSET (was SUMMER) — golden-hour sea with sun, clouds, gulls, and a sailboat
# =====================================================
class SunsetScene(Scene):
    duration_ms = 5800.0

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.shimmer: list[Particle] = []
        for _ in range(110):
            self.shimmer.append(Particle(
                x=random.uniform(0, w),
                y=random.uniform(h * 0.62, h * 0.94),
                vx=random.uniform(-12, 12),
                vy=random.uniform(-4, 4),
                life=1.0,
                decay=random.uniform(0.08, 0.18),
                size=random.uniform(4, 10),
                hue=random.uniform(0.06, 0.13),
                rot=random.uniform(0, math.tau),
                spin=random.uniform(-2, 2),
            ))
        # Three V-shaped birds, each with its own trajectory.
        self._birds = []
        for i in range(3):
            self._birds.append({
                "x": -120 - i * 110,
                "y": h * (0.18 + i * 0.045),
                "vx": random.uniform(85, 115),
                "phase": random.uniform(0, math.tau),
                "size": random.uniform(14, 22),
            })
        # Cumulus cloud blobs (positions/sizes baked in so they don't shimmer).
        rng = random.Random(7)
        self._clouds = []
        for _ in range(6):
            self._clouds.append((
                rng.uniform(0, w),
                rng.uniform(h * 0.05, h * 0.40),
                rng.uniform(min(w, h) * 0.10, min(w, h) * 0.22),
                rng.uniform(0.6, 1.0),
            ))

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        t = self.age_ms / 1000.0
        for part in self.shimmer:
            part.x += (part.vx + math.sin(t * 2.0 + part.y * 0.02) * 14) * dt
            part.y += (part.vy + math.cos(t * 1.4 + part.x * 0.012) * 4) * dt
            if part.x < -12:
                part.x = self.w + 12
            elif part.x > self.w + 12:
                part.x = -12
            if part.y < self.h * 0.62:
                part.y = self.h * 0.94
            elif part.y > self.h * 0.94:
                part.y = self.h * 0.62
            if self.age_ms > self.duration_ms - 900:
                part.life -= part.decay * 2.0 * dt
        for b in self._birds:
            b["x"] += b["vx"] * dt
            b["phase"] += dt * 4.5
            if b["x"] > self.w + 80:
                b["x"] = -80
        self.shimmer = [p for p in self.shimmer if p.life > 0]
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        sea_y = h * 0.62
        time_s = self.age_ms / 1000.0

        # Sky gradient — saturated golden hour.
        sky = QLinearGradient(0, 0, 0, sea_y)
        sky.setColorAt(0.0, QColor(38, 88, 156))
        sky.setColorAt(0.30, QColor(108, 156, 200))
        sky.setColorAt(0.55, QColor(244, 168, 120))
        sky.setColorAt(0.85, QColor(228, 100, 76))
        sky.setColorAt(1.0, QColor(162, 50, 60))
        p.fillRect(0, 0, w, int(sea_y), QBrush(sky))

        # Sea gradient.
        sea = QLinearGradient(0, sea_y, 0, h)
        sea.setColorAt(0.0, QColor(40, 96, 144))
        sea.setColorAt(0.4, QColor(20, 58, 100))
        sea.setColorAt(1.0, QColor(8, 18, 42))
        p.fillRect(0, int(sea_y), w, h - int(sea_y), QBrush(sea))

        # Clouds — backlit translucent cumulus.
        p.setPen(Qt.PenStyle.NoPen)
        for cx, cy, cr, depth in self._clouds:
            c0 = QColor(255, 200, 160, int(60 * depth))
            c1 = QColor(255, 200, 160, 0)
            grad = QRadialGradient(QPointF(cx, cy), cr)
            grad.setColorAt(0.0, c0)
            grad.setColorAt(1.0, c1)
            p.setBrush(QBrush(grad))
            # multi-blob cloud
            for off in ((0, 0, 1.0), (-cr * 0.55, cr * 0.15, 0.7), (cr * 0.5, cr * 0.1, 0.65), (-cr * 0.2, -cr * 0.18, 0.55)):
                ox, oy, sc = off
                grad2 = QRadialGradient(QPointF(cx + ox, cy + oy), cr * sc)
                grad2.setColorAt(0.0, QColor(255, 200, 160, int(70 * depth * sc)))
                grad2.setColorAt(1.0, QColor(255, 200, 160, 0))
                p.setBrush(QBrush(grad2))
                p.drawEllipse(QPointF(cx + ox, cy + oy), cr * sc, cr * sc)

        # Sun.
        sun_x = w * 0.5
        sun_y = sea_y - h * 0.10
        sun_r = min(w, h) * 0.13
        # outer halo
        _draw_glow(p, sun_x, sun_y, sun_r * 2.2, QColor(255, 220, 150, 70))
        _draw_glow(p, sun_x, sun_y, sun_r * 1.4, QColor(255, 170, 110, 110))
        # rays — radial soft beams
        ray_grad = QRadialGradient(QPointF(sun_x, sun_y), sun_r * 5.0)
        ray_grad.setColorAt(0.0, QColor(255, 220, 150, 50))
        ray_grad.setColorAt(0.5, QColor(255, 180, 120, 18))
        ray_grad.setColorAt(1.0, QColor(255, 120, 80, 0))
        p.fillRect(QRectF(sun_x - sun_r * 5.0, 0, sun_r * 10.0, sea_y),
                   QBrush(ray_grad))
        # sun disk
        sun_disk = QRadialGradient(QPointF(sun_x, sun_y), sun_r)
        sun_disk.setColorAt(0.0, QColor(255, 250, 210))
        sun_disk.setColorAt(0.7, QColor(255, 215, 140))
        sun_disk.setColorAt(1.0, QColor(255, 180, 110))
        p.setBrush(QBrush(sun_disk))
        p.drawEllipse(QPointF(sun_x, sun_y), sun_r, sun_r)

        # Reflection shaft on the water — modulated by shimmer.
        shaft_w = sun_r * 1.4
        for i in range(28):
            t_i = i / 28
            y = sea_y + t_i * (h - sea_y)
            jitter = math.sin(time_s * 4.0 + i * 0.6) * (4 + i * 0.5)
            band_w = shaft_w * (1.0 + t_i * 1.4) + jitter
            alpha = max(0, int(140 * (1.0 - t_i)))
            p.setPen(QPen(QColor(255, 215, 150, alpha), 2 + (i % 3)))
            p.drawLine(QPointF(sun_x - band_w / 2, y),
                       QPointF(sun_x + band_w / 2, y))

        # Animated wave highlights across the sea.
        for idx in range(13):
            y = sea_y + idx * (h - sea_y) / 12
            wave = math.sin(time_s * 1.8 + idx * 0.55) * 18
            p.setPen(QPen(QColor(255, 255, 255, max(0, 30 - idx * 2)),
                          max(1.0, 4.0 - idx * 0.25)))
            p.drawLine(QPointF(0, y + wave), QPointF(w, y - wave * 0.35))

        # Sailboat silhouette to the right of the sun.
        boat_x = w * 0.66
        boat_y = sea_y + h * 0.04
        boat_size = min(w, h) * 0.045
        boat = QPainterPath()
        boat.moveTo(boat_x - boat_size, boat_y)
        boat.lineTo(boat_x + boat_size, boat_y)
        boat.lineTo(boat_x + boat_size * 0.5, boat_y + boat_size * 0.3)
        boat.lineTo(boat_x - boat_size * 0.5, boat_y + boat_size * 0.3)
        boat.closeSubpath()
        p.setBrush(QColor(20, 14, 30, 240))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(boat)
        # mast
        p.setPen(QPen(QColor(20, 14, 30, 240), 2))
        p.drawLine(QPointF(boat_x, boat_y),
                   QPointF(boat_x, boat_y - boat_size * 1.4))
        # sail
        sail = QPainterPath()
        sail.moveTo(boat_x, boat_y - boat_size * 1.4)
        sail.lineTo(boat_x, boat_y)
        sail.lineTo(boat_x + boat_size * 0.85, boat_y)
        sail.closeSubpath()
        p.setBrush(QColor(20, 14, 30, 230))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(sail)

        # Birds (V silhouettes).
        for b in self._birds:
            wing_amp = math.sin(b["phase"]) * 0.4 + 0.6
            sz = b["size"]
            bx = b["x"]; by = b["y"]
            p.setPen(QPen(QColor(20, 14, 30, 220), 2.5,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(bx - sz, by + sz * 0.2),
                       QPointF(bx, by - sz * 0.2 * wing_amp))
            p.drawLine(QPointF(bx, by - sz * 0.2 * wing_amp),
                       QPointF(bx + sz, by + sz * 0.2))

        # Shimmer sparkles on water.
        p.setPen(Qt.PenStyle.NoPen)
        for part in self.shimmer:
            alpha = min(1.0, part.life)
            col = hsv(part.hue, 0.42, 1.0, alpha)
            _draw_glow(p, part.x, part.y, part.size * 2.4,
                       QColor(col.red(), col.green(), col.blue(), int(28 * alpha)))
            p.setBrush(col)
            p.drawEllipse(QPointF(part.x, part.y), part.size * 0.34, part.size * 0.34)

        _fill_vignette(p, w, h, 100)


# =====================================================
#  LEAVES (was AUTUMN) — maple leaves cascade past tree silhouettes with light rays
# =====================================================
class LeavesScene(Scene):
    duration_ms = 5400.0

    # Five autumn-foliage hues (HSV-friendly H values).
    _LEAF_HUES = (0.005, 0.04, 0.075, 0.10, 0.13)

    def __init__(self, w: int, h: int) -> None:
        super().__init__(w, h)
        self.leaves: list[Particle] = []
        # Three depth layers
        layers = (
            (60,  (8, 14),  (40, 80),   0.50),
            (80,  (14, 22), (60, 110),  0.75),
            (50,  (22, 36), (95, 160),  1.00),
        )
        for count, size_r, vy_r, depth in layers:
            for _ in range(count):
                self.leaves.append(Particle(
                    x=random.uniform(0, w),
                    y=random.uniform(-h * 0.25, h),
                    vx=random.uniform(-58, 44),
                    vy=random.uniform(*vy_r),
                    life=depth,
                    decay=random.uniform(0.06, 0.16),
                    size=random.uniform(*size_r),
                    hue=random.choice(self._LEAF_HUES),
                    rot=random.uniform(0, math.tau),
                    spin=random.uniform(-5, 5),
                ))
        # Leaf accumulation pile at the bottom (positions baked).
        rng = random.Random(11)
        self._pile = []
        for _ in range(60):
            self._pile.append((
                rng.uniform(-20, w + 20),
                h - rng.uniform(0, h * 0.04),
                rng.uniform(8, 18),
                rng.uniform(0, math.tau),
                rng.choice(self._LEAF_HUES),
            ))
        self._fade_start = self.duration_ms - 1000

    def update(self, dt_ms: float) -> bool:
        super().update(dt_ms)
        dt = dt_ms / 1000.0
        t = self.age_ms / 1000.0
        for part in self.leaves:
            part.vx += math.sin(t * 1.7 + part.y * 0.02) * 26 * dt
            part.x += part.vx * dt
            part.y += part.vy * dt
            part.rot += part.spin * dt
            if part.x < -32:
                part.x = self.w + 32
            elif part.x > self.w + 32:
                part.x = -32
            if part.y > self.h + 24:
                part.y = -18
                part.x = random.uniform(0, self.w)
        return self.alive

    def draw(self, p: QPainter, w: int, h: int) -> None:
        # Warm autumn sky.
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(252, 232, 200))
        grad.setColorAt(0.40, QColor(232, 175, 118))
        grad.setColorAt(0.78, QColor(168, 92, 58))
        grad.setColorAt(1.0, QColor(80, 40, 28))
        p.fillRect(0, 0, w, h, QBrush(grad))

        # Soft warm sun glow upper-right.
        _draw_glow(p, w * 0.78, h * 0.20, min(w, h) * 0.26, QColor(255, 232, 180, 80))
        _draw_glow(p, w * 0.18, h * 0.14, min(w, h) * 0.20, QColor(255, 220, 168, 50))

        # Sun rays from upper right (translucent diagonal stripes).
        time_s = self.age_ms / 1000.0
        for i in range(8):
            ang = -math.pi / 3 + i * 0.05
            x0, y0 = w * 0.78, h * 0.20
            x1 = x0 + math.cos(ang) * w * 1.2
            y1 = y0 + math.sin(ang) * w * 1.2
            grad_ray = QLinearGradient(QPointF(x0, y0), QPointF(x1, y1))
            alpha_ray = int(28 + 10 * math.sin(time_s * 0.8 + i))
            grad_ray.setColorAt(0.0, QColor(255, 240, 200, alpha_ray))
            grad_ray.setColorAt(1.0, QColor(255, 240, 200, 0))
            p.setPen(QPen(QBrush(grad_ray), 22))
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

        # Distant hills.
        hill = QPainterPath()
        hill.moveTo(0, h)
        hill.lineTo(0, h * 0.78)
        hill.cubicTo(w * 0.18, h * 0.68, w * 0.42, h * 0.86, w * 0.58, h * 0.76)
        hill.cubicTo(w * 0.74, h * 0.70, w * 0.88, h * 0.82, w, h * 0.74)
        hill.lineTo(w, h)
        hill.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(70, 38, 26, 130))
        p.drawPath(hill)

        # Tree silhouettes left & right (simple branching).
        def _draw_tree(cx: float, base_y: float, height: float) -> None:
            p.setPen(QPen(QColor(38, 22, 14, 230), 4,
                          Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            # trunk
            p.drawLine(QPointF(cx, base_y), QPointF(cx, base_y - height))
            # branches
            for level in range(4):
                ly = base_y - height * (0.4 + level * 0.18)
                spread = height * (0.35 - level * 0.06)
                p.setPen(QPen(QColor(38, 22, 14, 220), max(1.5, 4 - level * 0.7),
                              Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                p.drawLine(QPointF(cx, ly), QPointF(cx - spread, ly - height * 0.08))
                p.drawLine(QPointF(cx, ly), QPointF(cx + spread, ly - height * 0.08))
        _draw_tree(w * 0.08, h * 0.92, h * 0.55)
        _draw_tree(w * 0.94, h * 0.95, h * 0.50)

        # Leaf pile on the ground (drawn before falling leaves so falling layer is on top).
        for px, py, sz, prot, phue in self._pile:
            col = hsv(phue, 0.7, 0.92, 0.92)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.save()
            p.translate(px, py)
            p.rotate(math.degrees(prot))
            _draw_maple(p, sz)
            p.restore()

        # Falling leaves — depth-sorted.
        for part in sorted(self.leaves, key=lambda f: f.size):
            depth = part.life
            alpha = depth
            col = hsv(part.hue, 0.78, 1.0, alpha)
            _draw_glow(p, part.x, part.y, part.size * 1.6,
                       QColor(col.red(), col.green(), col.blue(), int(26 * alpha)))
            p.save()
            p.translate(part.x, part.y)
            p.rotate(math.degrees(part.rot))
            p.setBrush(col)
            _draw_maple(p, part.size)
            # darker spine for shape
            p.setPen(QPen(QColor(80, 36, 14, int(180 * alpha)), 0.08))
            p.drawLine(QPointF(0, -0.9 * part.size),
                       QPointF(0, 0.7 * part.size))
            p.setPen(Qt.PenStyle.NoPen)
            p.restore()

        _fill_vignette(p, w, h, 95)


# =====================================================
#  Shape helpers
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


_PETAL_PATH: QPainterPath | None = None
def _petal_path() -> QPainterPath:
    global _PETAL_PATH
    if _PETAL_PATH is not None:
        return _PETAL_PATH
    # Cherry-blossom-ish petal: rounded oval with a soft notch at the base.
    path = QPainterPath()
    path.moveTo(0.0, -1.0)
    path.cubicTo(0.85, -0.55, 0.78, 0.40, 0.10, 0.95)
    path.cubicTo(0.06, 0.78, -0.06, 0.78, -0.10, 0.95)
    path.cubicTo(-0.78, 0.40, -0.85, -0.55, 0.0, -1.0)
    path.closeSubpath()
    _PETAL_PATH = path
    return path


def _draw_petal(p: QPainter, size: float) -> None:
    p.save()
    p.scale(size * 0.55, size)
    p.drawPath(_petal_path())
    p.restore()


_MAPLE_PATH: QPainterPath | None = None
def _maple_path() -> QPainterPath:
    """Leaf silhouette — petal-like teardrop with rounded side notches.

    Built as: an elongated cherry-blossom-style oval, then four circular
    notches subtracted (two per side) so the edge takes on a lobed, leafy
    feel rather than a smooth petal.
    """
    global _MAPLE_PATH
    if _MAPLE_PATH is not None:
        return _MAPLE_PATH
    # Base teardrop: pointed tip up, broader middle, gentle taper to base point.
    base = QPainterPath()
    base.moveTo(0.0, -1.0)
    base.cubicTo(0.55, -0.78, 0.92, -0.20, 0.78,  0.20)
    base.cubicTo(0.65,  0.55, 0.30,  0.86, 0.0,   1.0)
    base.cubicTo(-0.30, 0.86, -0.65, 0.55, -0.78, 0.20)
    base.cubicTo(-0.92, -0.20, -0.55, -0.78, 0.0, -1.0)
    base.closeSubpath()
    # Four rounded notches — two per side at different heights — for a leaf look.
    def _circle(cx: float, cy: float, r: float) -> QPainterPath:
        c = QPainterPath()
        c.addEllipse(QPointF(cx, cy), r, r)
        return c
    leaf = base.subtracted(_circle( 0.95, -0.35, 0.32))
    leaf = leaf.subtracted(_circle(-0.95, -0.35, 0.32))
    leaf = leaf.subtracted(_circle( 0.78,  0.32, 0.26))
    leaf = leaf.subtracted(_circle(-0.78,  0.32, 0.26))
    _MAPLE_PATH = leaf
    return leaf


def _draw_maple(p: QPainter, size: float) -> None:
    p.save()
    # Slight horizontal squeeze so the leaf is taller-than-wide (real leaves are).
    p.scale(size * 0.85, size)
    p.drawPath(_maple_path())
    p.restore()


def _draw_snowflake(p: QPainter, size: float) -> None:
    """Six-arm snowflake with side branches near the tips. `size` ≈ arm length."""
    p.save()
    for i in range(6):
        ang = i * math.pi / 3
        x = math.cos(ang) * size
        y = math.sin(ang) * size
        p.drawLine(QPointF(0, 0), QPointF(x, y))
        # two side branches at ~0.55 along the arm
        bx = math.cos(ang) * size * 0.55
        by = math.sin(ang) * size * 0.55
        for sign in (1, -1):
            ang_b = ang + sign * math.pi / 4
            ex = bx + math.cos(ang_b) * size * 0.28
            ey = by + math.sin(ang_b) * size * 0.28
            p.drawLine(QPointF(bx, by), QPointF(ex, ey))
        # small inner hexagon nub
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
        margin = 8
        avail_w = max(1, w - 2 * margin)
        avail_h = max(1, h - 2 * margin)
        scale = min(avail_w / pw, avail_h / ph)
        dw = int(pw * scale)
        dh = int(ph * scale)
        dx = (w - dw) // 2
        dy = (h - dh) // 2

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
    if name == "petals": return PetalsScene(w, h)
    if name == "aurora": return AuroraScene(w, h)
    if name == "laser":  return LaserScene(w, h)
    if name == "sunset": return SunsetScene(w, h)
    if name == "leaves": return LeavesScene(w, h)
    return None
