"""BC-250 Control Center — interfaccia principale."""
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque

from PyQt6.QtCore import QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QFrame,
                             QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                             QSlider, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from . import common, health
from .engine import write_control
from .install import FLATPAK_GL_APPS, flatpak_gl, flatpak_gl_enabled
from .sensors import Sensors, governor_set

P = common.PALETTE
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

STYLE = f"""
QWidget {{ background:{P['BG']}; color:{P['TEXT']}; font-size:10pt; }}
QLabel {{ background:transparent; }}
QFrame#card {{ background:{P['CARD']}; border:1px solid {P['BORDER']}; border-radius:12px; }}
QListWidget#nav {{ background:{P['SIDEBAR']}; border:none; border-right:1px solid {P['BORDER']};
    padding:10px 8px; outline:0; }}
QListWidget#nav::item {{ padding:9px 12px; border-radius:8px; margin:2px 0; color:{P['MUTED']}; }}
QListWidget#nav::item:selected {{ background:{P['CARD2']}; color:{P['TEXT']}; }}
QListWidget#nav::item:hover:!selected {{ background:{P['CARD']}; }}
QPushButton {{ background:{P['CARD2']}; border:1px solid {P['BORDER']}; border-radius:8px;
    padding:6px 14px; color:{P['TEXT']}; }}
QPushButton:hover {{ border-color:{P['ACCENT']}; }}
QPushButton#primary {{ background:{P['ACCENT']}; border:none; color:#fff; font-weight:bold; }}
QPushButton#danger {{ color:{P['BAD']}; }}
QComboBox, QSpinBox, QLineEdit {{ background:{P['BG']}; border:1px solid {P['BORDER']}; border-radius:7px;
    padding:4px 8px; min-height:22px; }}
QComboBox QAbstractItemView {{ background:{P['CARD']}; selection-background-color:{P['ACCENT']}; }}
QCheckBox {{ spacing:10px; background:transparent; }}
QCheckBox::indicator {{ width:34px; height:18px; image:url({ASSETS}/switch-off.svg); }}
QCheckBox::indicator:checked {{ image:url({ASSETS}/switch-on.svg); }}
QSlider::groove:horizontal {{ height:4px; background:{P['OFF']}; border-radius:2px; }}
QSlider::handle:horizontal {{ width:14px; margin:-5px 0; border-radius:7px; background:{P['ACCENT']}; }}
QTableWidget {{ background:{P['CARD']}; border:none; gridline-color:{P['BORDER']}; }}
QHeaderView::section {{ background:{P['CARD2']}; color:{P['MUTED']}; border:none; padding:6px; }}
QTableWidget::item:selected {{ background:{P['CARD2']}; color:{P['TEXT']}; }}
QScrollArea {{ border:none; }}
QScrollBar:vertical {{ background:transparent; width:8px; }}
QScrollBar::handle:vertical {{ background:{P['OFF']}; border-radius:4px; min-height:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; }}
"""


# ---------------------------------------------------------------- piccoli componenti
def label(text="", size=10, color=None, bold=False, wrap=False):
    l = QLabel(text)
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or P['TEXT']}; font-size:{size}pt; font-weight:{'bold' if bold else 'normal'};")
    l.setWordWrap(wrap)
    l.setTextFormat(Qt.TextFormat.RichText)
    return l


class Card(QFrame):
    def __init__(self, title=None, subtitle=None):
        super().__init__()
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 12, 16, 14)
        self.lay.setSpacing(8)
        if title:
            t = label(title.upper(), 8.5, P["MUTED"], True)
            t.setStyleSheet(f"color:{P['MUTED']}; letter-spacing:1px;")
            self.lay.addWidget(t)
        if subtitle:
            self.lay.addWidget(label(subtitle, 9, P["DIM"], wrap=True))


def row(text, widget, hint=None):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 2, 0, 2)
    v = QVBoxLayout()
    v.setSpacing(0)
    v.addWidget(label(text, 10))
    if hint:
        v.addWidget(label(hint, 8.5, P["DIM"], wrap=True))
    h.addLayout(v, 1)
    h.addWidget(widget, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return w


def page(title, subtitle=None):
    """Pagina scorrevole con titolo. Ritorna (widget, layout)."""
    outer = QScrollArea()
    outer.setWidgetResizable(True)
    inner = QWidget()
    lay = QVBoxLayout(inner)
    lay.setContentsMargins(26, 22, 26, 22)
    lay.setSpacing(14)
    lay.addWidget(label(title, 17, bold=True))
    if subtitle:
        lay.addWidget(label(subtitle, 9.5, P["MUTED"], wrap=True))
    outer.setWidget(inner)
    return outer, lay


def temp_color(t, warn=75, bad=85):
    if t is None:
        return P["MUTED"]
    return P["BAD"] if t >= bad else P["WARN"] if t >= warn else P["GOOD"]


class Tile(QWidget):
    """Valore grande + etichetta + sparkline."""

    def __init__(self, name, unit, vmax, warn=None, bad=None):
        super().__init__()
        self.name, self.unit, self.vmax, self.warn, self.bad = name, unit, vmax, warn, bad
        self.value, self.hist = None, deque(maxlen=90)
        self.setMinimumHeight(78)

    def set(self, v):
        self.value = v
        if v is not None:
            self.hist.append(v)
        self.update()

    def color(self):
        v = self.value
        if v is None or self.warn is None:
            return QColor(P["ACCENT"])
        return QColor(P["BAD"] if v >= self.bad else P["WARN"] if v >= self.warn else P["GOOD"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        col = self.color()
        if len(self.hist) > 1:
            path = QPainterPath()
            n = self.hist.maxlen
            for i, v in enumerate(self.hist):
                x = w * (i + n - len(self.hist)) / (n - 1)
                y = h - 3 - (h * 0.5) * min(1.0, max(0.0, v / self.vmax))
                path.moveTo(x, y) if i == 0 else path.lineTo(x, y)
            c = QColor(col)
            c.setAlpha(140)
            p.setPen(QPen(c, 1.6))
            p.drawPath(path)
        f = QFont()
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(P["MUTED"]))
        p.drawText(0, 13, self.name)
        f.setPointSizeF(19)
        f.setBold(True)
        p.setFont(f)
        p.setPen(col)
        v = self.value
        txt = "—" if v is None else (f"{v:.0f}" if abs(v) >= 10 or self.unit in ("rpm", "MHz") else f"{v:.1f}")
        p.drawText(0, 44, txt + ("" if v is None else " " + self.unit))
        p.end()


class CoreBars(QWidget):
    def __init__(self):
        super().__init__()
        self.topo, self.threads, self.freq = {}, {}, {}
        self.setMinimumHeight(8 * 26 + 4)

    def set(self, topo, threads, freq):
        self.topo, self.threads, self.freq = topo, threads, freq
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        f = QFont()
        f.setPointSizeF(9)
        p.setFont(f)
        cores = list(self.topo.values())
        bar_x, bar_w = 60, w - 60 - 120
        for c in range(8):
            y = c * 26 + 2
            th = cores[c] if c < len(cores) else []
            on = bool(th)
            p.setPen(QColor(P["TEXT"] if on else P["DIM"]))
            p.drawText(0, y + 15, f"Core {c}")
            for i in range(2):
                r = QRectF(bar_x, y + 2 + i * 10, bar_w, 7)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(P["OFF"]))
                p.drawRoundedRect(r, 3, 3)
                if on and i < len(th):
                    u = self.threads.get(str(th[i]), self.threads.get(th[i], 0))
                    p.setBrush(QColor(P["BAD"] if u > 90 else P["WARN"] if u > 70 else P["ACCENT"]))
                    p.drawRoundedRect(QRectF(bar_x, y + 2 + i * 10, max(2, bar_w * u / 100), 7), 3, 3)
            p.setPen(QColor(P["MUTED"] if on else P["DIM"]))
            if on:
                fr = max((self.freq.get(str(t), self.freq.get(t, 0)) for t in th), default=0)
                u = max((self.threads.get(str(t), self.threads.get(t, 0)) for t in th), default=0)
                p.drawText(int(bar_x + bar_w + 10), y + 15, f"{fr / 1000:.2f} GHz  {u:3.0f}%")
            else:
                p.drawText(int(bar_x + bar_w + 10), y + 15, "bloccato")
        p.end()


class CuGrid(QWidget):
    """40 CU: 2 SE × 2 SA × 5 WGP × 2 CU."""

    def __init__(self):
        super().__init__()
        self.wgp_mask = self.inactive = None
        self.setMinimumHeight(130)

    def set(self, wgp_mask, inactive):
        self.wgp_mask, self.inactive = wgp_mask, inactive
        self.update()

    def active_wgp(self, i):
        if self.wgp_mask is None:
            return i < 3
        return (self.wgp_mask >> i) & 1 and not (self.inactive is not None and (self.inactive >> i) & 1)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        f = QFont()
        f.setPointSizeF(8.5)
        p.setFont(f)
        cell, gap = 15, 4
        for row_i in range(4):
            y = row_i * (cell + 11) + 2
            p.setPen(QColor(P["MUTED"]))
            p.drawText(0, y + 12, f"SE{row_i // 2}·SA{row_i % 2}")
            for wgp in range(5):
                on = self.active_wgp(wgp)
                for cu in range(2):
                    x = 56 + wgp * (2 * cell + 3 * gap) + cu * (cell + gap)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(P["GOOD"] if on else P["OFF"]))
                    p.drawRoundedRect(QRectF(x, y, cell, cell), 3, 3)
        p.end()


class CuInfo:
    """Legge maschera CU (umr, sudo -n) in un thread: lento e privilegiato."""

    def __init__(self):
        self.data = {}
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _run(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
        except Exception:
            return ""

    def _loop(self):
        while True:
            out = self._run(["sudo", "-n", "umr", "--instance", "1", "-r", "*.*.mmSPI_PG_ENABLE_STATIC_WGP_MASK"])
            m = re.search(r"=>\s*0x([0-9a-fA-F]+)", out)
            self.data["wgp_mask"] = int(m.group(1), 16) & 0x1F if m else None
            out = self._run(["sudo", "-n", "umr", "--instance", "1", "-r", "*.*.mmCC_GC_SHADER_ARRAY_CONFIG"])
            m = re.search(r"mmCC_GC_SHADER_ARRAY_CONFIG\s*=>\s*0x([0-9a-fA-F]+)", out)
            self.data["cc_inactive"] = (int(m.group(1), 16) >> 16) & 0x1F if m else None
            time.sleep(15)


class Chart(QWidget):
    """Grafico a più serie con assi, per lo storico."""

    def __init__(self):
        super().__init__()
        self.series = []  # (nome, valori, colore, vmax)
        self.marks = []   # (indice, testo)
        self.setMinimumHeight(170)

    def set(self, series, marks=()):
        self.series, self.marks = series, list(marks)
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(36, 22, self.width() - 46, self.height() - 34)
        p.setPen(QPen(QColor(P["BORDER"]), 1))
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.drawLine(int(r.left()), int(y), int(r.right()), int(y))
        f = QFont()
        f.setPointSizeF(8)
        p.setFont(f)
        lx = r.left()
        for name, vals, col, vmax in self.series:
            p.setPen(QColor(col))
            p.drawText(int(lx), 14, "● " + name)
            lx += p.fontMetrics().horizontalAdvance("● " + name) + 18
            pts = [(i, v) for i, v in enumerate(vals) if v is not None]
            if len(pts) < 2:
                continue
            n = len(vals)
            path = QPainterPath()
            for j, (i, v) in enumerate(pts):
                x = r.left() + r.width() * i / max(1, n - 1)
                y = r.bottom() - r.height() * min(1.0, v / vmax)
                path.moveTo(x, y) if j == 0 else path.lineTo(x, y)
            p.setPen(QPen(QColor(col), 1.6))
            p.drawPath(path)
        if self.series:
            p.setPen(QColor(P["DIM"]))
            vmax0 = self.series[0][3]
            for i in range(5):
                y = r.top() + r.height() * i / 4
                p.drawText(0, int(y + 4), f"{vmax0 * (1 - i / 4):.0f}")
            n = max(len(s[1]) for s in self.series)
            for idx, txt in self.marks:
                x = r.left() + r.width() * idx / max(1, n - 1)
                p.setPen(QPen(QColor(P["PURPLE"]), 1, Qt.PenStyle.DashLine))
                p.drawLine(int(x), int(r.top()), int(x), int(r.bottom()))
                p.drawText(int(x) + 3, int(r.top()) + 12, txt[:24])
        p.end()


# ---------------------------------------------------------------- pagine
class Dashboard:
    def __init__(self, win):
        self.w, lay = page("Panoramica")
        self.cu = CuInfo()
        tiles = QGridLayout()
        tiles.setSpacing(12)
        self.t = {
            "cpu_temp": Tile("CPU", "°C", 100, 80, 90), "gpu_temp": Tile("GPU", "°C", 100, 75, 85),
            "gpu_clk": Tile("Clock GPU", "MHz", 2100), "gpu_busy": Tile("Carico GPU", "%", 100),
            "power": Tile("Consumo SoC", "W", 200), "fan": Tile("Ventola", "rpm", 3000),
        }
        for i, t in enumerate(self.t.values()):
            c = Card()
            c.lay.addWidget(t)
            tiles.addWidget(c, i // 3, i % 3)
        lay.addLayout(tiles)
        self.game = label("", 10.5, wrap=True)
        gc = Card("In gioco")
        gc.lay.addWidget(self.game)
        lay.addWidget(gc)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        cc = Card("CPU — core fisici")
        self.cores = CoreBars()
        self.cpu_info = label("", 9, P["MUTED"])
        cc.lay.addWidget(self.cores)
        cc.lay.addWidget(self.cpu_info)
        mid.addWidget(cc, 3)
        gcard = Card("GPU — compute unit")
        self.grid = CuGrid()
        self.cu_info = label("", 9, P["MUTED"], wrap=True)
        gcard.lay.addWidget(self.grid)
        gcard.lay.addWidget(self.cu_info)
        gcard.lay.addStretch()
        mid.addWidget(gcard, 2)
        lay.addLayout(mid)
        bot = QHBoxLayout()
        bot.setSpacing(12)
        self.temps, self.mem, self.gov = (label("", 10) for _ in range(3))
        for title, l in (("Temperature scheda", self.temps), ("Memoria", self.mem), ("Governor", self.gov)):
            c = Card(title)
            c.lay.addWidget(l)
            c.lay.addStretch()
            bot.addWidget(c)
        lay.addLayout(bot)
        lay.addStretch()

    def refresh(self, st):
        s = st.get("sensors") or {}
        for k, t in self.t.items():
            t.set(s.get(k))
        g = st.get("game")
        if g:
            self.game.setText(
                f"<b>{g['name']}</b> <span style='color:{P['MUTED']}'>({g['api']})</span> — "
                f"<b style='color:{P['GOOD']}'>{g['fps']:.0f} FPS</b>"
                + (f" · 1% low {g['low1']:.0f}" if g.get("low1") else "")
                + (f" · limite {g['limit']}" if g.get("limit") else " · nessun limite")
                + (f" · profilo <b>{g['profile']}</b>" if g.get("profile") else ""))
        else:
            self.game.setText(f"<span style='color:{P['MUTED']}'>Nessun gioco attivo.</span>")
        if not getattr(self, "topo", None) or int(time.time()) % 10 == 0:
            self.topo = Sensors.topology()
        self.cores.set(self.topo, s.get("cpu_threads") or {}, s.get("cpu_freq") or {})
        nc = s.get("cores") or 0
        self.cpu_info.setText(f"{nc} core / {s.get('threads') or 0} thread · carico {s.get('cpu_load') or 0:.0f}%"
                              + ("  ·  sblocco 8 core attivo" if nc >= 8 else ""))
        d = self.cu.data
        self.grid.set(d.get("wgp_mask"), d.get("cc_inactive"))
        active = sum(bool(self.grid.active_wgp(i)) for i in range(5)) * 8
        self.cu_info.setText(f"<b style='color:{P['TEXT']}'>{active} / 40 CU attive</b>"
                             + ("" if d.get("wgp_mask") is not None else " (stima: umr non leggibile)"))
        lines = [f"<span style='color:{P['MUTED']}'>{k}</span> <b style='color:{temp_color(v, 70, 90)}'>{v:.0f}°C</b>"
                 for k, v in (s.get("board_temps") or {}).items()]
        if s.get("nvme_temp"):
            lines.append(f"<span style='color:{P['MUTED']}'>NVMe</span> "
                         f"<b style='color:{temp_color(s['nvme_temp'], 60, 70)}'>{s['nvme_temp']:.0f}°C</b>")
        self.temps.setText("<br>".join(lines) or "—")

        def pair(v, unit, fmt="{:.1f}"):
            if not v or v[0] is None or not v[1]:
                return "—"
            return f"{fmt.format(v[0])} / {fmt.format(v[1])} {unit} ({100 * v[0] / v[1]:.0f}%)"
        self.mem.setText("<br>".join([
            f"<span style='color:{P['MUTED']}'>RAM</span> <b>{pair(s.get('ram'), 'GiB')}</b>",
            f"<span style='color:{P['MUTED']}'>Swap</span> <b>{pair(s.get('swap'), 'GiB')}</b>",
            f"<span style='color:{P['MUTED']}'>VRAM</span> <b>{pair(s.get('vram'), 'MiB', '{:.0f}')}</b>",
            f"<span style='color:{P['MUTED']}'>GTT</span> <b>{pair(s.get('gtt'), 'GiB')}</b>"]))
        g = st.get("governor") or {}
        self.gov.setText("<br>".join([
            f"<span style='color:{P['MUTED']}'>Range</span> <b>{g.get('min') or '?'}–{g.get('max') or '?'} MHz</b>",
            f"<span style='color:{P['MUTED']}'>Taglio a</span> <b>{g.get('throttle') or '?'}°C</b> "
            f"<span style='color:{P['MUTED']}'>ripresa</span> <b>{g.get('recovery') or '?'}°C</b>",
            f"<span style='color:{P['MUTED']}'>Stato</span> <b style='color:{P['BAD'] if st.get('throttling') else P['GOOD']}'>"
            f"{'sta tagliando il clock' if st.get('throttling') else 'normale'}</b>",
            f"<span style='color:{P['MUTED']}'>VDDGFX</span> <b>{s.get('vddgfx') or 0:.0f} mV</b>"]))


LIMITS = [("Nessun limite", 0), ("30", 30), ("40", 40), ("45", 45), ("50", 50), ("60", 60), ("72", 72),
          ("75", 75), ("82 (metà di 165)", 82), ("90", 90), ("100", 100), ("120", 120), ("144", 144), ("165", 165)]


def limit_combo(value, allow_none_label=None):
    c = QComboBox()
    if allow_none_label:
        c.addItem(allow_none_label, None)
    for t, v in LIMITS:
        c.addItem(t, v)
    i = c.findData(value)
    if i < 0 and value is not None:
        c.addItem(str(value), value)
        i = c.count() - 1
    c.setCurrentIndex(max(0, i))
    return c


class GamesPage:
    def __init__(self, win):
        self.win = win
        self.w, lay = page("Giochi e FPS", "Il motore BC-250 conta gli FPS e applica il limite direttamente "
                           "dentro i giochi, al posto di MangoHud. Le modifiche valgono subito, anche a gioco aperto.")
        cfg = common.load_config()
        c = Card("Limite FPS")
        self.enabled = QCheckBox()
        self.enabled.setChecked(cfg["engine"]["limit_enabled"])
        self.enabled.toggled.connect(self.save)
        c.lay.addWidget(row("Limite FPS attivo", self.enabled, "Shift+F1 lo accende e spegne mentre giochi."))
        self.limit = limit_combo(cfg["engine"]["fps_limit"])
        self.limit.activated.connect(self.save)
        c.lay.addWidget(row("Limite per tutti i giochi", self.limit,
                            "I giochi con un profilo usano il limite del profilo. Con VRR attivo, "
                            "valori sotto i 165 Hz restano fluidi."))
        self.engine = QCheckBox()
        self.engine.setChecked(cfg["engine"]["enabled"])
        self.engine.toggled.connect(self.save)
        c.lay.addWidget(row("Motore FPS attivo", self.engine, "Se lo spegni il gioco non viene più misurato né limitato."))
        lay.addWidget(c)

        self.live = label("", 10, wrap=True)
        lc = Card("Giochi in esecuzione")
        lc.lay.addWidget(self.live)
        lay.addWidget(lc)

        gl = Card("Giochi OpenGL", "I giochi Vulkan e Proton (quasi tutti quelli Steam) sono coperti in automatico. "
                  "Quelli OpenGL vanno attivati uno per uno.")
        for app in FLATPAK_GL_APPS + self.other_flatpaks():
            cb = QCheckBox()
            cb.setChecked(flatpak_gl_enabled(app))
            cb.toggled.connect(lambda on, a=app: (flatpak_gl(a, on), win.toast(f"{a}: riavvia l'app per applicare.")))
            gl.lay.addWidget(row(app, cb, "App Flatpak — vale dal prossimo avvio."))
        steam = QLineEdit("bc250-gl %command%")
        steam.setReadOnly(True)
        steam.setMinimumWidth(220)
        gl.lay.addWidget(row("Giochi Steam OpenGL nativi", steam,
                             "Copia questo testo in Proprietà → Opzioni di avvio del gioco."))
        lay.addWidget(gl)

        mh = Card("MangoHud")
        self.mh = label("", 9.5, P["MUTED"], wrap=True)
        mh.lay.addWidget(self.mh)
        self.mh_btn = QCheckBox()
        self.mh_btn.setChecked(os.path.exists(common.MANGOHUD_FLAG))
        self.mh_btn.toggled.connect(self.toggle_mangohud)
        mh.lay.addWidget(row("Togli MangoHud dai giochi", self.mh_btn,
                             "Resta installato: puoi riattivarlo qui. Vale dal prossimo accesso alla sessione."))
        lay.addWidget(mh)
        lay.addStretch()

    @staticmethod
    def other_flatpaks():
        try:
            out = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True,
                                 text=True, timeout=10).stdout.split()
        except Exception:
            return []
        games = ("game", "minecraft", "prism", "retroarch", "dolphin-emu", "pcsx", "ppsspp", "heroic",
                 "lutris", "bottles", "hypixel", "openttd", "supertux", "xonotic", "veloren", "luanti")
        return sorted(a for a in out if a not in FLATPAK_GL_APPS and any(g in a.lower() for g in games))

    def save(self, *_):
        lim = self.limit.currentData()
        en, eng = self.enabled.isChecked(), self.engine.isChecked()
        cfg = common.update_config(lambda c: c["engine"].update(fps_limit=lim, limit_enabled=en, enabled=eng))
        e = cfg["engine"]
        write_control(e["fps_limit"], e["limit_enabled"], e["enabled"])
        self.win.toast("Limite FPS: " + (f"{lim}" if lim and en else "disattivato"))

    def toggle_mangohud(self, on):
        if on:
            os.makedirs(common.CONF_DIR, exist_ok=True)
            open(common.MANGOHUD_FLAG, "w").close()
        elif os.path.exists(common.MANGOHUD_FLAG):
            os.remove(common.MANGOHUD_FLAG)
        self.win.toast("Salvato: vale dal prossimo accesso alla sessione.")

    def refresh(self, st):
        gs = st.get("games") or []
        g = st.get("game")
        if gs:
            self.live.setText("<br>".join(
                f"<b>{x['name']}</b> <span style='color:{P['MUTED']}'>{x['api']}</span> — {x['fps']:.0f} FPS"
                + (f" · limite applicato <b>{g['limit']}</b>" if g and g['name'] == x['name'] and g.get('limit') else "")
                for x in gs))
        else:
            self.live.setText(f"<span style='color:{P['MUTED']}'>Nessun gioco sta disegnando frame.</span>")
        mh = health.mangohud_global() if int(time.time()) % 10 == 0 or not self.mh.text() else None
        if mh is not None:
            self.mh.setText("MangoHud è ancora caricato nella sessione attuale." if mh
                            else "MangoHud non viene più caricato nei giochi.")


class ProfilesPage:
    COLS = ["Nome", "Riconosci (processo o appid:ID)"] + [f[1] for f in common.PROFILE_FIELDS] + ["Note"]

    def __init__(self, win):
        self.win = win
        self.w, lay = page("Profili per gioco", "Quando un gioco parte, il suo profilo imposta limite FPS, clock GPU, "
                           "VRR, protezione calore e overlay. Alla chiusura torna tutto normale. "
                           "Puoi modificarli anche in gioco con Shift+F2.")
        c = Card()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(self.COLS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setMinimumHeight(300)
        c.lay.addWidget(self.table)
        c.lay.addWidget(label("Protezione calore: se la CPU supera la soglia, il limite FPS scende di 10 ogni 20 s; "
                              "quando torna 8°C sotto, risale. VRR: sul tuo monitor, all'avvio e alla chiusura del "
                              "gioco lo schermo diventa nero per un attimo.", 8.5, P["DIM"], wrap=True))
        btns = QHBoxLayout()
        for text, fn, obj in (("Aggiungi", self.add, None), ("Dal gioco in corso", self.add_current, None),
                              ("Elimina", self.delete, "danger"), ("Salva", self.save, "primary")):
            b = QPushButton(text)
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        c.lay.addLayout(btns)
        lay.addWidget(c)
        d = Card("Clock GPU normale (senza profilo)")
        cfg = common.load_config()
        self.gmin, self.gmax = QSpinBox(), QSpinBox()
        for sb, v in ((self.gmin, cfg["gpu_default"]["min"]), (self.gmax, cfg["gpu_default"]["max"])):
            sb.setRange(500, 2000)
            sb.setSingleStep(25)
            sb.setSuffix(" MHz")
            sb.setValue(v)
        d.lay.addWidget(row("Minimo", self.gmin))
        d.lay.addWidget(row("Massimo", self.gmax, "Più alto = più FPS ma più calore. Il governor taglia comunque "
                            "a 85°C. Con una sola ventola, 1750 è un buon compromesso."))
        b = QPushButton("Applica")
        b.setObjectName("primary")
        b.clicked.connect(self.apply_default)
        d.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        lay.addWidget(d)
        lay.addStretch()
        self.extra = []  # campi del profilo non mostrati in tabella, da conservare
        self.load()

    def load(self):
        profs = common.load_config()["profiles"]
        self.table.setRowCount(0)
        self.extra = []
        for p in profs:
            self.add_row(p)

    def add_row(self, p):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(p.get("name", "")))
        self.table.setItem(r, 1, QTableWidgetItem(p.get("match", "")))
        for i, (key, _label, values, fmt) in enumerate(common.PROFILE_FIELDS):
            cb = QComboBox()
            for v in values:
                cb.addItem(fmt(v, {}), v)
            cur = p.get(key, common.FIELD_DEFAULT[key])
            idx = values.index(cur) if cur in values else 0
            cb.setCurrentIndex(idx)
            self.table.setCellWidget(r, 2 + i, cb)
        self.table.setItem(r, len(self.COLS) - 1, QTableWidgetItem(p.get("notes", "")))
        known = {"name", "match", "notes"} | {f[0] for f in common.PROFILE_FIELDS}
        self.extra.append({k: v for k, v in p.items() if k not in known})

    def add(self):
        self.add_row({"name": "Nuovo gioco", "match": ""})

    def add_current(self):
        g = common.read_state().get("game")
        if not g:
            self.win.toast("Nessun gioco in corso.")
            return
        match = f"appid:{g['appid']}" if g.get("appid") else g["name"]
        self.add_row({"name": g["name"].removesuffix(".exe"), "match": match})

    def delete(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
            if r < len(self.extra):
                self.extra.pop(r)

    def save(self):
        profs = []
        for r in range(self.table.rowCount()):
            def text(c):
                it = self.table.item(r, c)
                return it.text().strip() if it else ""
            name, match = text(0), text(1)
            if not name or not match:
                continue
            p = dict(self.extra[r]) if r < len(self.extra) else {}
            p.update(name=name, match=match)
            for i, (key, *_rest) in enumerate(common.PROFILE_FIELDS):
                p[key] = self.table.cellWidget(r, 2 + i).currentData()
            notes = text(len(self.COLS) - 1)
            if notes:
                p["notes"] = notes
            profs.append(p)
        common.update_config(lambda c: c.update(profiles=profs))
        self.win.toast(f"{len(profs)} profili salvati.")

    def apply_default(self):
        mn, mx = self.gmin.value(), self.gmax.value()
        if mn > mx:
            mn = mx
        common.update_config(lambda c: c.update(gpu_default={"min": mn, "max": mx}))
        ok = governor_set(mn, mx)
        self.win.toast(f"Clock GPU {mn}–{mx} MHz" + ("" if ok else " (governor non raggiungibile!)"))

    def refresh(self, st):
        pass


ITEMS = [("fps", "FPS"), ("frametime", "Grafico frametime"), ("low1", "1% low"), ("cpu_temp", "Temperatura CPU"),
         ("gpu_temp", "Temperatura GPU"), ("gpu_clk", "Clock GPU"), ("power", "Consumo"), ("gpu_busy", "Carico GPU"),
         ("cpu_load", "Carico CPU"), ("fan", "Ventola"), ("ram", "RAM"), ("vram", "VRAM")]
POSITIONS = [("In alto a sinistra", "top-left"), ("In alto al centro", "top-center"),
             ("In alto a destra", "top-right"), ("In basso a sinistra", "bottom-left"),
             ("In basso al centro", "bottom-center"), ("In basso a destra", "bottom-right")]


class OverlayPage:
    def __init__(self, win):
        self.win = win
        self.w, lay = page("Overlay", "HUD minimal sopra i giochi e pannello dettagli in stile Steam.")
        o = common.load_config()["overlay"]
        c = Card("Tasti rapidi")
        c.lay.addWidget(label(
            f"<b>Shift+F1</b> <span style='color:{P['MUTED']}'>limite FPS on/off</span> &nbsp;&nbsp; "
            f"<b>Shift+F2</b> <span style='color:{P['MUTED']}'>pannello dettagli</span> &nbsp;&nbsp; "
            f"<b>Shift+F3</b> <span style='color:{P['MUTED']}'>mostra/nascondi overlay</span>", 10))
        c.lay.addWidget(label("Si cambiano in Impostazioni di sistema → Scorciatoie → «BC-250».", 8.5, P["DIM"]))
        b = QPushButton("Apri pannello dettagli ora")
        b.clicked.connect(lambda: common.overlay_send("toggle-panel"))
        c.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(c)

        a = Card("Aspetto")
        self.visible = QCheckBox()
        self.visible.setChecked(o["hud_visible"])
        a.lay.addWidget(row("Overlay visibile", self.visible))
        self.only = QCheckBox()
        self.only.setChecked(o["only_in_game"])
        a.lay.addWidget(row("Solo mentre giochi", self.only, "Se spento resta sempre visibile sul desktop."))
        self.pos = QComboBox()
        for t, v in POSITIONS:
            self.pos.addItem(t, v)
        self.pos.setCurrentIndex(max(0, self.pos.findData(o["position"])))
        a.lay.addWidget(row("Posizione", self.pos))
        self.margin = QSpinBox()
        self.margin.setRange(0, 400)
        self.margin.setSuffix(" px")
        self.margin.setValue(int(o["margin"]))
        a.lay.addWidget(row("Distanza dal bordo", self.margin))
        self.scale = QSlider(Qt.Orientation.Horizontal)
        self.scale.setRange(60, 200)
        self.scale.setValue(int(float(o["scale"]) * 100))
        self.scale.setFixedWidth(220)
        a.lay.addWidget(row("Dimensione", self.scale))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(int(float(o["opacity"]) * 100))
        self.opacity.setFixedWidth(220)
        a.lay.addWidget(row("Opacità sfondo", self.opacity))
        lay.addWidget(a)

        it = Card("Cosa mostrare")
        grid = QGridLayout()
        self.items = {}
        for i, (k, t) in enumerate(ITEMS):
            cb = QCheckBox(t)
            cb.setChecked(k in o["items"])
            cb.toggled.connect(self.save)
            self.items[k] = cb
            grid.addWidget(cb, i // 3, i % 3)
        it.lay.addLayout(grid)
        lay.addWidget(it)
        for w in (self.visible, self.only):
            w.toggled.connect(self.save)
        self.pos.activated.connect(self.save)
        for w in (self.margin, self.scale, self.opacity):
            w.valueChanged.connect(self.save)
        lay.addStretch()

    def save(self, *_):
        items = [k for k, _ in ITEMS if self.items[k].isChecked()]
        common.update_config(lambda c: c["overlay"].update(
            hud_visible=self.visible.isChecked(), only_in_game=self.only.isChecked(),
            position=self.pos.currentData(), margin=self.margin.value(),
            scale=self.scale.value() / 100, opacity=self.opacity.value() / 100, items=items))

    def refresh(self, st):
        pass


class DisplayPage:
    def __init__(self, win):
        self.win = win
        self.w, self.lay = page("Display", "VRR (FreeSync): il monitor si adatta agli FPS del gioco. "
                                "Niente tearing e niente scatti anche sotto i 165 Hz. Funziona nei giochi a schermo intero.")
        auto = Card("Automatico")
        self.games_only = QCheckBox()
        self.games_only.setChecked(common.load_config()["display"]["vrr_games_only"])
        self.games_only.toggled.connect(self.save_auto)
        auto.lay.addWidget(row("VRR solo nei giochi", self.games_only,
                               "Il servizio BC-250 lo accende quando parte un gioco e lo spegne alla chiusura "
                               "(schermo nero per un attimo). Il gioco deve essere a schermo intero."))
        self.lay.addWidget(auto)
        self.box = QVBoxLayout()
        self.lay.addLayout(self.box)
        self.lay.addStretch()
        self.build()

    def save_auto(self, on):
        common.update_config(lambda c: c["display"].update(vrr_games_only=on))
        self.win.toast("VRR solo nei giochi: " + ("attivo" if on else "disattivato (lo gestisci a mano qui sotto)"))

    def build(self):
        while self.box.count():
            it = self.box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for o in health.vrr_outputs():
            c = Card(f"Schermo {o['name']} — {o['mode']} Hz")
            vrr = QComboBox()
            for t, v in (("Mai", "never"), ("Automatico (giochi a schermo intero)", "automatic"), ("Sempre", "always")):
                vrr.addItem(t, v)
            vrr.setCurrentIndex(max(0, vrr.findData(o["vrr"])))
            vrr.activated.connect(lambda _, name=o["name"], cb=vrr: self.set_vrr(name, cb.currentData()))
            c.lay.addWidget(row("VRR / FreeSync (manuale)", vrr, "Con «VRR solo nei giochi» attivo lo decide il servizio. "
                                "Sul desktop il tuo monitor col VRR sfarfalla."))
            modes = QComboBox()
            seen = set()
            for m in sorted(o["modes"], key=lambda m: (-m["w"] * m["h"], -m["hz"])):
                key = (m["w"], m["h"], round(m["hz"]))
                if key in seen:
                    continue
                seen.add(key)
                modes.addItem(f"{m['w']}×{m['h']} @ {m['hz']:.0f} Hz", m["id"])
            modes.setCurrentIndex(max(0, modes.findData(o["current_mode"])))
            modes.activated.connect(lambda _, name=o["name"], cb=modes: self.set_mode(name, cb.currentData()))
            c.lay.addWidget(row("Risoluzione e frequenza", modes))
            self.box.addWidget(c)

    def set_vrr(self, name, policy):
        ok = health.set_vrr(name, policy)
        self.win.toast(f"VRR {name}: {policy}" if ok else "Errore nel cambiare il VRR")

    def set_mode(self, name, mode_id):
        ok = health.sh(["kscreen-doctor", f"output.{name}.mode.{mode_id}"])[0] == 0
        self.win.toast("Modalità cambiata (KDE chiede conferma se serve)." if ok else "Errore")
        QTimer.singleShot(1500, self.build)

    def refresh(self, st):
        pass


class HealthPage:
    def __init__(self, win):
        self.win = win
        self.w, self.lay = page("Salute", "Controlli per assicurarti che la BC-250 giri al meglio.")
        b = QPushButton("Ricontrolla")
        b.setObjectName("primary")
        b.clicked.connect(self.build)
        self.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.box = QVBoxLayout()
        self.box.setSpacing(8)
        self.lay.addLayout(self.box)
        tips = Card("Consigli")
        tips.lay.addWidget(label(
            "• La ventola è una sola e gira sempre al massimo: il limite vero è il raffreddamento. "
            "Una seconda ventola sul dissipatore o una più potente è l'upgrade che rende di più.<br>"
            "• Pasta termica nuova e dissipatore pulito: −5/−10°C tipici su queste schede.<br>"
            "• Usa un limite FPS (60–90) con VRR: meno calore, stessa fluidità percepita.<br>"
            "• Nei giochi con generazione del mondo (Hytale, Minecraft) abbassa la distanza visiva: pesa sulla CPU.<br>"
            "• Profili per gioco: clock GPU più basso nei giochi leggeri = scheda più fresca.", 9.5, P["MUTED"], wrap=True))
        self.lay.addWidget(tips)
        self.lay.addStretch()
        QTimer.singleShot(300, self.build)

    def build(self):
        while self.box.count():
            it = self.box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for ch in health.checks():
            c = QFrame()
            c.setObjectName("card")
            h = QHBoxLayout(c)
            h.setContentsMargins(14, 10, 14, 10)
            col = (P["WARN"] if ch["ok"] == "warn" else P["GOOD"] if ch["ok"] else
                   P["MUTED"] if ch["ok"] is None else P["BAD"])
            dot = label("●", 14, col)
            h.addWidget(dot)
            v = QVBoxLayout()
            v.setSpacing(0)
            v.addWidget(label(ch["title"], 10, bold=True))
            v.addWidget(label(ch["detail"], 9, P["MUTED"], wrap=True))
            h.addLayout(v, 1)
            if ch["fix"] and ch["ok"] is False or ch["id"] in ("daemon", "overlay") and ch["fix"]:
                b = QPushButton(ch["fix"])
                b.clicked.connect(lambda _, i=ch["id"]: self.fix(i))
                h.addWidget(b)
            self.box.addWidget(c)

    def fix(self, cid):
        ok, msg = health.fix(cid)
        self.win.toast(msg if ok else "Non riuscito: " + msg)
        QTimer.singleShot(1500, self.build)

    def refresh(self, st):
        pass


class HistoryPage:
    def __init__(self, win):
        self.win = win
        self.w, lay = page("Storico partite", "Ogni partita viene registrata (FPS, temperature, clock, consumi). "
                           "I segni viola li aggiunge Claude durante i test.")
        top = QHBoxLayout()
        self.list = QListWidget()
        self.list.setObjectName("nav")
        self.list.setFixedWidth(300)
        self.list.setMinimumHeight(520)
        self.list.currentRowChanged.connect(self.show_session)
        top.addWidget(self.list)
        right = QVBoxLayout()
        self.summary = label("", 10, wrap=True)
        sc = Card("Riepilogo")
        sc.lay.addWidget(self.summary)
        right.addWidget(sc)
        self.c_fps, self.c_temp, self.c_clk = Chart(), Chart(), Chart()
        for title, ch in (("FPS", self.c_fps), ("Temperature", self.c_temp), ("Clock GPU e consumo", self.c_clk)):
            c = Card(title)
            c.lay.addWidget(ch)
            right.addWidget(c)
        top.addLayout(right, 1)
        lay.addLayout(top)
        b = QPushButton("Aggiorna")
        b.clicked.connect(self.load)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.sessions = []
        self.load()

    def db(self):
        con = sqlite3.connect(common.DB_PATH, timeout=3)
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE IF NOT EXISTS marks(session INTEGER, t REAL, note TEXT)")
        return con

    def load(self):
        self.list.clear()
        try:
            con = self.db()
            self.sessions = con.execute("SELECT * FROM sessions ORDER BY start DESC LIMIT 200").fetchall()
        except sqlite3.Error:
            self.sessions = []
        for s in self.sessions:
            mins = (s["end"] - s["start"]) / 60
            it = QListWidgetItem(f"{s['game']}\n{time.strftime('%d/%m %H:%M', time.localtime(s['start']))}"
                                 f" · {mins:.0f} min")
            self.list.addItem(it)
        if self.sessions:
            self.list.setCurrentRow(0)
        else:
            self.summary.setText(f"<span style='color:{P['MUTED']}'>Ancora nessuna partita registrata.</span>")

    def show_session(self, i):
        if i < 0 or i >= len(self.sessions):
            return
        s = self.sessions[i]
        con = self.db()
        rows = con.execute("SELECT * FROM samples WHERE session=? ORDER BY t", (s["id"],)).fetchall()
        marks = con.execute("SELECT * FROM marks WHERE session=? ORDER BY t", (s["id"],)).fetchall()
        if not rows:
            self.summary.setText("Nessun dato.")
            return
        step = max(1, len(rows) // 400)
        rs = rows[::step]

        def col(k):
            return [r[k] for r in rs]

        def stat(k, f=max):
            v = [r[k] for r in rows if r[k] is not None]
            return f(v) if v else 0
        fps = [r["fps"] for r in rows if r["fps"]]
        low = [r["low1"] for r in rows if r["low1"]]
        thr = 100 * sum(r["throttling"] or 0 for r in rows) / len(rows)
        self.summary.setText(
            f"<b>{s['game']}</b> <span style='color:{P['MUTED']}'>· {s['api']} · "
            f"{'profilo ' + s['profile'] if s['profile'] else 'nessun profilo'} · {(s['end'] - s['start']) / 60:.0f} min</span><br>"
            f"FPS medi <b>{sum(fps) / len(fps) if fps else 0:.0f}</b> · 1% low medio <b>{sum(low) / len(low) if low else 0:.0f}</b>"
            f" · CPU max <b style='color:{temp_color(stat('cpu_temp'), 80, 90)}'>{stat('cpu_temp'):.0f}°C</b>"
            f" · GPU max <b style='color:{temp_color(stat('gpu_temp'))}'>{stat('gpu_temp'):.0f}°C</b>"
            f" · consumo medio <b>{stat('power', lambda v: sum(v) / len(v)):.0f} W</b>"
            f" · taglio clock <b style='color:{P['BAD'] if thr > 5 else P['GOOD']}'>{thr:.0f}% del tempo</b>")
        mk = []
        for m in marks:
            idx = min(range(len(rs)), key=lambda j: abs(rs[j]["t"] - m["t"]))
            mk.append((idx, m["note"]))
        top = max(60, max(fps or [60]) * 1.15)
        self.c_fps.set([("FPS", col("fps"), P["GOOD"], top), ("1% low", col("low1"), P["WARN"], top)], mk)
        self.c_temp.set([("CPU °C", col("cpu_temp"), P["BAD"], 100), ("GPU °C", col("gpu_temp"), P["WARN"], 100)], mk)
        self.c_clk.set([("Clock GPU MHz", col("gpu_clk"), P["ACCENT"], 2100),
                        ("Consumo W ×10", [None if v is None else v * 10 for v in col("power")], P["PURPLE"], 2100)], mk)

    def refresh(self, st):
        pass


class AlertsPage:
    def __init__(self, win):
        self.win = win
        self.w, lay = page("Avvisi", "Notifica sul desktop e messaggio sopra il gioco quando qualcosa va storto.")
        a = common.load_config()["alerts"]
        c = Card()
        self.en = QCheckBox()
        self.en.setChecked(a["enabled"])
        c.lay.addWidget(row("Avvisi attivi", self.en))
        self.cpu, self.gpu, self.fan, self.cool = QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox()
        for sb, rng, suf, v in ((self.cpu, (60, 100), " °C", a["cpu_temp"]), (self.gpu, (60, 100), " °C", a["gpu_temp"]),
                                (self.fan, (0, 3000), " rpm", a["fan_min_rpm"]),
                                (self.cool, (30, 3600), " s", a["cooldown_s"])):
            sb.setRange(*rng)
            sb.setSuffix(suf)
            sb.setValue(int(v))
        c.lay.addWidget(row("CPU oltre", self.cpu, "La CPU (Zen 2) è al limite a 97°C."))
        c.lay.addWidget(row("GPU oltre", self.gpu, "Il governor taglia il clock a 85°C."))
        c.lay.addWidget(row("Ventola sotto", self.fan, "La tua gira a ~1080 rpm: sotto questa soglia è ferma o guasta."))
        c.lay.addWidget(row("Non ripetere prima di", self.cool))
        b = QPushButton("Salva")
        b.setObjectName("primary")
        b.clicked.connect(self.save)
        c.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        lay.addWidget(c)
        t = QPushButton("Prova una notifica")
        t.clicked.connect(lambda: subprocess.Popen(["notify-send", "-a", "BC-250", "BC-250", "Le notifiche funzionano."]))
        lay.addWidget(t, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()

    def save(self):
        common.update_config(lambda c: c["alerts"].update(
            enabled=self.en.isChecked(), cpu_temp=self.cpu.value(), gpu_temp=self.gpu.value(),
            fan_min_rpm=self.fan.value(), cooldown_s=self.cool.value()))
        self.win.toast("Avvisi salvati.")

    def refresh(self, st):
        pass


# ---------------------------------------------------------------- finestra
class Main(QWidget):
    PAGES = [("Panoramica", "utilities-system-monitor", Dashboard), ("Giochi e FPS", "applications-games", GamesPage),
             ("Profili", "view-list-details", ProfilesPage), ("Overlay", "view-visible", OverlayPage),
             ("Display", "video-display", DisplayPage), ("Salute", "security-high", HealthPage),
             ("Storico", "view-history", HistoryPage), ("Avvisi", "dialog-warning", AlertsPage)]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BC-250 Control Center")
        self.setWindowIcon(QIcon.fromTheme("utilities-system-monitor"))
        self.setStyleSheet(STYLE)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        side = QWidget()
        side.setFixedWidth(210)
        side.setStyleSheet(f"background:{P['SIDEBAR']};")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 18, 0, 12)
        brand = label("BC-250", 15, bold=True)
        brand.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(brand)
        sub = label("Control Center", 9, P["MUTED"])
        sub.setContentsMargins(20, 0, 0, 8)
        sl.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        sl.addWidget(self.nav, 1)
        self.status = label("", 8.5, P["MUTED"], wrap=True)
        self.status.setContentsMargins(18, 0, 12, 0)
        sl.addWidget(self.status)
        root.addWidget(side)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.toast_l = label("", 9.5, P["ACCENT"])
        self.toast_l.setContentsMargins(26, 6, 26, 8)
        right.addWidget(self.toast_l)
        root.addLayout(right, 1)

        self.pages = []
        for name, icon, cls in self.PAGES:
            it = QListWidgetItem(QIcon.fromTheme(icon), name)
            self.nav.addItem(it)
            pg = cls(self)
            self.pages.append(pg)
            self.stack.addWidget(pg.w)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(lambda: self.toast_l.setText(""))

        self.resize(1240, 860)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.tick()

    def toast(self, text):
        self.toast_l.setText(text)
        self.toast_timer.start(4000)

    def tick(self):
        st = common.read_state()
        fresh = time.time() - st.get("ts", 0) < 5
        g = st.get("game")
        self.status.setText(
            (f"<span style='color:{P['GOOD']}'>●</span> servizio attivo" if fresh else
             f"<span style='color:{P['BAD']}'>●</span> servizio fermo — vedi Salute")
            + (f"<br>{g['name']} · {g['fps']:.0f} FPS" if g else ""))
        cur = self.stack.currentIndex()
        try:
            self.pages[cur].refresh(st)
        except Exception as e:  # una pagina non deve bloccare la finestra
            print("refresh error:", e, file=sys.stderr)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("bc250-control")
    app.setDesktopFileName("bc250-control")
    w = Main()
    if "--page" in sys.argv:
        w.nav.setCurrentRow(int(sys.argv[sys.argv.index("--page") + 1]))
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
