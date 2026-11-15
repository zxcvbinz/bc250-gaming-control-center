# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""Disegno dell'HUD in gioco, condiviso da overlay e anteprima nella GUI (qui niente layer-shell).

Tre stili:
  bubble   cerchio con gli FPS che si allarga solo quando qualcosa richiede attenzione
  ring     anello completo: FPS al centro e quattro valori sugli archi intorno, sempre visibili
  compact  una riga sola con le metriche scelte
  full     riquadro con FPS, grafico frametime e metriche
"""
import math
import time

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainterPath, QPen

from . import common
from .i18n import T

P = common.PALETTE

# etichette in italiano come dati: si traducono con T() dove si mostrano
STYLES = [("bubble", "Cerchio intelligente"), ("ring", "Anello completo"), ("compact", "Barra compatta"),
          ("full", "Completo")]
STYLE_NAMES = dict(STYLES)
# cosa può far allargare il cerchio
WATCH = [("cpu_temp", "CPU troppo calda"), ("gpu_temp", "GPU troppo calda"),
         ("fps_drop", "FPS sotto l'obiettivo"), ("stutter", "Scatti (1% low basso)"),
         ("throttling", "Taglio clock GPU"), ("ram", "RAM quasi piena"), ("fan", "Ventola ferma")]
CENTER = [("fps", "FPS"), ("cpu_temp", "Temperatura CPU"), ("gpu_temp", "Temperatura GPU"), ("power", "Consumo")]
# valori attorno all'anello (alto, destra, basso, sinistra)
RING_SLOTS = [("cpu_temp", "Temperatura CPU"), ("gpu_temp", "Temperatura GPU"), ("power", "Consumo"),
              ("gpu_clk", "Clock GPU"), ("gpu_busy", "Carico GPU"), ("cpu_load", "Carico CPU"),
              ("ram", "RAM"), ("vram", "VRAM"), ("fan", "Ventola"), ("low1", "1% low")]
RING_DEFAULT = ["cpu_temp", "gpu_temp", "power", "gpu_clk"]
IDLE = [("visible", "Sempre visibile"), ("faded", "Quasi trasparente"), ("hidden", "Nascosto")]
# secondi in cui una condizione deve durare prima di allargare il cerchio (evita lampi nei caricamenti)
DEBOUNCE = {"fps_drop": 2.0, "stutter": 2.0, "cpu_temp": 1.0, "gpu_temp": 1.0}
IDLE_ALPHA = {"visible": 1.0, "faded": 0.35, "hidden": 0.0}


# ---------------------------------------------------------------- helpers
def qc(hexcol, alpha=255):
    c = QColor(hexcol)
    c.setAlpha(alpha)
    return c


def font(size, bold=False):
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    return f


def temp_col(t, warn=75, bad=85):
    if t is None:
        return P["MUTED"]
    return P["BAD"] if t >= bad else P["WARN"] if t >= warn else P["GOOD"]


def fps_col(fps, limit):
    if not fps:
        return P["MUTED"]
    target = limit or 60
    return P["GOOD"] if fps >= target * 0.9 else P["WARN"] if fps >= target * 0.6 else P["BAD"]


def draw_series(p, rect, values, vmax, color, fill=True, width=1.6, vmin=0.0):
    vals = [v for v in values if v is not None]
    if len(vals) < 2 or vmax <= vmin:
        return
    n = len(values)
    path = QPainterPath()
    started = False
    first_x = x = rect.left()
    for i, v in enumerate(values):
        if v is None:
            continue
        x = rect.left() + rect.width() * i / max(1, n - 1)
        y = rect.bottom() - rect.height() * max(0.0, min(1.0, (v - vmin) / (vmax - vmin)))
        if not started:
            path.moveTo(x, y)
            first_x = x
            started = True
        else:
            path.lineTo(x, y)
    if fill:
        area = QPainterPath(path)
        area.lineTo(x, rect.bottom())
        area.lineTo(first_x, rect.bottom())
        area.closeSubpath()
        p.fillPath(area, qc(color, 40))
    p.setPen(QPen(qc(color), width))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(path)


ITEM_LABELS = {
    "cpu_temp": "CPU", "gpu_temp": "GPU", "gpu_clk": "CLK", "power": "W", "gpu_busy": "GPU%",
    "cpu_load": "CPU%", "fan": "FAN", "ram": "RAM", "vram": "VRAM", "low1": "1%",
    "cpu_clk": "CPU MHz", "ft": "MS",
}

LOOK_DEFAULT = {"labels": True, "border": False, "colors": "status", "accent": "#4fa3ff", "limit_badge": True}
ACCENTS = [("#4fa3ff", "Blu"), ("#3fb950", "Verde"), ("#a371f7", "Viola"), ("#e6edf3", "Bianco"),
           ("#ff7b72", "Corallo"), ("#d29922", "Ambra")]


def look(cfg):
    return {**LOOK_DEFAULT, **(cfg["overlay"].get("look") or {})}


def tint(col, lk, arc=False):
    """Colori «a semaforo» o monocromatici: in mono restano colorati solo avvisi e problemi."""
    if lk["colors"] == "mono" and col not in (P["BAD"], P["WARN"]):
        return lk["accent"] if arc else P["TEXT"]
    return col


def shown_items(o):
    """Valori scelti dall'utente, nell'ordine scelto (FPS e grafico frametime esclusi)."""
    return [i for i in o.get("items", []) if i not in ("fps", "frametime")]


def metric_value(it, s, g):
    def v(k):
        return s.get(k)
    if it == "cpu_temp":
        t = v("cpu_temp")
        return (f"{t:.0f}°" if t else "—"), temp_col(t, 80, 90)
    if it == "gpu_temp":
        t = v("gpu_temp")
        return (f"{t:.0f}°" if t else "—"), temp_col(t, 75, 85)
    if it == "gpu_clk":
        c = v("gpu_clk")
        return (f"{c:.0f}" if c else "—"), P["TEXT"]
    if it == "power":
        w = v("power")
        return (f"{w:.0f}W" if w else "—"), P["TEXT"]
    if it == "gpu_busy":
        b = v("gpu_busy")
        return (f"{b:.0f}%" if b is not None else "—"), P["TEXT"]
    if it == "cpu_load":
        b = v("cpu_load")
        return (f"{b:.0f}%" if b is not None else "—"), P["TEXT"]
    if it == "fan":
        f = v("fan")
        return (f"{f}" if f else "—"), P["TEXT"] if f else P["BAD"]
    if it == "ram":
        r = v("ram") or [None, None]
        return (f"{r[0]:.1f}G" if r[0] else "—"), P["TEXT"]
    if it == "vram":
        r = v("vram") or [None, None]
        return (f"{r[0]:.0f}M" if r[0] else "—"), P["TEXT"]
    if it == "low1":
        return (f"{g['low1']:.0f}" if g.get("low1") else "—"), P["TEXT"]
    if it == "cpu_clk":
        c = v("cpu_mhz")
        return (f"{c:.0f}" if c else "—"), P["TEXT"]
    if it == "ft":
        ft = g.get("frametime")
        return (f"{ft:.1f}" if ft else "—"), P["TEXT"]
    return "—", P["MUTED"]


# ---------------------------------------------------------------- attenzione (stile cerchio)
def fps_target(g, b):
    return g.get("limit") or b.get("fps_min", 40)


def attention(state, cfg):
    """Condizioni che richiedono attenzione adesso: {chiave: colore}, nell'ordine di WATCH."""
    b = cfg["overlay"]["bubble"]
    watch = set(b.get("watch", []))
    g = state.get("game") or {}
    s = state.get("sensors") or {}
    out = {}
    t = s.get("cpu_temp")
    if "cpu_temp" in watch and t and t >= b["cpu_temp"]:
        out["cpu_temp"] = P["BAD"] if t >= b["cpu_temp"] + 5 else P["WARN"]
    t = s.get("gpu_temp")
    if "gpu_temp" in watch and t and t >= b["gpu_temp"]:
        out["gpu_temp"] = P["BAD"] if t >= b["gpu_temp"] + 5 else P["WARN"]
    fps, low = g.get("fps"), g.get("low1")
    if "fps_drop" in watch and fps and fps < fps_target(g, b) * b["fps_drop_pct"] / 100:
        out["fps_drop"] = P["BAD"]
    if "stutter" in watch and fps and fps >= 20 and low and low < fps * b["stutter_pct"] / 100:
        out["stutter"] = P["WARN"]
    if "throttling" in watch and state.get("throttling"):
        out["throttling"] = P["BAD"]
    ram = s.get("ram") or [0, 0]
    if "ram" in watch and ram[1] and 100 * ram[0] / ram[1] >= b["ram_pct"]:
        out["ram"] = P["WARN"]
    fan = s.get("fan")
    if "fan" in watch and fan is not None and fan < cfg["alerts"]["fan_min_rpm"]:
        out["fan"] = P["BAD"]
    # gli avvisi del servizio contano sempre
    amap = {"cpu": "cpu_temp", "gpu": "gpu_temp", "fan": "fan", "ram": "ram"}
    for a in state.get("alerts") or []:
        k = amap.get(a.get("key"))
        if k:
            out[k] = P["BAD"]
    return {k: out[k] for k, _ in WATCH if k in out}


def attention_cell(key, state, cfg):
    """(etichetta, valore) mostrati nel cerchio allargato."""
    g = state.get("game") or {}
    s = state.get("sensors") or {}
    if key == "cpu_temp":
        return "CPU", f"{s['cpu_temp']:.0f}°" if s.get("cpu_temp") else "—"
    if key == "gpu_temp":
        return "GPU", f"{s['gpu_temp']:.0f}°" if s.get("gpu_temp") else "—"
    if key == "fps_drop":
        return T("OBIETTIVO"), f"{fps_target(g, cfg['overlay']['bubble'])}"
    if key == "stutter":
        return "1% LOW", f"{g['low1']:.0f}" if g.get("low1") else "—"
    if key == "throttling":
        return T("CLOCK GPU"), f"{s['gpu_clk']:.0f}" if s.get("gpu_clk") else "—"
    if key == "ram":
        r = s.get("ram") or [0, 0]
        return "RAM", f"{100 * r[0] / r[1]:.0f}%" if r[1] else "—"
    if key == "fan":
        return T("VENTOLA"), f"{s.get('fan') or 0}"
    return key, "—"


def ring_value(key, st, cfg):
    """(etichetta, testo, frazione 0-1 dell'arco, colore) per un valore dell'anello."""
    s = st.get("sensors") or {}
    g = st.get("game") or {}
    b = cfg["overlay"]["bubble"]
    if key in ("cpu_temp", "gpu_temp"):
        t = s.get(key)
        warn = b.get(key, 85) - 8
        col = temp_col(t, warn, b.get(key, 85))
        return ("CPU" if key == "cpu_temp" else "GPU"), (f"{t:.0f}°" if t else "—"), \
            max(0.0, min(1.0, ((t or 30) - 30) / 70)), col
    if key == "power":
        w = s.get("power")
        return "W", (f"{w:.0f}" if w else "—"), min(1.0, (w or 0) / 160), P["PURPLE"]
    if key == "gpu_clk":
        c = s.get("gpu_clk")
        return "MHz", (f"{c:.0f}" if c else "—"), min(1.0, (c or 0) / 2000), \
            P["BAD"] if st.get("throttling") else P["ACCENT"]
    if key in ("gpu_busy", "cpu_load"):
        v = s.get(key)
        return ("GPU%" if key == "gpu_busy" else "CPU%"), (f"{v:.0f}" if v is not None else "—"), \
            min(1.0, (v or 0) / 100), P["ACCENT"]
    if key in ("ram", "vram"):
        r = s.get(key) or [0, 0]
        f = r[0] / r[1] if r[0] and r[1] else 0
        txt = (f"{r[0]:.1f}G" if key == "ram" else f"{r[0]:.0f}M") if r[0] else "—"
        return key.upper(), txt, f, P["WARN"] if f > b.get("ram_pct", 90) / 100 else P["GOOD"]
    if key == "fan":
        f = s.get("fan")
        return "RPM", (f"{f}" if f else "—"), min(1.0, (f or 0) / 2000), P["TEXT"] if f else P["BAD"]
    if key == "low1":
        lo, fps = g.get("low1"), g.get("fps")
        return "1%", (f"{lo:.0f}" if lo else "—"), min(1.0, lo / fps) if lo and fps else 0, \
            P["GOOD"] if lo and fps and lo >= fps * 0.75 else P["WARN"]
    if key == "cpu_clk":
        c = s.get("cpu_mhz")
        return "CPU MHz", (f"{c:.0f}" if c else "—"), min(1.0, (c or 0) / 3500), P["ACCENT"]
    if key == "ft":
        ft, lim = g.get("frametime"), g.get("limit")
        tgt = 1000 / lim if lim else 16.7
        return "MS", (f"{ft:.1f}" if ft else "—"), min(1.0, (ft or 0) / (2 * tgt)), \
            P["GOOD"] if ft and ft <= tgt * 1.15 else P["WARN"]
    return key, "—", 0, P["MUTED"]


def ring_items(o):
    items = shown_items(o)[:8]
    if len(items) < 2:
        items = ((o.get("ring") or {}).get("slots") or RING_DEFAULT)[:4]
    return items


def ring_diameter(o):
    n = len(ring_items(o))
    return 112 if n <= 4 else 136 if n <= 6 else 160


RING_KEYS = {"cpu_temp": ("cpu_temp",), "gpu_temp": ("gpu_temp",), "gpu_clk": ("throttling",),
             "ram": ("ram",), "fan": ("fan",), "low1": ("stutter",)}


# ---------------------------------------------------------------- painter
class HudPainter:
    """Stato e disegno dell'HUD. update() a ogni nuovo stato, step() per le animazioni."""
    D = 56        # diametro cerchio
    DR = 112      # diametro anello completo
    CELL = 70     # larghezza di una voce nel cerchio allargato

    def __init__(self):
        self.seen = {}        # chiave -> ultima volta attiva
        self.since = {}       # chiave -> da quando la condizione è vera (debounce)
        self.colors = {}
        self.keys = []        # voci mostrate (attive o ancora nel tempo di tenuta)
        self.shown = []       # voci disegnate (restano mentre il cerchio si richiude)
        self.active = []      # voci la cui condizione è vera adesso
        self.w_cur = float(self.D)
        self.alpha = 1.0
        self.alpha_target = 1.0
        self.last_step = time.monotonic()

    # ------------------------------------------------ stato
    def update(self, state, cfg, now=None):
        now = time.monotonic() if now is None else now
        o = cfg["overlay"]
        b = o["bubble"]
        raw = attention(state, cfg)
        for k in list(self.since):
            if k not in raw:
                del self.since[k]
        for k, col in raw.items():
            self.since.setdefault(k, now)
            if now - self.since[k] >= DEBOUNCE.get(k, 0):
                self.seen[k] = now
                self.colors[k] = col
        hold = float(b.get("hold_s", 8))
        self.keys = [k for k, _ in WATCH if now - self.seen.get(k, -1e9) < hold]
        self.active = [k for k in self.keys if k in raw]
        if self.keys:
            self.shown = list(self.keys)
        self.alpha_target = 1.0 if self.keys else IDLE_ALPHA.get(b.get("idle", "visible"), 1.0)

    def target_w(self):
        return self.D + (12 + len(self.keys) * self.CELL if self.keys else 0)

    def step(self, dt=None):
        """Avanza le animazioni. Ritorna True se c'è ancora movimento."""
        now = time.monotonic()
        dt = now - self.last_step if dt is None else dt
        self.last_step = now
        k = min(1.0, dt * 10)
        tw = self.target_w()
        self.w_cur += (tw - self.w_cur) * k
        self.alpha += (self.alpha_target - self.alpha) * k
        moving = False
        if abs(tw - self.w_cur) < 0.6:
            self.w_cur = float(tw)
        else:
            moving = True
        if abs(self.alpha_target - self.alpha) < 0.02:
            self.alpha = self.alpha_target
        else:
            moving = True
        if not self.keys and self.w_cur <= self.D:
            self.shown = []
        return moving

    def settle(self):
        """Salta l'animazione (per esempio quando la finestra era nascosta)."""
        self.w_cur = float(self.target_w())
        self.alpha = self.alpha_target

    def visible(self, cfg):
        if cfg["overlay"].get("style", "bubble") not in ("bubble", "ring"):
            return True
        return self.alpha > 0.01 or self.alpha_target > 0

    # ------------------------------------------------ dimensioni (pixel reali, scala inclusa)
    def size(self, state, cfg, expanded=False):
        o = cfg["overlay"]
        sc = float(o["scale"])
        style = o.get("style", "bubble")
        if style == "ring":
            d = ring_diameter(o)
            return int(math.ceil(d * sc)) + 2, int(math.ceil(d * sc)) + 2
        if style == "bubble":
            w = self.D + 12 + len(WATCH) * self.CELL if expanded else self.w_cur
            return int(math.ceil(w * sc)) + 2, int(math.ceil(self.D * sc)) + 2
        if style == "compact":
            w = sum(QFontMetrics(font(f, b)).horizontalAdvance(t) for t, _c, f, b in self.compact_parts(state, o))
            return int((w + 28) * sc), int(30 * sc)
        items = shown_items(o)
        w = int((150 + 64 * max(0, len(items) - 2) if items else 150) * sc)
        w = max(w, int(190 * sc))
        h = int((44 + (34 if "frametime" in o["items"] and o.get("graph", True) else 0)
                 + (26 if items else 0)) * sc)
        return w, h

    # ------------------------------------------------ disegno
    def paint(self, p, state, cfg, W, H):
        """Disegna l'HUD in (0, 0, W, H) del painter, in pixel reali."""
        o = cfg["overlay"]
        sc = float(o["scale"])
        p.save()
        p.setRenderHint(p.RenderHint.Antialiasing)
        p.scale(sc, sc)
        style = o.get("style", "bubble")
        if style == "bubble":
            self.paint_bubble(p, state, cfg, W / sc, H / sc)
        elif style == "ring":
            self.paint_ring(p, state, cfg)
        elif style == "compact":
            self.paint_compact(p, state, o, W / sc, H / sc)
        else:
            self.paint_full(p, state, o, W / sc, H / sc)
        p.restore()

    def paint_bubble(self, p, st, cfg, W, H):
        o = cfg["overlay"]
        b = o["bubble"]
        D = self.D
        g = st.get("game") or {}
        s = st.get("sensors") or {}
        right = o.get("position", "top-left").endswith("right")
        wu = max(D, min(self.w_cur, W - 1))
        x0 = (W - 1 - wu) if right else 1
        p.setOpacity(max(0.0, min(1.0, self.alpha)))
        lk = look(cfg)
        p.setPen(QPen(qc(lk["accent"], 200), 1.5) if lk["border"] else QPen(qc(P["BORDER"], 160), 1))
        p.setBrush(qc(P["BG"], int(255 * float(o["opacity"]))))
        p.drawRoundedRect(QRectF(x0, 1, wu, D - 2), (D - 2) / 2, (D - 2) / 2)
        cx = x0 + wu - D / 2 if right else x0 + D / 2
        cy = D / 2

        # valore al centro
        center = b.get("center", "fps")
        warn = [self.colors[k] for k in self.active]
        alarm = P["BAD"] if P["BAD"] in warn else (P["WARN"] if warn else None)
        if center == "fps":
            fps = g.get("fps")
            tgt = fps_target(g, b)
            frac = min(1.0, (fps or 0) / tgt) if tgt else 0
            col = fps_col(fps, g.get("limit") or 0)
            txt, unit = (f"{fps:.0f}" if fps else "—"), "FPS"
        elif center in ("cpu_temp", "gpu_temp"):
            t = s.get(center)
            frac = max(0.0, min(1.0, ((t or 30) - 30) / 70))
            col = temp_col(t, 75, 85) if center == "gpu_temp" else temp_col(t, 80, 90)
            txt, unit = (f"{t:.0f}°" if t else "—"), "CPU" if center == "cpu_temp" else "GPU"
        else:
            w = s.get("power")
            frac = min(1.0, (w or 0) / 160)
            col, txt, unit = P["PURPLE"], (f"{w:.0f}" if w else "—"), "WATT"
        ring = alarm or col
        rr = QRectF(cx - D / 2 + 5, cy - D / 2 + 5, D - 10, D - 10)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qc(P["OFF"]), 3))
        p.drawEllipse(rr)
        if frac > 0:
            pen = QPen(qc(ring), 3)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rr, 90 * 16, -int(360 * 16 * frac))
        p.setFont(font(12.5 if len(txt) < 4 else 10.5, True))
        p.setPen(qc(col))
        p.drawText(QRectF(cx - D / 2, cy - 14, D, 22), Qt.AlignmentFlag.AlignCenter, txt)
        p.setFont(font(5.5, True))
        p.setPen(qc(P["MUTED"]))
        p.drawText(QRectF(cx - D / 2, cy + 7, D, 10), Qt.AlignmentFlag.AlignCenter, unit)

        # voci che richiedono attenzione, rivelate mentre il cerchio si allarga
        if not self.shown or wu <= D + 1:
            return
        area = QRectF(x0 + 6, 0, wu - D - 6, D) if right else QRectF(x0 + D, 0, wu - D - 6, D)
        p.save()
        p.setClipRect(area)
        for i, k in enumerate(self.shown):
            lab, val = attention_cell(k, st, cfg)
            col = self.colors.get(k, P["TEXT"]) if k in self.active else P["TEXT"]
            if right:
                cell = QRectF(x0 + wu - D - 6 - (i + 1) * self.CELL, 0, self.CELL, D)
            else:
                cell = QRectF(x0 + D + 6 + i * self.CELL, 0, self.CELL, D)
            if i:
                p.setPen(QPen(qc(P["BORDER"]), 1))
                sx = cell.right() if right else cell.left()
                p.drawLine(QPointF(sx, 16), QPointF(sx, D - 16))
            p.setFont(font(6, True))
            p.setPen(qc(P["DIM"]))
            p.drawText(QRectF(cell.left(), 12, cell.width(), 10), Qt.AlignmentFlag.AlignCenter, lab)
            p.setFont(font(11, True))
            p.setPen(qc(col))
            p.drawText(QRectF(cell.left(), 22, cell.width(), 20), Qt.AlignmentFlag.AlignCenter, val)
        p.restore()

    def paint_ring(self, p, st, cfg):
        o = cfg["overlay"]
        lk = look(cfg)
        D = ring_diameter(o)
        R = D / 2
        cx = cy = R + 1
        g = st.get("game") or {}
        p.setOpacity(max(0.0, min(1.0, self.alpha)))
        # alone quando qualcosa richiede attenzione
        alarm = None
        if self.active:
            cols = [self.colors[k] for k in self.active]
            alarm = P["BAD"] if P["BAD"] in cols else P["WARN"]
        if alarm:
            p.setPen(QPen(qc(alarm, 220), 2.5))
        elif lk["border"]:
            p.setPen(QPen(qc(lk["accent"], 200), 1.5))
        else:
            p.setPen(QPen(qc(P["BORDER"], 160), 1))
        p.setBrush(qc(P["BG"], int(255 * float(o["opacity"]))))
        p.drawEllipse(QPointF(cx, cy), R - 1, R - 1)

        items = ring_items(o)
        n = len(items)
        rr = QRectF(cx - R + 8, cy - R + 8, D - 16, D - 16)
        seg = 360 / n
        gap = 14 if n <= 4 else 10
        tr = R * (0.56 if n <= 4 else 0.6)
        for i, key in enumerate(items):
            lab, txt, frac, col = ring_value(key, st, cfg)
            for k in RING_KEYS.get(key, ()):
                if k in self.active:
                    col = self.colors[k]
            mid = 90 - i * seg          # gradi Qt: 0 = destra, antiorario; si parte dall'alto
            span = seg - gap
            start = mid + span / 2
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(qc(P["OFF"]), 4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawArc(rr, int(start * 16), int(-span * 16))
            if frac > 0:
                pen = QPen(qc(tint(col, lk, arc=True)), 4)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawArc(rr, int(start * 16), int(-span * frac * 16))
            ang = math.radians(mid)
            bx, by = cx + tr * math.cos(ang), cy - tr * math.sin(ang)
            box = QRectF(bx - 22, by - 10, 44, 20)
            p.setFont(font(8 if n <= 6 else 7.5, True))
            p.setPen(qc(tint(col, lk)))
            p.drawText(box.adjusted(0, -3 if lk["labels"] else 0, 0, -3 if lk["labels"] else 0),
                       Qt.AlignmentFlag.AlignCenter, txt)
            if lk["labels"]:
                p.setFont(font(4.6, True))
                p.setPen(qc(P["DIM"]))
                p.drawText(QRectF(box.left(), box.bottom() - 6, box.width(), 7), Qt.AlignmentFlag.AlignCenter, lab)
        # centro: limite, FPS, mini grafico frametime
        fps = g.get("fps")
        limit = g.get("limit") or 0
        txt = f"{fps:.0f}" if fps else "—"
        graph = "frametime" in o.get("items", []) and g.get("frametimes")
        dy = -3 if graph else 0
        if lk["limit_badge"] and g:
            p.setFont(font(4.8, True))
            p.setPen(qc(lk["accent"] if limit else P["DIM"]))
            p.drawText(QRectF(cx - 22, cy - 21 + dy, 44, 8), Qt.AlignmentFlag.AlignCenter,
                       f"⏵ {limit}" if limit else "∞")
        p.setFont(font(14 if len(txt) < 4 else 11.5, True))
        fc = P["BAD"] if "fps_drop" in self.active else fps_col(fps, limit)
        p.setPen(qc(tint(fc, lk)))
        p.drawText(QRectF(cx - 22, cy - 13 + dy, 44, 22), Qt.AlignmentFlag.AlignCenter, txt)
        if graph:
            fts = g["frametimes"][-40:]
            tgt = 1000.0 / limit if limit else sum(fts) / len(fts)
            gr = QRectF(cx - 15, cy + 8, 30, 7)
            draw_series(p, gr, fts, max(tgt * 2, max(fts) * 1.1), tint(fc, lk, arc=True), fill=False, width=1)
        elif lk["labels"]:
            p.setFont(font(4.6, True))
            p.setPen(qc(P["MUTED"]))
            p.drawText(QRectF(cx - 22, cy + 7, 44, 8), Qt.AlignmentFlag.AlignCenter, "FPS")

    @staticmethod
    def compact_parts(st, o, lk=None):
        lk = lk or {**LOOK_DEFAULT, **(o.get("look") or {})}
        g = st.get("game") or {}
        s = st.get("sensors") or {}
        fps = g.get("fps")
        parts = [(f"{fps:.0f}" if fps else "—", tint(fps_col(fps, g.get("limit") or 0), lk), 10.5, True),
                 (" FPS", P["MUTED"], 7, True)]
        for it in shown_items(o):
            val, col = metric_value(it, s, g)
            parts.append(("   " + (ITEM_LABELS.get(it, it) + " " if lk["labels"] else ""), P["DIM"], 7, True))
            parts.append((val, tint(col, lk), 9, True))
        return parts

    def paint_compact(self, p, st, o, W, H):
        lk = {**LOOK_DEFAULT, **(o.get("look") or {})}
        p.setPen(QPen(qc(lk["accent"], 200), 1.5) if lk["border"] else Qt.PenStyle.NoPen)
        p.setBrush(qc(P["BG"], int(255 * float(o["opacity"]))))
        p.drawRoundedRect(QRectF(0, 0, W, H), H / 2, H / 2)
        x = 14
        for txt, col, size, bold in self.compact_parts(st, o, lk):
            f = font(size, bold)
            p.setFont(f)
            p.setPen(qc(col))
            w = QFontMetrics(f).horizontalAdvance(txt)
            p.drawText(QRectF(x, 0, w + 2, H), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)
            x += w

    def paint_full(self, p, st, o, W, H):
        lk = {**LOOK_DEFAULT, **(o.get("look") or {})}
        p.setPen(QPen(qc(lk["accent"], 200), 1.5) if lk["border"] else Qt.PenStyle.NoPen)
        p.setBrush(qc(P["BG"], int(255 * float(o["opacity"]))))
        p.drawRoundedRect(QRectF(0, 0, W, H), 10, 10)
        g = st.get("game") or {}
        s = st.get("sensors") or {}
        fps = g.get("fps")
        limit = g.get("limit") or 0
        x, y = 12, 8
        p.setFont(font(20, True))
        p.setPen(qc(tint(fps_col(fps, limit), lk)))
        txt = f"{fps:.0f}" if fps else "—"
        p.drawText(QRectF(x, y, 80, 32), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)
        tw = QFontMetrics(font(20, True)).horizontalAdvance(txt)
        p.setFont(font(7.5, True))
        p.setPen(qc(P["MUTED"]))
        p.drawText(QRectF(x + tw + 5, y + 4, 40, 12), Qt.AlignmentFlag.AlignLeft, "FPS")
        if g and lk["limit_badge"]:
            badge, col = (f"⏵ {limit}", lk["accent"]) if limit else ("∞", P["DIM"])
            p.setFont(font(7.5, True))
            p.setPen(qc(col))
            p.drawText(QRectF(x + tw + 5, y + 17, 50, 12), Qt.AlignmentFlag.AlignLeft, badge)
        p.setFont(font(8.5))
        p.setPen(qc(P["MUTED"]))
        ft = g.get("frametime")
        right = f"{ft:.1f} ms" if ft else ""
        if g.get("low1"):
            right += f"   1% {g['low1']:.0f}"
        p.drawText(QRectF(0, y + 2, W - 12, 28), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, right)
        y += 38
        if "frametime" in o["items"] and o.get("graph", True):
            fts = g.get("frametimes") or []
            r = QRectF(12, y, W - 24, 26)
            p.setPen(QPen(qc(P["BORDER"]), 1))
            p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))
            if fts:
                target = 1000.0 / limit if limit else (sum(fts) / len(fts))
                vmax = max(target * 2.2, max(fts) * 1.1)
                draw_series(p, r, fts, vmax, tint(fps_col(fps, limit), lk, arc=True), fill=True, width=1.3)
            y += 34
        items = shown_items(o)
        if items:
            cw = (W - 24) / len(items)
            for i, it in enumerate(items):
                val, col = metric_value(it, s, g)
                cx = 12 + i * cw
                if lk["labels"]:
                    p.setFont(font(6.5, True))
                    p.setPen(qc(P["DIM"]))
                    p.drawText(QRectF(cx, y - 4, cw, 10), Qt.AlignmentFlag.AlignLeft, ITEM_LABELS.get(it, it))
                p.setFont(font(9, True))
                p.setPen(qc(tint(col, lk)))
                p.drawText(QRectF(cx, y + 5, cw, 14), Qt.AlignmentFlag.AlignLeft, val)


# ---------------------------------------------------------------- dati finti per l'anteprima
DEMOS = [("ok", "Demo: tutto regolare"), ("hot", "Demo: CPU calda"),
         ("drop", "Demo: FPS in calo e scatti"), ("throttle", "Demo: GPU calda, clock tagliato")]


def demo_state(kind, cfg):
    t = time.monotonic()
    limit = 90
    fps = 88.5 + math.sin(t * 1.3) * 1.2
    low = 82
    s = {"cpu_temp": 71, "gpu_temp": 64, "gpu_clk": 1750, "cpu_mhz": 3490, "power": 74, "gpu_busy": 62, "cpu_load": 48,
         "fan": 1085, "ram": [7.9, 14.8], "vram": [410, 512]}
    thr = False
    if kind == "hot":
        s["cpu_temp"] = 91 + math.sin(t) * 1.5
    elif kind == "drop":
        fps, low = 52 + math.sin(t * 2) * 4, 21
    elif kind == "throttle":
        s.update(gpu_temp=86, gpu_clk=1120, power=104)
        fps, low, thr = 63, 55, True
    fts = [1000 / fps + (7 if kind == "drop" and i % 17 == 0 else 0) + math.sin(i * 0.7 + t) * 0.4
           for i in range(120)]
    return {"ts": time.time(), "sensors": s, "throttling": thr, "alerts": [],
            "game": {"name": T("Gioco di prova"), "fps": fps, "low1": low, "frametime": fts[-1],
                     "frametimes": fts, "limit": limit, "api": "Vulkan"}}
