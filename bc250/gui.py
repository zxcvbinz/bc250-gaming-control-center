# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""BC-250 Control Center — interfaccia principale."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from collections import deque

from PyQt6.QtCore import QRectF, QSize, QStringListModel, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QIcon, QPixmap, QTextDocument, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QCompleter, QFrame,
                             QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea,
                             QSizePolicy, QSlider, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from . import __version__, common, gamecfg, health, i18n
from .engine import write_control
from .i18n import T
from .hudpaint import (ACCENTS, CENTER, DEMOS, DISPLAY, IDLE, LOOK_DEFAULT, MONO, STYLES, WATCH, HudPainter,
                       demo_state, display_font, font, load_fonts)
from .install import FLATPAK_GL_APPS, flatpak_gl, flatpak_gl_enabled
from .sensors import Sensors, governor_set

P = common.PALETTE
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

STYLE = f"""
QWidget {{ background:{P['BG']}; color:{P['TEXT']}; font-size:10pt; font-family:'{MONO}'; }}
QLabel {{ background:transparent; }}
QFrame#card {{ background:{P['CARD']}; border:1px solid {P['BORDER']}; border-radius:0px; }}
QListWidget#nav {{ background:{P['SIDEBAR']}; border:none; border-right:1px solid {P['BORDER']};
    padding:10px 0; outline:0; }}
QListWidget#nav::item {{ padding:9px 12px 9px 18px; border-left:2px solid transparent; margin:0; color:{P['MUTED']}; }}
QListWidget#nav::item:selected {{ background:{P['CARD2']}; color:{P['TEXT']}; border-left:2px solid {P['ACCENT']}; }}
QListWidget#nav::item:hover:!selected {{ background:{P['CARD']}; }}
QPushButton {{ background:{P['CARD2']}; border:1px solid {P['BORDER']}; border-radius:0px;
    padding:6px 14px; color:{P['TEXT']}; }}
QPushButton:hover {{ border-color:{P['ACCENT']}; }}
QPushButton#primary {{ background:{P['ACCENT']}; border:none; color:{P['ON_ACCENT']}; font-weight:bold; }}
QPushButton#danger {{ color:{P['BAD']}; }}
QComboBox, QSpinBox, QLineEdit {{ background:{P['BG']}; border:1px solid {P['BORDER']}; border-radius:0px;
    padding:4px 8px; min-height:22px; }}
QComboBox {{ combobox-popup:0; }}
QComboBox::drop-down {{ border:none; width:22px; }}
QComboBox::down-arrow {{ image:url({ASSETS}/chevron.svg); width:12px; height:12px; }}
QComboBox QAbstractItemView {{ background:{P['CARD2']}; color:{P['TEXT']}; border:1px solid {P['BORDER']};
    border-radius:0px; padding:4px; outline:0; selection-background-color:{P['ACCENT']}; selection-color:{P['ON_ACCENT']}; }}
QComboBox QAbstractItemView::item {{ min-height:24px; padding:2px 8px; }}
QMenu {{ background:{P['CARD2']}; border:1px solid {P['BORDER']}; padding:4px; }}
QMenu::item:selected {{ background:{P['ACCENT']}; color:{P['ON_ACCENT']}; }}
QCheckBox {{ spacing:10px; background:transparent; }}
QCheckBox::indicator {{ width:34px; height:18px; image:url({ASSETS}/switch-off.svg); }}
QCheckBox::indicator:checked {{ image:url({ASSETS}/switch-on.svg); }}
QSlider::groove:horizontal {{ height:4px; background:{P['OFF']}; border-radius:0px; }}
QSlider::handle:horizontal {{ width:10px; margin:-6px 0; border-radius:0px; background:{P['ACCENT']}; }}
QTableWidget {{ background:{P['CARD']}; border:none; gridline-color:{P['BORDER']}; }}
QHeaderView::section {{ background:{P['CARD2']}; color:{P['MUTED']}; border:none; border-bottom:1px solid {P['BORDER']}; padding:6px; }}
QTableWidget::item:selected {{ background:{P['CARD2']}; color:{P['TEXT']}; }}
QTreeWidget#hist {{ background:{P['SIDEBAR']}; border:none; border-right:1px solid {P['BORDER']};
    padding:8px 6px; outline:0; }}
QTreeWidget#hist::item {{ padding:7px 6px; border-radius:0px; margin:1px 0; color:{P['MUTED']}; }}
QTreeWidget#hist::item:selected {{ background:{P['CARD2']}; color:{P['TEXT']}; border-left:2px solid {P['ACCENT']}; }}
QTreeWidget#hist::item:hover:!selected {{ background:{P['CARD']}; }}
QListWidget#items {{ background:{P['BG']}; border:1px solid {P['BORDER']}; border-radius:0px; padding:4px; outline:0; }}
QListWidget#items::item {{ padding:4px 6px; border-radius:0px; }}
QListWidget#items::item:hover {{ background:{P['CARD2']}; }}
QListWidget#items::item:selected {{ background:{P['CARD2']}; color:{P['TEXT']}; }}
QListWidget#items::indicator {{ width:16px; height:16px; border-radius:0px; }}
QListWidget#items::indicator:unchecked {{ border:1px solid {P['MUTED']}; background:{P['BG']}; }}
QListWidget#items::indicator:checked {{ border:1px solid {P['ACCENT']}; background:{P['ACCENT']}; image:url({ASSETS}/check.svg); }}
QLineEdit#find {{ background:{P['BG']}; border:1px solid {P['BORDER']}; border-radius:0px; padding:6px 8px; }}
QLineEdit#find:focus {{ border-color:{P['ACCENT']}; }}
QListView#findpop {{ background:{P['CARD2']}; color:{P['TEXT']}; border:1px solid {P['BORDER']}; padding:4px;
    selection-background-color:{P['ACCENT']}; selection-color:{P['ON_ACCENT']}; outline:0; }}
QScrollArea {{ border:none; }}
QScrollBar:vertical {{ background:transparent; width:8px; }}
QScrollBar::handle:vertical {{ background:{P['OFF']}; border-radius:0px; min-height:30px; }}
QScrollBar:horizontal {{ background:transparent; height:8px; }}
QScrollBar::handle:horizontal {{ background:{P['OFF']}; border-radius:0px; min-width:30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height:0; width:0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
"""


# ---------------------------------------------------------------- piccoli componenti
class WrapLabel(QLabel):
    """QLabel che va a capo calcolando l'altezza sulla larghezza vera.
    Il QLabel normale riserva l'altezza per una larghezza più stretta: card più alte del testo."""

    def hasHeightForWidth(self):
        return self.wordWrap() or super().hasHeightForWidth()

    def heightForWidth(self, w):
        if not self.wordWrap():
            return super().heightForWidth(w)
        m = self.contentsMargins()
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDocumentMargin(0)
        doc.setHtml(self.text()) if self.textFormat() == Qt.TextFormat.RichText else doc.setPlainText(self.text())
        doc.setTextWidth(max(1, w - m.left() - m.right()))
        return int(doc.size().height()) + m.top() + m.bottom() + 1

    def minimumSizeHint(self):
        if not self.wordWrap():
            return super().minimumSizeHint()
        # il minimo vero lo dà heightForWidth: qui niente altezza riservata per larghezze strette
        return QSize(0, self.heightForWidth(4000))

    def sizeHint(self):
        if not self.wordWrap():
            return super().sizeHint()
        w = self.width() if self.width() > 200 else 4000   # prima del layout la larghezza non è quella vera
        return QSize(super().sizeHint().width(), self.heightForWidth(w))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.wordWrap() and e.oldSize().width() != e.size().width():
            self.updateGeometry()


def label(text="", size=10, color=None, bold=False, wrap=False):
    l = WrapLabel(text)
    f = QFont()
    f.setPointSizeF(size)
    f.setBold(bold)
    l.setFont(f)
    l.setStyleSheet(f"color:{color or P['TEXT']}; font-size:{size}pt; font-weight:{'bold' if bold else 'normal'};")
    l.setWordWrap(wrap)
    l.setTextFormat(Qt.TextFormat.RichText)
    l.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    return l


class Card(QFrame):
    def __init__(self, title=None, subtitle=None):
        super().__init__()
        self.setObjectName("card")
        # mai più alta del contenuto (le card affiancate vengono pareggiate a parte)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(16, 12, 16, 14)
        self.lay.setSpacing(8)
        if title:
            t = label(title.upper(), 8.5, P["MUTED"], True)
            t.setStyleSheet(f"color:{P['MUTED']}; letter-spacing:1px;")
            self.lay.addWidget(t)
        if subtitle:
            self.lay.addWidget(label(subtitle, 9, P["DIM"], wrap=True))
        # dopo la costruzione: lo spazio in più va in fondo, così i testi restano in alto
        # invece di distribuirsi in verticale quando la card è più alta del contenuto
        QTimer.singleShot(0, lambda: self.lay.addStretch(1))


def row(text, widget, hint=None):
    w = QWidget()
    w.setStyleSheet("background:transparent;")
    h = QHBoxLayout(w)
    h.setContentsMargins(0, 2, 0, 2)
    v = QVBoxLayout()
    v.setSpacing(0)
    main = label(text, 10)
    if not hint:  # riga singola: centrata rispetto al controllo a destra
        main.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    v.addWidget(main)
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
    head = label(title, 19, bold=True)
    head.setStyleSheet(f"color:{P['TEXT']}; font-family:'{DISPLAY}'; font-size:19pt; font-weight:bold;"
                       f" border-bottom:1px solid {P['BORDER']}; padding-bottom:10px;")
    lay.addWidget(head)
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

    def __init__(self, name, unit, vmax, warn=None, bad=None, color=None):
        super().__init__()
        self.name, self.unit, self.vmax, self.warn, self.bad = name, unit, vmax, warn, bad
        self.base = color or P["ACCENT"]
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
            return QColor(self.base)
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
        f.setPointSizeF(7.5)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1)
        p.setFont(f)
        p.setPen(QColor(P["MUTED"]))
        p.drawText(0, 13, self.name.upper())
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0)
        f.setPointSizeF(20)
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
                p.drawRect(r)
                if on and i < len(th):
                    u = self.threads.get(str(th[i]), self.threads.get(th[i], 0))
                    p.setBrush(QColor(P["BAD"] if u > 90 else P["WARN"] if u > 70 else P["ACCENT"]))
                    p.drawRect(QRectF(bar_x, y + 2 + i * 10, max(2, bar_w * u / 100), 7))
            p.setPen(QColor(P["MUTED"] if on else P["DIM"]))
            if on:
                fr = max((self.freq.get(str(t), self.freq.get(t, 0)) for t in th), default=0)
                u = max((self.threads.get(str(t), self.threads.get(t, 0)) for t in th), default=0)
                p.drawText(int(bar_x + bar_w + 10), y + 15, f"{fr / 1000:.2f} GHz  {u:3.0f}%")
            else:
                p.drawText(int(bar_x + bar_w + 10), y + 15, T("bloccato"))
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
                    p.setBrush(QColor(P["CYAN"] if on else P["OFF"]))
                    p.drawRect(QRectF(x, y, cell, cell))
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
        self.w, lay = page(T("Panoramica"))
        # un solo thread di lettura CU anche se la finestra ricostruisce le pagine (cambio lingua)
        self.cu = getattr(win, "cu_reader", None) or CuInfo()
        win.cu_reader = self.cu
        tiles = QGridLayout()
        tiles.setSpacing(12)
        self.t = {
            "cpu_temp": Tile("CPU", "°C", 100, 80, 90), "gpu_temp": Tile("GPU", "°C", 100, 75, 85),
            "gpu_clk": Tile(T("Clock GPU"), "MHz", 2100, color=P["CYAN"]), "gpu_busy": Tile(T("Carico GPU"), "%", 100, color=P["TEXT"]),
            "power": Tile(T("Consumo SoC"), "W", 200, color=P["TEXT"]), "fan": Tile(T("Ventola"), "rpm", 3000, color=P["TEXT"]),
        }
        for i, t in enumerate(self.t.values()):
            c = Card()
            c.lay.addWidget(t)
            tiles.addWidget(c, i // 3, i % 3)
        lay.addLayout(tiles)
        self.game = label("", 10.5, wrap=True)
        gc = Card(T("In gioco"))
        gc.lay.addWidget(self.game)
        lay.addWidget(gc)
        mid = QHBoxLayout()
        mid.setSpacing(12)
        cc = Card(T("CPU — core fisici"))
        self.cores = CoreBars()
        self.cpu_info = label("", 9, P["MUTED"])
        cc.lay.addWidget(self.cores)
        cc.lay.addWidget(self.cpu_info)
        cc.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)  # affiancate: stessa altezza
        mid.addWidget(cc, 3)
        gcard = Card(T("GPU — compute unit"))
        self.grid = CuGrid()
        self.cu_info = label("", 9, P["MUTED"], wrap=True)
        gcard.lay.addWidget(self.grid)
        gcard.lay.addWidget(self.cu_info)
        gcard.lay.addStretch()
        gcard.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)  # affiancate: stessa altezza
        mid.addWidget(gcard, 2)
        lay.addLayout(mid)
        bot = QHBoxLayout()
        bot.setSpacing(12)
        self.temps, self.mem, self.gov = (label("", 10) for _ in range(3))
        for title, l in (("Temperature scheda", self.temps), ("Memoria", self.mem), ("Governor", self.gov)):
            c = Card(T(title))
            c.lay.addWidget(l)
            c.lay.addStretch()
            c.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)  # affiancate: stessa altezza
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
                + (" · " + T("limite {v}", v=g["limit"]) if g.get("limit") else " · " + T("nessun limite"))
                + (" · " + T("profilo <b>{p}</b>", p=g["profile"]) if g.get("profile") else ""))
        else:
            self.game.setText(f"<span style='color:{P['MUTED']}'>{T('Nessun gioco attivo.')}</span>")
        if not getattr(self, "topo", None) or int(time.time()) % 10 == 0:
            self.topo = Sensors.topology()
        self.cores.set(self.topo, s.get("cpu_threads") or {}, s.get("cpu_freq") or {})
        nc = s.get("cores") or 0
        self.cpu_info.setText(T("{c} core / {t} thread · carico {l:.0f}%", c=nc, t=s.get('threads') or 0,
                                l=s.get('cpu_load') or 0)
                              + ("  ·  " + T("sblocco 8 core attivo") if nc >= 8 else ""))
        d = self.cu.data
        self.grid.set(d.get("wgp_mask"), d.get("cc_inactive"))
        active = sum(bool(self.grid.active_wgp(i)) for i in range(5)) * 8
        self.cu_info.setText(f"<b style='color:{P['TEXT']}'>{T('{n} / 40 CU attive', n=active)}</b>"
                             + ("" if d.get("wgp_mask") is not None else " " + T("(stima: umr non leggibile)")))
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
            f"<span style='color:{P['MUTED']}'>{T('Range')}</span> <b>{g.get('min') or '?'}–{g.get('max') or '?'} MHz</b>",
            f"<span style='color:{P['MUTED']}'>{T('Taglio a')}</span> <b>{g.get('throttle') or '?'}°C</b> "
            f"<span style='color:{P['MUTED']}'>{T('ripresa')}</span> <b>{g.get('recovery') or '?'}°C</b>",
            f"<span style='color:{P['MUTED']}'>{T('Stato')}</span> <b style='color:{P['BAD'] if st.get('throttling') else P['GOOD']}'>"
            f"{T('sta tagliando il clock') if st.get('throttling') else T('normale')}</b>",
            f"<span style='color:{P['MUTED']}'>VDDGFX</span> <b>{s.get('vddgfx') or 0:.0f} mV</b>"]))


LIMITS = [("Nessun limite", 0), ("30", 30), ("40", 40), ("45", 45), ("50", 50), ("60", 60), ("72", 72),
          ("75", 75), ("82 (metà di 165)", 82), ("90", 90), ("100", 100), ("120", 120), ("144", 144), ("165", 165)]


def limit_combo(value, allow_none_label=None):
    c = QComboBox()
    if allow_none_label:
        c.addItem(allow_none_label, None)
    for t, v in LIMITS:
        c.addItem(T(t), v)
    i = c.findData(value)
    if i < 0 and value is not None:
        c.addItem(str(value), value)
        i = c.count() - 1
    c.setCurrentIndex(max(0, i))
    return c


def other_flatpaks():
    """App Flatpak che sembrano giochi o launcher (oltre a quelle note), per la compatibilità OpenGL."""
    try:
        out = subprocess.run(["flatpak", "list", "--app", "--columns=application"], capture_output=True,
                             text=True, timeout=10).stdout.split()
    except Exception:
        return []
    games = ("game", "minecraft", "prism", "retroarch", "dolphin-emu", "pcsx", "ppsspp", "heroic",
             "lutris", "bottles", "hypixel", "openttd", "supertux", "xonotic", "veloren", "luanti")
    return sorted(a for a in out if a not in FLATPAK_GL_APPS and any(g in a.lower() for g in games))


class FpsPage:
    """Limite FPS globale, motore, upscaling con gamescope e MangoHud."""

    def __init__(self, win):
        self.win = win
        self.w, lay = page(T("FPS e upscaling"), T("Il motore BC-250 misura gli FPS e applica il limite direttamente "
                           "dentro i giochi. Un limite FPS è il modo più semplice per avere meno calore e meno rumore: "
                           "la scheda lavora solo quanto serve. Le modifiche valgono subito, anche a gioco aperto."))
        cfg = common.load_config()
        c = Card(T("Limite FPS"), T("Vale per tutti i giochi. Un gioco con un profilo usa il limite del suo profilo."))
        self.enabled = QCheckBox()
        self.enabled.setChecked(cfg["engine"]["limit_enabled"])
        self.enabled.toggled.connect(self.save)
        c.lay.addWidget(row(T("Limite FPS attivo"), self.enabled, T("Shift+F1 lo accende e spegne mentre giochi.")))
        self.limit = limit_combo(cfg["engine"]["fps_limit"])
        self.limit.activated.connect(self.save)
        c.lay.addWidget(row(T("Limite per tutti i giochi"), self.limit,
                            T("I giochi con un profilo usano il limite del profilo. Con VRR attivo, "
                              "valori sotto i 165 Hz restano fluidi.")))
        self.engine = QCheckBox()
        self.engine.setChecked(cfg["engine"]["enabled"])
        self.engine.toggled.connect(self.save)
        c.lay.addWidget(row(T("Motore FPS attivo"), self.engine, T("Se lo spegni il gioco non viene più misurato né limitato.")))
        lay.addWidget(c)

        up = Card(T("Upscaling FSR (gamescope)"), T("Il gioco gira a una risoluzione più bassa e viene ingrandito con "
                  "FSR 1 fino a quella del monitor: più FPS e meno calore, con qualsiasi gioco."))
        up.lay.addWidget(label("<br>".join("• " + T(t) for t in (
            "Si sceglie per ogni gioco nel suo profilo (pagina Profili o Shift+F2 in gioco): 77% ultra qualità, "
            "67% qualità, 59% bilanciato, 50% prestazioni.",
            "Funziona solo con i giochi collegati (pagina Giochi), perché passa da bc250-run all'avvio.",
            "Vale dal prossimo avvio del gioco. Senza upscaling nel profilo il gioco parte normalmente.",
            "Se il gioco ha già FSR o DLSS nelle sue impostazioni, di solito conviene usare quello.")),
            9.5, P["MUTED"], wrap=True))
        lay.addWidget(up)

        mh = Card("MangoHud", T("Il vecchio overlay per FPS e limiti. Il motore BC-250 lo sostituisce: tenerli "
                                "entrambi attivi raddoppia il lavoro e può confondere il limite FPS."))
        self.mh = label("", 9.5, P["MUTED"], wrap=True)
        mh.lay.addWidget(self.mh)
        self.mh_btn = QCheckBox()
        self.mh_btn.setChecked(os.path.exists(common.MANGOHUD_FLAG))
        self.mh_btn.toggled.connect(self.toggle_mangohud)
        mh.lay.addWidget(row(T("Togli MangoHud dai giochi"), self.mh_btn,
                             T("Resta installato: puoi riattivarlo qui. Vale dal prossimo accesso alla sessione.")))
        lay.addWidget(mh)
        lay.addStretch()

    def save(self, *_):
        lim = self.limit.currentData()
        en, eng = self.enabled.isChecked(), self.engine.isChecked()
        cfg = common.update_config(lambda c: c["engine"].update(fps_limit=lim, limit_enabled=en, enabled=eng))
        e = cfg["engine"]
        write_control(e["fps_limit"], e["limit_enabled"], e["enabled"])
        self.win.toast(T("Limite FPS: {v}", v=lim) if lim and en else T("Limite FPS: disattivato"))

    def toggle_mangohud(self, on):
        if on:
            os.makedirs(common.CONF_DIR, exist_ok=True)
            open(common.MANGOHUD_FLAG, "w").close()
        elif os.path.exists(common.MANGOHUD_FLAG):
            os.remove(common.MANGOHUD_FLAG)
        self.win.toast(T("Salvato: vale dal prossimo accesso alla sessione."))

    def refresh(self, st):
        mh = health.mangohud_global() if int(time.time()) % 10 == 0 or not self.mh.text() else None
        if mh is not None:
            self.mh.setText(T("MangoHud è ancora caricato nella sessione attuale.") if mh
                            else T("MangoHud non viene più caricato nei giochi."))


class LibraryPage:
    """Tutti i giochi: installati (Steam, Lutris, Heroic, non Steam dentro Steam) e rilevati quando partono.
    Spunta = collegato (parte con bc250-run: profilo, upscaling FSR)."""
    FILTERS = [("all", "Tutti"), ("pending", "Nuovi"), ("linked", "Collegati"), ("unlinked", "Non collegati"),
               ("seen", "Rilevati in gioco")]

    def __init__(self, win):
        self.win = win
        self.w, lay = page(T("Giochi"), T("Tutti i tuoi giochi: quelli installati e quelli rilevati quando li avvii "
                                          "(anche fuori da Steam, per esempio da uno script o da distrobox). Spunta un "
                                          "gioco per collegarlo: parte con bc250-run e può usare il profilo e "
                                          "l'upscaling FSR."))
        self.live = label("", 10, wrap=True)
        lc = Card(T("In esecuzione adesso"), T("I giochi che stanno disegnando frame, con il limite FPS applicato."))
        lc.lay.addWidget(self.live)
        lay.addWidget(lc)

        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(T("Cerca un gioco…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        top.addWidget(self.search, 1)
        self.filter = QComboBox()
        for k, t in self.FILTERS:
            self.filter.addItem(T(t), k)
        self.filter.activated.connect(self.apply_filter)
        top.addWidget(self.filter)
        lay.addLayout(top)

        gc = Card()
        self.glist = QListWidget()
        self.glist.setObjectName("items")
        self.glist.setMinimumHeight(420)
        self.glist.itemChanged.connect(self.game_toggled)
        self.glist.currentItemChanged.connect(self.show_details)
        gc.lay.addWidget(self.glist)
        self.details = label("", 9, P["MUTED"], wrap=True)
        gc.lay.addWidget(self.details)
        btns = QHBoxLayout()
        for text, fn in ((T("Collega tutti"), lambda: self.link_all(True)),
                         (T("Scollega tutti"), lambda: self.link_all(False)),
                         (T("Aggiorna"), self.load_games)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        gc.lay.addLayout(btns)
        lay.addWidget(gc)

        mc = Card(T("Giochi nuovi"))
        self.mode = QComboBox()
        for k, t in (("ask", "Aggiungili qui come «nuovi», li collego io"), ("auto", "Collegali da soli"),
                     ("off", "Non fare niente")):
            self.mode.addItem(T(t), k)
        self.mode.setCurrentIndex(max(0, self.mode.findData(common.load_config().get("launcher", {}).get("mode", "ask"))))
        self.mode.activated.connect(lambda *_: common.update_config(
            lambda c: c.setdefault("launcher", {}).update(mode=self.mode.currentData())))
        mc.lay.addWidget(row(T("Quando installi o avvii un gioco nuovo"), self.mode,
                             T("Nessuna notifica durante il gioco: i nuovi compaiono qui, con il numero accanto a "
                               "«Giochi» nel menu.")))
        lay.addWidget(mc)

        hand = Card(T("Collegare un gioco a mano"), T("Per i giochi che la lista non trova, o se preferisci farlo tu: "
                    "copia il testo nelle opzioni di avvio del gioco."))
        run = QLineEdit("bc250-run %command%")
        run.setReadOnly(True)
        run.setMinimumWidth(220)
        hand.lay.addWidget(row(T("Opzioni di avvio"), run,
                               T("Steam: Proprietà → Opzioni di avvio. Lutris/Heroic: «prefisso del comando» = bc250-run.")))
        lay.addWidget(hand)

        gl = Card(T("Compatibilità OpenGL"), T("I giochi Vulkan e Proton (quasi tutti quelli Steam) sono misurati in "
                  "automatico. I pochi giochi OpenGL vanno attivati uno per uno, altrimenti non vedi i loro FPS "
                  "e il limite non si applica."))
        for app in FLATPAK_GL_APPS + other_flatpaks():
            cb = QCheckBox()
            cb.setChecked(flatpak_gl_enabled(app))
            cb.toggled.connect(lambda on, a=app: (flatpak_gl(a, on), win.toast(T("{a}: riavvia l'app per applicare.", a=a))))
            gl.lay.addWidget(row(app, cb, T("App Flatpak — vale dal prossimo avvio.")))
        steam = QLineEdit("bc250-gl %command%")
        steam.setReadOnly(True)
        steam.setMinimumWidth(220)
        gl.lay.addWidget(row(T("Giochi Steam OpenGL nativi"), steam,
                             T("Copia questo testo in Proprietà → Opzioni di avvio del gioco.")))
        lay.addWidget(gl)
        lay.addStretch()
        self.launch_result = None
        self.known = {}
        self.load_games()

    def apply_filter(self, *_):
        q = self.search.text().strip().lower()
        f = self.filter.currentData()
        for i in range(self.glist.count()):
            it = self.glist.item(i)
            k = it.data(Qt.ItemDataRole.UserRole)
            g = self.known.get(k, {})
            st = g.get("status")
            ok = (f == "all" or (f == "pending" and st == "pending") or (f == "linked" and st in ("linked", "queued"))
                  or (f == "unlinked" and st not in ("linked", "queued")) or (f == "seen" and k.startswith("seen:")))
            text = f"{g.get('name', '')} {g.get('store', '')} {g.get('process', '')}".lower()
            it.setHidden(bool(not ok or (q and q not in text)))

    def show_details(self, it, *_):
        if not it:
            self.details.setText("")
            return
        k = it.data(Qt.ItemDataRole.UserRole)
        g = self.known.get(k, {})
        parts = [f"<b>{g.get('name', k)}</b> · {g.get('store', '')}"]
        launch = g.get("launch") or {}
        if launch.get("cmd"):
            cmd = " ".join(launch["cmd"])
            parts.append(T("Avviato con: {c}", c=(cmd[:160] + "…") if len(cmd) > 160 else cmd))
            if launch.get("container"):
                parts.append(T("Dentro il container distrobox «{c}».", c=launch["container"]))
        if k.startswith("seen:"):
            parts.append(T("Collegandolo crei «{n} (BC-250)» nel menu delle applicazioni: avvialo da lì per usare "
                           "profilo e upscaling.", n=g.get("name", "")))
        elif k.startswith(("steam:", "shortcut:")):
            parts.append(T("Collegarlo scrive bc250-run nelle opzioni di avvio di Steam (le tue opzioni restano)."))
        self.details.setText("<br>".join(parts))

    def load_games(self):
        from . import launchers
        try:
            launchers.scan(common.load_config().get("launcher", {}).get("mode", "ask"))
        except Exception as e:
            print("scan:", e, file=sys.stderr)
        known = launchers.load_known()
        self.known = known
        self.glist.blockSignals(True)
        self.glist.clear()
        labels = {"linked": "", "pending": T("nuovo"), "queued": T("alla chiusura di Steam"), "ignored": ""}
        for k, g in sorted(known.items(), key=lambda kv: (kv[1].get("status") != "pending", kv[1].get("name", "").lower())):
            st = g.get("status")
            extra = labels.get(st, "")
            it = QListWidgetItem(f"{g.get('name', k)}   ·   {g.get('store', '')}" + (f"   ·   {extra}" if extra else ""))
            it.setData(Qt.ItemDataRole.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if st in ("linked", "queued") else Qt.CheckState.Unchecked)
            if st == "pending":
                it.setForeground(QColor(P["WARN"]))
            self.glist.addItem(it)
        self.glist.blockSignals(False)
        self.apply_filter()

    def game_toggled(self, it):
        self.do_link([it.data(Qt.ItemDataRole.UserRole)], it.checkState() == Qt.CheckState.Checked)

    def do_link(self, keys, on):
        """Collega/scollega; per Steam aperto chiede se riavviarlo ora o farlo alla chiusura."""
        from . import launchers
        restart = False
        if any(k.startswith("steam:") for k in keys) and launchers.steam_pids():
            r = QMessageBox.question(self.w, "BC-250", T("Steam è aperto e scrive le opzioni di avvio quando si chiude. "
                                     "Lo riavvio adesso (qualche secondo)? Con «No» lo faccio alla prossima chiusura di Steam."))
            restart = r == QMessageBox.StandardButton.Yes

        steam_open = bool(launchers.steam_pids())
        if not on and steam_open and not restart:
            # scollegare un gioco Steam si può solo a Steam chiuso: per ora restano collegati
            keys = [k for k in keys if not k.startswith("steam:")]
            self.win.toast(T("Per scollegare i giochi Steam serve chiudere Steam: riprova e scegli «Sì»."))
            if not keys:
                self.load_games()
                return

        def work():
            try:
                done, queued = launchers.link(keys, on, restart_steam=restart)
                self.launch_result = (T("Collegati: {n}.", n=len(done)) if on else T("Scollegati: {n}.", n=len(done))) + \
                    (" " + T("{n} di Steam alla prossima chiusura di Steam.", n=len(queued)) if queued else "")
            except Exception as e:
                self.launch_result = str(e)
        self.launch_result = None
        threading.Thread(target=work, daemon=True).start()
        self.wait_result()

    def wait_result(self):
        if self.launch_result is None:
            QTimer.singleShot(400, self.wait_result)
        else:
            self.win.toast(self.launch_result)
            self.load_games()
            self.win.check_new_games(force=True)

    def link_all(self, on):
        from . import launchers
        msg = T("Steam verrà chiuso e riaperto per scrivere le opzioni di avvio. Se stai giocando, chiudi "
                "prima il gioco. Continuo?") if on else \
            T("Tolgo bc250-run dalle opzioni di avvio di tutti i giochi (Steam si chiude e riapre). Continuo?")
        if QMessageBox.question(self.w, "BC-250", msg) != QMessageBox.StandardButton.Yes:
            return
        self.win.toast(T("Aggiorno le opzioni di avvio…"))

        def work():
            res = launchers.apply_all(on)
            known = launchers.load_known()
            for k in known:
                known[k]["status"] = "linked" if on else "ignored"
            launchers.save_known(known)
            n = len(res["steam"]) + len(res["lutris"]) + len(res["heroic"])
            self.launch_result = T("Opzioni di avvio aggiornate: {n} giochi.", n=n) + \
                (" " + "; ".join(res["errors"]) if res["errors"] else "")
        self.launch_result = None
        threading.Thread(target=work, daemon=True).start()
        self.wait_result()

    def refresh(self, st):
        gs = st.get("games") or []
        g = st.get("game")
        if gs:
            self.live.setText("<br>".join(
                f"<b>{x['name']}</b> <span style='color:{P['MUTED']}'>{x['api']}</span> — {x['fps']:.0f} FPS"
                + (" · " + T("limite applicato <b>{v}</b>", v=g["limit"])
                   if g and g['name'] == x['name'] and g.get('limit') else "")
                for x in gs))
        else:
            self.live.setText(f"<span style='color:{P['MUTED']}'>{T('Nessun gioco sta disegnando frame.')}</span>")


class ProfilesPage:
    COLS = ["Nome", "Riconosci (processo o appid:ID)"] + [f[1] for f in common.PROFILE_FIELDS] + ["Note"]

    def __init__(self, win):
        self.win = win
        self.w, lay = page(T("Profili per gioco"), T("Quando un gioco parte, il suo profilo imposta limite FPS, clock GPU, "
                           "VRR, protezione calore e overlay. Alla chiusura torna tutto normale. "
                           "Puoi modificarli anche in gioco con Shift+F2."))
        c = Card(T("I tuoi profili"), T("Una riga per gioco. «Salva» rende effettive le modifiche: se il gioco è "
                                        "aperto valgono subito, tranne l'upscaling (dal prossimo avvio)."))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([T(c) for c in self.COLS])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(len(self.COLS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        c.lay.addWidget(self.table)
        btns = QHBoxLayout()
        for text, fn, obj in (("Aggiungi", self.add, None), ("Dal gioco in corso", self.add_current, None),
                              ("Elimina", self.delete, "danger"), ("Salva", self.save, "primary")):
            b = QPushButton(T(text))
            if obj:
                b.setObjectName(obj)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch()
        c.lay.addLayout(btns)
        lay.addWidget(c)

        h = Card(T("Cosa fa ogni colonna"))
        h.lay.addWidget(label("<br>".join(
            f"<b style='color:{P['TEXT']}'>{T(k)}</b> — {T(v)}" for k, v in (
                ("Riconosci", "come trovare il gioco: il nome del processo (per esempio HytaleClient) oppure "
                              "appid:NUMERO per Steam. «Dal gioco in corso» lo compila da solo."),
                ("Limite FPS", "«globale» usa il limite della pagina FPS e upscaling, «nessuno» lo toglie."),
                ("Clock GPU max", "tetto del clock GPU mentre il gioco è aperto. Più basso = meno calore, "
                                  "spesso senza perdere FPS nei giochi leggeri o già limitati."),
                ("VRR", "accende FreeSync solo per questo gioco. Su molti monitor lo schermo diventa nero per un "
                        "attimo all'avvio e alla chiusura."),
                ("Protezione calore", "se la CPU supera la soglia, il limite FPS scende di 10 ogni 20 s; "
                                      "risale quando la CPU torna 8°C sotto."),
                ("Overlay, Posizione overlay, Stile overlay", "cambiano l'overlay solo per questo gioco, "
                                                               "al posto delle impostazioni della pagina Overlay."),
                ("Upscaling FSR", "risoluzione ridotta e ingrandita con FSR 1. Serve il gioco collegato "
                                  "(pagina Giochi); vale dal prossimo avvio."),
                ("Frequenza CPU max", "tetto di frequenza della CPU mentre il gioco è aperto: «globale» usa quello "
                                      "della pagina Scheda. Serve cpufreq (pagina Scheda)."))
        ), 9.5, P["MUTED"], wrap=True))
        lay.addWidget(h)
        lay.addStretch()
        self.extra = []  # campi del profilo non mostrati in tabella, da conservare
        self.load()

    def load(self):
        profs = common.load_config()["profiles"]
        self.table.setRowCount(0)
        self.extra = []
        for p in profs:
            self.add_row(p)
        QTimer.singleShot(0, self.fit_table)

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
        self.fit_table()
        known = {"name", "match", "notes"} | {f[0] for f in common.PROFILE_FIELDS}
        self.extra.append({k: v for k, v in p.items() if k not in known})

    def fit_table(self):
        """Tabella alta quanto le sue righe: niente spazio vuoto nella card."""
        t = self.table
        h = t.horizontalHeader().height() + t.rowCount() * t.verticalHeader().defaultSectionSize() + 4
        if t.horizontalScrollBar().isVisible() or t.horizontalHeader().length() > t.viewport().width():
            h += t.horizontalScrollBar().sizeHint().height()
        t.setFixedHeight(max(h, 90))

    def add(self):
        self.add_row({"name": T("Nuovo gioco"), "match": ""})

    def add_current(self):
        g = common.read_state().get("game")
        if not g:
            self.win.toast(T("Nessun gioco in corso."))
            return
        match = f"appid:{g['appid']}" if g.get("appid") else g["name"]
        self.add_row({"name": g["name"].removesuffix(".exe"), "match": match})

    def delete(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
            if r < len(self.extra):
                self.extra.pop(r)
        self.fit_table()

    def save(self):
        profs = []
        for r in range(self.table.rowCount()):
            def text(c, r=r):
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
        self.win.toast(T("{n} profili salvati.", n=len(profs)))

    def refresh(self, st):
        pass


class BoardPage:
    """La scheda: clock GPU senza profilo, stato del governor e della CPU (solo lettura da sysfs)."""

    def __init__(self, win):
        self.win = win
        self.w, lay = page(T("Scheda"), T("Come lavorano GPU e CPU quando nessun profilo dice altro. Sulla BC-250 il "
                           "limite vero è il raffreddamento: meno clock vuol dire meno calore."))
        d = Card(T("Clock GPU"), T("Il governor alza e abbassa il clock in base al carico, dentro questo intervallo. "
                                   "Un profilo può usare un massimo diverso per il suo gioco."))
        cfg = common.load_config()
        self.gmin, self.gmax = QSpinBox(), QSpinBox()
        for sb, v in ((self.gmin, cfg["gpu_default"]["min"]), (self.gmax, cfg["gpu_default"]["max"])):
            sb.setRange(500, 2000)
            sb.setSingleStep(25)
            sb.setSuffix(" MHz")
            sb.setValue(v)
        d.lay.addWidget(row(T("Minimo"), self.gmin, T("Il clock a riposo.")))
        d.lay.addWidget(row(T("Massimo"), self.gmax, T("Più alto = più FPS ma più calore. Il governor taglia comunque "
                            "a 85°C. Con una sola ventola, 1750 è un buon compromesso.")))
        b = QPushButton(T("Applica"))
        b.setObjectName("primary")
        b.clicked.connect(self.apply_default)
        d.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignRight)
        lay.addWidget(d)

        g = Card(T("Governor GPU"), T("Il servizio che regola il clock della GPU. Sopra la soglia di taglio scende "
                                      "al minimo finché la GPU non torna alla temperatura di ripresa."))
        self.gov = label("", 10, wrap=True)
        g.lay.addWidget(self.gov)
        lay.addWidget(g)

        c = Card(T("CPU"), T("Nei giochi che scaldano molto la CPU (per esempio Cyberpunk) un tetto di frequenza "
                             "toglie molti gradi perdendo pochi FPS. Un profilo può usare un tetto diverso."))
        self.cpu = label("", 10, wrap=True)
        c.lay.addWidget(self.cpu)
        info = common.cpufreq_info()
        self.cpumax = QComboBox()
        self.cpumax.addItem(T("Nessun limite"), None)
        for mhz in (info or {}).get("steps", [])[1:]:
            self.cpumax.addItem(f"{mhz} MHz", mhz)
        cur = (cfg.get("cpu") or {}).get("max_mhz")
        self.cpumax.setCurrentIndex(max(0, self.cpumax.findData(cur)))
        self.cpumax.setEnabled(bool(info))
        self.cpumax.activated.connect(self.save_cpu)
        c.lay.addWidget(row(T("Frequenza CPU massima"), self.cpumax,
                            T("2550 MHz è il punto consigliato dalle misure della community: molto meno calore, "
                              "prestazioni quasi uguali.") if info else
                            T("Non disponibile: manca il driver cpufreq (vedi docs/cpu.md).")))
        lay.addWidget(c)
        lay.addStretch()

    def save_cpu(self, *_):
        mhz = self.cpumax.currentData()
        common.update_config(lambda c: c.setdefault("cpu", {}).update(max_mhz=mhz))
        self.win.toast(T("Frequenza CPU massima: {v}", v=f"{mhz} MHz" if mhz else T("nessun limite")))

    def apply_default(self):
        mn, mx = self.gmin.value(), self.gmax.value()
        if mn > mx:
            mn = mx
        common.update_config(lambda c: c.update(gpu_default={"min": mn, "max": mx}))
        ok = governor_set(mn, mx)
        self.win.toast(T("Clock GPU {a}–{b} MHz", a=mn, b=mx) + ("" if ok else " " + T("(governor non raggiungibile!)")))

    @staticmethod
    def read(path):
        try:
            with open(path) as f:
                return f.read().strip()
        except OSError:
            return None

    def refresh(self, st):
        g = st.get("governor") or {}
        m = P["MUTED"]
        self.gov.setText("<br>".join([
            f"<span style='color:{m}'>{T('Intervallo attuale')}</span> <b>{g.get('min') or '?'}–{g.get('max') or '?'} MHz</b>",
            f"<span style='color:{m}'>{T('Taglio a')}</span> <b>{g.get('throttle') or '?'}°C</b> "
            f"<span style='color:{m}'>{T('ripresa')}</span> <b>{g.get('recovery') or '?'}°C</b>",
            f"<span style='color:{m}'>{T('Stato')}</span> <b style='color:{P['BAD'] if st.get('throttling') else P['GOOD']}'>"
            f"{T('sta tagliando il clock') if st.get('throttling') else T('normale')}</b>"]))
        s = st.get("sensors") or {}
        idle = self.read("/sys/devices/system/cpu/cpuidle/current_driver")
        freq = os.path.exists("/sys/devices/system/cpu/cpu0/cpufreq")
        good, warn = P["GOOD"], P["WARN"]
        idle_txt = (f"<b style='color:{good}'>{T('attivi')}</b> ({idle})" if idle and idle != "none"
                    else f"<b style='color:{warn}'>{T('non attivi')}</b>")
        cf = st.get("cpufreq") or common.cpufreq_info()
        if freq and cf:
            freq_txt = (f"<b style='color:{good}'>{T('attiva')}</b> ({cf['driver']}, "
                        + T("ora al massimo {v} MHz", v=cf["max"]) + ")")
            if not cf["writable"]:
                freq_txt += f" · <b style='color:{warn}'>{T('il servizio bc250-cpufreq non è installato')}</b>"
        else:
            freq_txt = f"<b style='color:{warn}'>{T('non disponibile')}</b>"
        nc = s.get("cores") or 0
        self.cpu.setText("<br>".join([
            f"<span style='color:{m}'>{T('Core')}</span> <b>{nc} / {s.get('threads') or 0} thread</b>"
            + (" · " + T("sblocco 8 core attivo") if nc >= 8 else ""),
            f"<span style='color:{m}'>{T('Stati di riposo (C-state)')}</span> {idle_txt}",
            f"<span style='color:{m}'>{T('Regolazione frequenza (cpufreq)')}</span> {freq_txt}",
            f"<span style='color:{P['DIM']}; font-size:9pt'>" + (
                T("Senza C-state e cpufreq la CPU resta sempre alla frequenza massima. Il BIOS della BC-250 non li "
                  "espone correttamente: la community ha un fix delle tabelle ACPI (vedi docs/cpu.md).")
                if not freq else T("La frequenza CPU si può limitare: utile nei giochi che scaldano molto la CPU."))
            + "</span>"]))
        if cf and not self.cpumax.view().isVisible():
            want = (common.load_config().get("cpu") or {}).get("max_mhz")
            self.cpumax.setCurrentIndex(max(0, self.cpumax.findData(want)))


ITEMS = [("fps", "FPS"), ("frametime", "Grafico frametime"), ("low1", "1% low"), ("cpu_temp", "Temperatura CPU"),
         ("gpu_temp", "Temperatura GPU"), ("gpu_clk", "Clock GPU"), ("power", "Consumo"), ("gpu_busy", "Carico GPU"),
         ("cpu_load", "Carico CPU"), ("fan", "Ventola"), ("ram", "RAM"), ("vram", "VRAM"),
         ("ft", "Frametime (ms)"), ("cpu_clk", "Clock CPU")]
POSITIONS = [("In alto a sinistra", "top-left"), ("In alto al centro", "top-center"),
             ("In alto a destra", "top-right"), ("In basso a sinistra", "bottom-left"),
             ("In basso al centro", "bottom-center"), ("In basso a destra", "bottom-right")]


class HudPreview(QWidget):
    """Anteprima dell'overlay così come appare in gioco, a grandezza reale, sopra uno sfondo da gioco."""
    PAD = 18

    def __init__(self):
        super().__init__()
        self.cfg = common.load_config()
        self.painter = HudPainter()
        self.scenario = "auto"
        self.live = {}
        self.st = {}
        self.last_upd = 0.0
        self.last_paint = 0.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(33)
        self.refresh_state()
        self.painter.settle()
        self.fix_height()

    def set_cfg(self, cfg):
        self.cfg = cfg
        self.refresh_state()
        self.fix_height()
        self.update()

    def set_live(self, st):
        self.live = st

    def refresh_state(self):
        live = self.live if self.scenario == "auto" and self.live.get("game") and \
            time.time() - self.live.get("ts", 0) < 5 else None
        self.st = live or demo_state("ok" if self.scenario == "auto" else self.scenario, self.cfg)
        self.painter.update(self.st, self.cfg)

    def tick(self):
        if not self.isVisible():
            return
        now = time.monotonic()
        if now - self.last_upd > 0.25:
            self.last_upd = now
            self.refresh_state()
        if self.painter.step() or now - self.last_paint > 0.25:
            self.last_paint = now
            self.fix_height()
            self.update()

    def fix_height(self):
        # altezza fissa sulla misura massima: la pagina non salta quando il cerchio si allarga
        h = self.painter.size(self.st, self.cfg, expanded=True)[1] + 2 * self.PAD
        if self.height() != h:
            self.setFixedHeight(h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        bg = QLinearGradient(r.topLeft(), r.bottomRight())
        bg.setColorAt(0, QColor("#2a3550"))
        bg.setColorAt(0.55, QColor("#7a4a3a"))
        bg.setColorAt(1, QColor("#2b2230"))
        p.setPen(QPen(QColor(P["BORDER"]), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 10, 10)
        o = self.cfg["overlay"]
        hw, hh = self.painter.size(self.st, self.cfg)
        pos = o.get("position", "top-left")
        x = r.right() - self.PAD - hw if pos.endswith("right") else \
            r.left() + (r.width() - hw) / 2 if pos.endswith("center") else r.left() + self.PAD
        y = r.bottom() - self.PAD - hh if pos.startswith("bottom") else r.top() + self.PAD
        p.save()
        p.translate(x, y)
        self.painter.paint(p, self.st, self.cfg, hw, hh)
        p.restore()
        if not o["hud_visible"]:
            f = QFont()
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(P["TEXT"]))
            p.drawText(r.adjusted(14, 8, -14, -8), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom,
                       T("Overlay spento: in gioco non si vede (Shift+F3 per accenderlo)"))
        p.end()


class OverlayPage:
    def __init__(self, win):
        self.win = win
        self.loading = True
        self.w, lay = page(T("Overlay"), T("Cosa vedi sopra i giochi. Con il «cerchio intelligente» resta piccolo "
                           "in un angolo e si allarga solo quando qualcosa richiede attenzione."))
        o = common.load_config()["overlay"]
        b = o["bubble"]

        c = Card(T("Comandi in gioco"), T("Funzionano sopra qualsiasi gioco, anche a schermo intero."))
        for keys, what in (("Shift+F1", "Accende e spegne il limite FPS."),
                           ("Shift+F2", "Apre il pannello in basso: FPS, frametime, sensori e il profilo del gioco "
                                        "da modificare con le frecce. Esc lo chiude."),
                           ("Shift+F3", "Mostra o nasconde l'overlay.")):
            c.lay.addWidget(label(f"<b>{keys}</b>&nbsp;&nbsp;<span style='color:{P['MUTED']}'>{T(what)}</span>",
                                  10, wrap=True))
        c.lay.addWidget(label(T("Si cambiano in Impostazioni di sistema → Scorciatoie → «BC-250»."), 8.5, P["DIM"]))
        bt = QPushButton(T("Apri il pannello ora"))
        bt.clicked.connect(lambda: common.overlay_send("toggle-panel"))
        c.lay.addWidget(bt, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(c)

        pc = Card(T("Anteprima"), T("Com'è l'overlay in gioco, a grandezza reale. Cambia le impostazioni qui sotto "
                                    "e lo vedi subito."))
        self.scen = QComboBox()
        self.scen.addItem(T("Dati live (se stai giocando)"), "auto")
        for k, t in DEMOS:
            self.scen.addItem(T(t), k)
        self.scen.activated.connect(self.set_scenario)
        pc.lay.addWidget(row(T("Simula"), self.scen, T("Le demo mostrano come reagisce il cerchio, con gli stessi "
                             "tempi del gioco (si allarga dopo 1-2 s, si richiude dopo la tenuta).")))
        self.preview = HudPreview()
        pc.lay.addWidget(self.preview)
        lay.addWidget(pc)

        a = Card(T("Aspetto"), T("Stile, posizione e dimensione. Un profilo può cambiarli per il suo gioco."))
        self.visible = QCheckBox()
        self.visible.setChecked(o["hud_visible"])
        a.lay.addWidget(row(T("Overlay attivo"), self.visible, T("Shift+F3 lo accende e spegne anche in gioco.")))
        self.style = QComboBox()
        for k, t in STYLES:
            self.style.addItem(T(t), k)
        self.style.setCurrentIndex(max(0, self.style.findData(o.get("style", "bubble"))))
        a.lay.addWidget(row(T("Stile"), self.style, T("Cerchio: solo FPS, si allarga quando serve · Anello: FPS e fino a 8 valori "
                            "sempre visibili · Barra: una riga · Completo: grafico e tutte le metriche.")))
        self.only = QCheckBox()
        self.only.setChecked(o["only_in_game"])
        a.lay.addWidget(row(T("Solo mentre giochi"), self.only, T("Se spento resta sempre visibile sul desktop.")))
        self.pos = QComboBox()
        for t, v in POSITIONS:
            self.pos.addItem(T(t), v)
        self.pos.setCurrentIndex(max(0, self.pos.findData(o["position"])))
        a.lay.addWidget(row(T("Posizione"), self.pos, T("Un profilo può usare una posizione diversa per quel gioco.")))
        self.margin = QSpinBox()
        self.margin.setRange(0, 400)
        self.margin.setSuffix(" px")
        self.margin.setValue(int(o["margin"]))
        a.lay.addWidget(row(T("Distanza dal bordo"), self.margin))
        self.scale = QSlider(Qt.Orientation.Horizontal)
        self.scale.setRange(60, 200)
        self.scale.setValue(int(float(o["scale"]) * 100))
        self.scale.setFixedWidth(220)
        a.lay.addWidget(row(T("Dimensione"), self.scale))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(20, 100)
        self.opacity.setValue(int(float(o["opacity"]) * 100))
        self.opacity.setFixedWidth(220)
        a.lay.addWidget(row(T("Opacità sfondo"), self.opacity))
        lay.addWidget(a)

        self.bcard = Card(T("Cerchio e anello"), T("Quando il cerchio si allarga per segnalare un problema, e con "
                                                   "quali soglie. Vale anche per i colori dell'anello."))
        self.center = QComboBox()
        for k, t in CENTER:
            self.center.addItem(T(t), k)
        self.center.setCurrentIndex(max(0, self.center.findData(b.get("center", "fps"))))
        self.center_row = row(T("Valore nel cerchio"), self.center)
        self.bcard.lay.addWidget(self.center_row)
        self.idle = QComboBox()
        for k, t in IDLE:
            self.idle.addItem(T(t), k)
        self.idle.setCurrentIndex(max(0, self.idle.findData(b.get("idle", "visible"))))
        self.bcard.lay.addWidget(row(T("Quando va tutto bene"), self.idle,
                                     T("«Nascosto»: in gioco non vedi niente finché non c'è un problema.")))
        self.hold = QSpinBox()
        self.hold.setRange(2, 120)
        self.hold.setSuffix(" s")
        self.hold.setValue(int(b.get("hold_s", 8)))
        self.bcard.lay.addWidget(row(T("Resta allargato per"), self.hold, T("Dopo che il problema è sparito.")))
        self.bcard.lay.addWidget(label(T("SI ALLARGA QUANDO"), 8, P["MUTED"], True))
        grid = QGridLayout()
        self.watch = {}
        for i, (k, t) in enumerate(WATCH):
            cb = QCheckBox(T(t))
            cb.setChecked(k in b.get("watch", []))
            self.watch[k] = cb
            grid.addWidget(cb, i // 2, i % 2)
        self.bcard.lay.addLayout(grid)
        self.th = {}
        for k, text, rng, suf, hint in (
                ("cpu_temp", "CPU calda da", (60, 100), " °C", None),
                ("gpu_temp", "GPU calda da", (55, 95), " °C", "Il governor taglia il clock a 85°C."),
                ("fps_drop_pct", "FPS sotto l'obiettivo", (50, 99), " %", "Percentuale del limite FPS del gioco."),
                ("fps_min", "Obiettivo senza limite FPS", (20, 165), " FPS", None),
                ("stutter_pct", "Scatti: 1% low sotto", (20, 90), " % degli FPS", None),
                ("ram_pct", "RAM piena da", (70, 99), " %", None)):
            sb = QSpinBox()
            sb.setRange(*rng)
            sb.setSuffix(T(suf))
            sb.setValue(int(b.get(k, rng[0])))
            self.th[k] = sb
            self.bcard.lay.addWidget(row(T(text), sb, hint and T(hint)))
        lay.addWidget(self.bcard)

        self.icard = Card(T("Valori mostrati"), T("Spunta cosa vedere e trascina per cambiare l'ordine. "
                                                  "Anello: un arco per valore (da 2 a 8, si allarga da solo), "
                                                  "«Grafico frametime» va al centro sotto gli FPS."))
        self.items = QListWidget()
        self.items.setObjectName("items")
        self.items.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.items.setDefaultDropAction(Qt.DropAction.MoveAction)
        names = dict(ITEMS)
        order = [k for k in o["items"] if k in names] + [k for k, _ in ITEMS if k not in o["items"]]
        for k in order:
            it = QListWidgetItem(T(names[k]))
            it.setData(Qt.ItemDataRole.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsDragEnabled)
            it.setCheckState(Qt.CheckState.Checked if k in o["items"] else Qt.CheckState.Unchecked)
            self.items.addItem(it)
        self.items.setFixedHeight(self.items.count() * (max(24, self.items.sizeHintForRow(0)) + 2) + 14)
        self.icard.lay.addWidget(self.items)
        lay.addWidget(self.icard)

        lk = {**LOOK_DEFAULT, **(o.get("look") or {})}
        self.lcard = Card(T("Aspetto dei valori"), T("Etichette, bordo e colori dei numeri nell'overlay."))
        self.labels, self.border, self.badge = QCheckBox(), QCheckBox(), QCheckBox()
        for cb, key, text, hint in (
                (self.labels, "labels", "Etichette", "CPU, GPU, W… sotto o accanto ai numeri."),
                (self.border, "border", "Bordo colorato", None),
                (self.badge, "limit_badge", "Mostra il limite FPS", "⏵ 90 accanto agli FPS, ∞ senza limite.")):
            cb.setChecked(bool(lk[key]))
            self.lcard.lay.addWidget(row(T(text), cb, hint and T(hint)))
        self.colors = QComboBox()
        self.colors.addItem(T("A semaforo (verde, arancio, rosso)"), "status")
        self.colors.addItem(T("Monocromatico (colorati solo i problemi)"), "mono")
        self.colors.setCurrentIndex(max(0, self.colors.findData(lk["colors"])))
        self.lcard.lay.addWidget(row(T("Colori"), self.colors))
        self.accent = QComboBox()
        for col, name in ACCENTS:
            pm = QPixmap(14, 14)
            pm.fill(QColor(col))
            self.accent.addItem(QIcon(pm), T(name), col)
        self.accent.setCurrentIndex(max(0, self.accent.findData(lk["accent"])))
        self.lcard.lay.addWidget(row(T("Colore principale"), self.accent, T("Bordo, limite FPS e valori in monocromatico.")))
        lay.addWidget(self.lcard)

        for w in [self.visible, self.only, self.labels, self.border, self.badge] + list(self.watch.values()):
            w.toggled.connect(self.save)
        for w in [self.pos, self.style, self.center, self.idle, self.colors, self.accent]:
            w.activated.connect(self.save)
        self.items.itemChanged.connect(self.save)
        self.items.model().rowsMoved.connect(self.save)
        for w in [self.margin, self.scale, self.opacity, self.hold] + list(self.th.values()):
            w.valueChanged.connect(self.save)
        lay.addStretch()
        self.loading = False
        self.sync_cards()

    def sync_cards(self):
        style = self.style.currentData()
        round_ = style in ("bubble", "ring")
        self.bcard.setVisible(round_)
        self.icard.setVisible(style != "bubble")
        self.center_row.setVisible(style == "bubble")

    def set_scenario(self, *_):
        self.preview.scenario = self.scen.currentData()
        self.preview.refresh_state()

    def save(self, *_):
        if self.loading:
            return
        items = [self.items.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.items.count())
                 if self.items.item(i).checkState() == Qt.CheckState.Checked]
        lk = {"labels": self.labels.isChecked(), "border": self.border.isChecked(),
              "limit_badge": self.badge.isChecked(), "colors": self.colors.currentData(),
              "accent": self.accent.currentData()}
        bub = {"center": self.center.currentData(), "idle": self.idle.currentData(), "hold_s": self.hold.value(),
               "watch": [k for k, _ in WATCH if self.watch[k].isChecked()],
               **{k: sb.value() for k, sb in self.th.items()}}

        def fn(c):
            c["overlay"].update(
                hud_visible=self.visible.isChecked(), only_in_game=self.only.isChecked(),
                position=self.pos.currentData(), margin=self.margin.value(), style=self.style.currentData(),
                scale=self.scale.value() / 100, opacity=self.opacity.value() / 100, items=items)
            c["overlay"].setdefault("bubble", {}).update(bub)
            c["overlay"]["look"] = lk
        cfg = common.update_config(fn)
        self.sync_cards()
        self.preview.set_cfg(cfg)

    def refresh(self, st):
        self.preview.set_live(st)


class DisplayPage:
    def __init__(self, win):
        self.win = win
        self.w, self.lay = page(T("Display"), T("VRR (FreeSync): il monitor si adatta agli FPS del gioco. "
                                "Niente tearing e niente scatti anche sotto i 165 Hz. Funziona nei giochi a schermo intero."))
        auto = Card(T("Automatico"), T("Il modo consigliato: VRR acceso solo mentre giochi, così il desktop non "
                                       "sfarfalla. Un profilo può accenderlo o no per il suo gioco."))
        self.games_only = QCheckBox()
        self.games_only.setChecked(common.load_config()["display"]["vrr_games_only"])
        self.games_only.toggled.connect(self.save_auto)
        auto.lay.addWidget(row(T("VRR solo nei giochi"), self.games_only,
                               T("Il servizio BC-250 lo accende quando parte un gioco e lo spegne alla chiusura "
                                 "(schermo nero per un attimo). Il gioco deve essere a schermo intero.")))
        self.lay.addWidget(auto)
        self.box = QVBoxLayout()
        self.lay.addLayout(self.box)
        self.lay.addStretch()
        self.build()

    def save_auto(self, on):
        common.update_config(lambda c: c["display"].update(vrr_games_only=on))
        self.win.toast(T("VRR solo nei giochi: attivo") if on else
                       T("VRR solo nei giochi: disattivato (lo gestisci a mano qui sotto)"))

    def build(self):
        while self.box.count():
            it = self.box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for o in health.vrr_outputs():
            c = Card(T("Schermo {n} — {m} Hz", n=o['name'], m=o['mode']),
                     T("Impostazioni manuali di questo monitor. KDE chiede conferma se la modalità non funziona."))
            vrr = QComboBox()
            for t, v in (("Mai", "never"), ("Automatico (giochi a schermo intero)", "automatic"), ("Sempre", "always")):
                vrr.addItem(T(t), v)
            vrr.setCurrentIndex(max(0, vrr.findData(o["vrr"])))
            vrr.activated.connect(lambda _, name=o["name"], cb=vrr: self.set_vrr(name, cb.currentData()))
            c.lay.addWidget(row(T("VRR / FreeSync (manuale)"), vrr, T("Con «VRR solo nei giochi» attivo lo decide il servizio. "
                                "Su alcuni monitor il VRR fa sfarfallare il desktop.")))
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
            c.lay.addWidget(row(T("Risoluzione e frequenza"), modes))
            self.box.addWidget(c)

    def set_vrr(self, name, policy):
        ok = health.set_vrr(name, policy)
        self.win.toast(f"VRR {name}: {policy}" if ok else T("Errore nel cambiare il VRR"))

    def set_mode(self, name, mode_id):
        ok = health.sh(["kscreen-doctor", f"output.{name}.mode.{mode_id}"])[0] == 0
        self.win.toast(T("Modalità cambiata (KDE chiede conferma se serve).") if ok else T("Errore"))
        QTimer.singleShot(1500, self.build)

    def refresh(self, st):
        pass


class HealthPage:
    def __init__(self, win):
        self.win = win
        self.w, self.lay = page(T("Salute e avvisi"), T("Controlli per assicurarti che la BC-250 giri al meglio, "
                                "e gli avvisi quando qualcosa va storto."))
        b = QPushButton(T("Ricontrolla"))
        b.setObjectName("primary")
        b.clicked.connect(self.build)
        self.lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.box = QVBoxLayout()
        self.box.setSpacing(8)
        self.lay.addLayout(self.box)
        self.lay.addWidget(self.alerts_card())
        tips = Card(T("Consigli"), T("Cosa rende di più per temperature e FPS su questa scheda."))
        tips.lay.addWidget(label("<br>".join("• " + T(t) for t in (
            "La ventola è una sola e gira sempre al massimo: il limite vero è il raffreddamento. "
            "Una seconda ventola sul dissipatore o una più potente è l'upgrade che rende di più.",
            "Pasta termica nuova e dissipatore pulito: −5/−10°C tipici su queste schede.",
            "Usa un limite FPS (60–90) con VRR: meno calore, stessa fluidità percepita.",
            "Nei giochi con generazione del mondo (Hytale, Minecraft) abbassa la distanza visiva: pesa sulla CPU.",
            "Profili per gioco: clock GPU più basso nei giochi leggeri = scheda più fresca.")),
            9.5, P["MUTED"], wrap=True))
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
        self.win.toast(msg if ok else T("Non riuscito: {m}", m=msg))
        QTimer.singleShot(1500, self.build)

    def alerts_card(self):
        a = common.load_config()["alerts"]
        c = Card(T("Avvisi"), T("Notifica sul desktop e messaggio sopra il gioco quando una soglia viene superata."))
        self.en = QCheckBox()
        self.en.setChecked(a["enabled"])
        c.lay.addWidget(row(T("Avvisi attivi"), self.en))
        self.cpu, self.gpu, self.fan, self.cool = QSpinBox(), QSpinBox(), QSpinBox(), QSpinBox()
        for sb, rng, suf, v in ((self.cpu, (60, 100), " °C", a["cpu_temp"]), (self.gpu, (60, 100), " °C", a["gpu_temp"]),
                                (self.fan, (0, 3000), " rpm", a["fan_min_rpm"]),
                                (self.cool, (30, 3600), " s", a["cooldown_s"])):
            sb.setRange(*rng)
            sb.setSuffix(suf)
            sb.setValue(int(v))
        c.lay.addWidget(row(T("CPU oltre"), self.cpu, T("La CPU (Zen 2) è al limite a 97°C.")))
        c.lay.addWidget(row(T("GPU oltre"), self.gpu, T("Il governor taglia il clock a 85°C.")))
        c.lay.addWidget(row(T("Ventola sotto"), self.fan, T("La ventola di serie gira a circa 1000 rpm: sotto questa soglia è ferma o guasta.")))
        c.lay.addWidget(row(T("Non ripetere prima di"), self.cool, T("Lo stesso avviso non torna prima di questo tempo.")))
        btns = QHBoxLayout()
        t = QPushButton(T("Prova una notifica"))
        t.clicked.connect(lambda: subprocess.Popen(["notify-send", "-a", "BC-250", "BC-250", T("Le notifiche funzionano.")]))
        btns.addWidget(t)
        btns.addStretch()
        s = QPushButton(T("Salva"))
        s.setObjectName("primary")
        s.clicked.connect(self.save_alerts)
        btns.addWidget(s)
        c.lay.addLayout(btns)
        return c

    def save_alerts(self):
        common.update_config(lambda c: c["alerts"].update(
            enabled=self.en.isChecked(), cpu_temp=self.cpu.value(), gpu_temp=self.gpu.value(),
            fan_min_rpm=self.fan.value(), cooldown_s=self.cool.value()))
        self.win.toast(T("Avvisi salvati."))

    def refresh(self, st):
        pass


def fmt_dur(sec):
    m = int(round(sec / 60))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


# giorni scritti qui e non con %a: così seguono la lingua dell'app e non quella del sistema
DAYS = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def day_time(t):
    lt = time.localtime(t)
    return T(DAYS[lt.tm_wday]) + time.strftime(' %d/%m %H:%M', lt)


def game_title(name):
    return (name or "?").removesuffix(".exe")


class HistoryPage:
    def __init__(self, win):
        self.win = win
        self.w, lay = page(T("Storico partite"), T("Partite raggruppate per gioco: scegli un gioco per il riepilogo "
                           "di tutte le sessioni, o una sessione per il dettaglio. Se esci dal gioco (alt+tab, "
                           "caricamenti) e torni entro 5 minuti è la stessa sessione. "
                           "I segni viola li aggiunge Claude durante i test."))
        top = QHBoxLayout()
        self.tree = QTreeWidget()
        self.tree.setObjectName("hist")
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(320)
        self.tree.setMinimumHeight(520)
        self.tree.setIndentation(14)
        self.tree.currentItemChanged.connect(self.on_select)
        top.addWidget(self.tree)
        right = QVBoxLayout()
        self.summary = label("", 10, wrap=True)
        sc = Card(T("Riepilogo"))
        sc.lay.addWidget(self.summary)
        right.addWidget(sc)
        self.c_fps, self.c_temp, self.c_clk = Chart(), Chart(), Chart()
        for title, ch in (("FPS", self.c_fps), ("Temperature", self.c_temp), ("Clock GPU e consumo", self.c_clk)):
            c = Card(T(title))
            c.lay.addWidget(ch)
            right.addWidget(c)
        top.addLayout(right, 1)
        lay.addLayout(top)
        b = QPushButton(T("Aggiorna"))
        b.clicked.connect(self.load)
        lay.addWidget(b, 0, Qt.AlignmentFlag.AlignLeft)
        self.sessions = []
        self.games = {}
        self.load()

    def db(self):
        con = sqlite3.connect(common.DB_PATH, timeout=3)
        con.row_factory = sqlite3.Row
        con.execute("CREATE TABLE IF NOT EXISTS marks(session INTEGER, t REAL, note TEXT)")
        return con

    def load(self):
        self.tree.clear()
        try:
            con = self.db()
            self.sessions = con.execute(
                "SELECT s.*, (SELECT COUNT(*) FROM samples WHERE session=s.id) AS n FROM sessions s "
                "ORDER BY start DESC LIMIT 1000").fetchall()
        except sqlite3.Error:
            self.sessions = []
        self.games = {}
        for i, s in enumerate(self.sessions):
            self.games.setdefault(game_title(s["game"]), []).append(i)
        first = None
        for name, idxs in self.games.items():   # già in ordine di partita più recente
            ss = [self.sessions[i] for i in idxs]
            played = sum(s["n"] for s in ss)     # un campione al secondo mentre il gioco disegna
            last = time.strftime('%d/%m', time.localtime(ss[0]["start"]))
            n = len(ss)
            top = QTreeWidgetItem([f"{name}\n" + (T("1 sessione") if n == 1 else T("{n} sessioni", n=n))
                                   + " · " + T("{d} · ultima {last}", d=fmt_dur(played), last=last)])
            f = top.font(0)
            f.setBold(True)
            top.setFont(0, f)
            top.setData(0, Qt.ItemDataRole.UserRole, ("game", name))
            for i in idxs:
                s = self.sessions[i]
                it = QTreeWidgetItem([f"{day_time(s['start'])}  ·  {fmt_dur(s['n'])}"])
                it.setData(0, Qt.ItemDataRole.UserRole, ("session", i))
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            if first is None:
                first = top
        if first:
            first.setExpanded(True)
            self.tree.setCurrentItem(first)
        else:
            self.summary.setText(f"<span style='color:{P['MUTED']}'>{T('Ancora nessuna partita registrata.')}</span>")

    def on_select(self, cur, _prev):
        if not cur:
            return
        kind, val = cur.data(0, Qt.ItemDataRole.UserRole)
        if kind == "game":
            self.show_game(val)
        else:
            self.show_session(val)

    @staticmethod
    def stats(rows):
        def stat(k, f=max):
            v = [r[k] for r in rows if r[k] is not None]
            return f(v) if v else 0
        fps = [r["fps"] for r in rows if r["fps"]]
        low = [r["low1"] for r in rows if r["low1"]]
        thr = 100 * sum(r["throttling"] or 0 for r in rows) / len(rows)
        return (T("FPS medi") + f" <b>{sum(fps) / len(fps) if fps else 0:.0f}</b> · " + T("1% low medio")
                + f" <b>{sum(low) / len(low) if low else 0:.0f}</b>"
                f" · CPU max <b style='color:{temp_color(stat('cpu_temp'), 80, 90)}'>{stat('cpu_temp'):.0f}°C</b>"
                f" · GPU max <b style='color:{temp_color(stat('gpu_temp'))}'>{stat('gpu_temp'):.0f}°C</b>"
                " · " + T("consumo medio") + f" <b>{stat('power', lambda v: sum(v) / len(v)):.0f} W</b>"
                " · " + T("taglio clock") + f" <b style='color:{P['BAD'] if thr > 5 else P['GOOD']}'>"
                + T("{v:.0f}% del tempo", v=thr) + "</b>"), fps

    def draw(self, rows, marks):
        """marks: [(t, testo)]"""
        step = max(1, len(rows) // 400)
        rs = rows[::step]

        def col(k):
            return [r[k] for r in rs]
        mk = []
        for t, note in marks:
            idx = min(range(len(rs)), key=lambda j: abs(rs[j]["t"] - t))
            mk.append((idx, note))
        fps = [r["fps"] for r in rows if r["fps"]]
        top = max(60, max(fps or [60]) * 1.15)
        self.c_fps.set([("FPS", col("fps"), P["GOOD"], top), ("1% low", col("low1"), P["WARN"], top)], mk)
        self.c_temp.set([("CPU °C", col("cpu_temp"), P["BAD"], 100), ("GPU °C", col("gpu_temp"), P["WARN"], 100)], mk)
        self.c_clk.set([(T("Clock GPU MHz"), col("gpu_clk"), P["ACCENT"], 2100),
                        (T("Consumo W ×10"), [None if v is None else v * 10 for v in col("power")], P["PURPLE"], 2100)], mk)

    def show_game(self, name):
        ss = [self.sessions[i] for i in self.games.get(name, [])]
        if not ss:
            return
        con = self.db()
        ids = [s["id"] for s in ss]
        q = ",".join("?" * len(ids))
        rows = con.execute(f"SELECT * FROM samples WHERE session IN ({q}) ORDER BY t", ids).fetchall()
        if not rows:
            self.summary.setText(T("Nessun dato."))
            return
        played = sum(s["n"] for s in ss)
        first = time.strftime('%d/%m/%Y', time.localtime(ss[-1]["start"]))
        last = time.strftime('%d/%m/%Y', time.localtime(ss[0]["start"]))
        profs = sorted({s["profile"] for s in ss if s["profile"]})
        text, _ = self.stats(rows)
        self.summary.setText(
            f"<b>{name}</b> <span style='color:{P['MUTED']}'>· "
            + T("{n} sessioni · in gioco {d} · dal {a} al {b}", n=len(ss), d=fmt_dur(played), a=first, b=last)
            + " · " + (T("profilo {p}", p=", ".join(profs)) if profs else T("nessun profilo")) + "</span><br>"
            + text + f"<br><span style='color:{P['DIM']}'>"
            + T("Grafici: tutte le sessioni una dopo l'altra, le linee viola separano le sessioni.") + "</span>")
        bounds = [(s["start"], time.strftime('%d/%m %H:%M', time.localtime(s["start"]))) for s in reversed(ss)]
        self.draw(rows, bounds[1:] if len(bounds) > 1 else [])

    def show_session(self, i):
        if i < 0 or i >= len(self.sessions):
            return
        s = self.sessions[i]
        con = self.db()
        rows = con.execute("SELECT * FROM samples WHERE session=? ORDER BY t", (s["id"],)).fetchall()
        marks = con.execute("SELECT * FROM marks WHERE session=? ORDER BY t", (s["id"],)).fetchall()
        if not rows:
            self.summary.setText(T("Nessun dato."))
            return
        total = s["end"] - s["start"]
        away = total - s["n"]
        text, _ = self.stats(rows)
        when = time.strftime('%d/%m %H:%M', time.localtime(s["start"])) + "–" + \
            time.strftime('%H:%M', time.localtime(s["end"]))
        self.summary.setText(
            f"<b>{game_title(s['game'])}</b> <span style='color:{P['MUTED']}'>· {when} · {s['api']} · "
            + (T("profilo {p}", p=s['profile']) if s['profile'] else T("nessun profilo"))
            + " · " + T("in gioco {d}", d=fmt_dur(s['n']))
            + (" " + T("(fuori dal gioco {d})", d=fmt_dur(away)) if away > 90 else "") + "</span><br>" + text
            + self.graphics_html(con, s["id"]))
        self.draw(rows, [(m["t"], m["note"]) for m in marks])

    @staticmethod
    def graphics_html(con, sid):
        """Impostazioni grafiche: quelle principali all'avvio e cosa è cambiato durante la partita."""
        try:
            evs = con.execute("SELECT * FROM game_settings WHERE session=? ORDER BY t", (sid,)).fetchall()
        except sqlite3.Error:
            return ""
        if not evs:
            return ""
        out = []
        for e in evs:
            d = json.loads(e["data"])
            hhmm = time.strftime('%H:%M', time.localtime(e["t"]))
            if e["kind"] == "start":
                summ = gamecfg.summary(d.get("settings", {}), 14)
                vals = " · ".join(f"{gamecfg.short(k)} <b>{v}</b>" for k, v in summ.items())
                eng = (d.get("source") or {}).get("engine", "")
                out.append(T("Grafica all'avvio ({e}):", e=eng) + " " + vals)
            elif e["kind"] == "change":
                out.append(f"<span style='color:{P['PURPLE']}'>{hhmm} " + T("cambiata in gioco:") + " "
                           + gamecfg.describe_changes(d.get("changes", {}), 6) + "</span>")
            else:
                out.append(f"<span style='color:{P['ACCENT']}'>{hhmm} " + T("applicata dal profilo:") + " "
                           + gamecfg.describe_changes(d.get("changes", {}), 6) + "</span>")
        return f"<br><span style='color:{P['MUTED']}; font-size:9pt'>" + "<br>".join(out) + "</span>"

    def refresh(self, st):
        pass


# ---------------------------------------------------------------- finestra
class Main(QWidget):
    # menu a gruppi: (gruppo, [(chiave, nome, classe)]); la chiave serve a --page e ai collegamenti interni
    GROUPS = [("Monitoraggio", [("overview", "Panoramica", Dashboard), ("history", "Storico", HistoryPage)]),
              ("Giochi", [("games", "Giochi", LibraryPage), ("profiles", "Profili", ProfilesPage),
                          ("overlay", "Overlay", OverlayPage)]),
              ("Prestazioni", [("fps", "FPS e upscaling", FpsPage), ("board", "Scheda", BoardPage),
                               ("display", "Display", DisplayPage)]),
              ("Sistema", [("health", "Salute e avvisi", HealthPage)])]
    PAGES = [p for _g, ps in GROUPS for p in ps]

    @classmethod
    def page_index(cls, key):
        return next(i for i, p in enumerate(cls.PAGES) if p[0] == key)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BC-250 Control Center")
        self.setWindowIcon(QIcon(os.path.join(ASSETS, "icon.svg")))
        self.setStyleSheet(STYLE)
        self.root = QHBoxLayout(self)
        self.root.setContentsMargins(0, 0, 0, 0)
        self.root.setSpacing(0)
        self.side = self.content = None
        self.toast_timer = QTimer(self)
        self.toast_timer.setSingleShot(True)
        self.toast_timer.timeout.connect(lambda: self.toast_l.setText(""))
        self.build()

        self.resize(1240, 860)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.tick()

    def build(self, current=0):
        """Costruisce barra laterale e pagine nella lingua attuale (di nuovo a ogni cambio lingua)."""
        side = QWidget()
        side.setFixedWidth(210)
        side.setStyleSheet(f"background:{P['SIDEBAR']};")
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 18, 0, 12)
        brand = label("BC-250", 17, P["ACCENT"], bold=True)
        brand.setFont(display_font(17))
        brand.setStyleSheet(f"color:{P['ACCENT']}; font-family:'{DISPLAY}'; font-size:17pt; font-weight:bold;")
        brand.setContentsMargins(20, 0, 0, 0)
        sl.addWidget(brand)
        sub = label("CONTROL CENTER · v" + __version__, 7.5, P["DIM"])
        sub.setStyleSheet(f"color:{P['DIM']}; font-size:7.5pt; letter-spacing:1px;")
        sub.setContentsMargins(20, 2, 0, 12)
        sl.addWidget(sub)
        self.find = QLineEdit()
        self.find.setObjectName("find")
        self.find.setPlaceholderText("🔍  " + T("Cerca impostazioni e giochi…"))
        self.find.setClearButtonEnabled(True)
        self.find_model = QStringListModel()
        comp = QCompleter(self.find_model, self.find)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        comp.setMaxVisibleItems(14)
        comp.popup().setObjectName("findpop")
        comp.activated.connect(self.goto_result)
        self.find.setCompleter(comp)
        self.find.textEdited.connect(lambda *_: self.build_index())
        self.find.returnPressed.connect(lambda: self.goto_result(self.find.text()))
        fw = QWidget()
        fl = QHBoxLayout(fw)
        fl.setContentsMargins(12, 0, 12, 6)
        fl.addWidget(self.find)
        sl.addWidget(fw)
        self.find_index = {}
        self.find_built = 0
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        sl.addWidget(self.nav, 1)
        self.lang = QComboBox()
        for code, name in i18n.LANGS:
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(i18n.get_lang())))
        self.lang.setToolTip(T("Lingua"))
        self.lang.activated.connect(self.on_lang)
        lw = QWidget()
        lw.setStyleSheet("background:transparent;")
        ll = QHBoxLayout(lw)
        ll.setContentsMargins(16, 0, 12, 8)
        ll.addWidget(self.lang)
        sl.addWidget(lw)
        self.status = label("", 8.5, P["MUTED"], wrap=True)
        self.status.setContentsMargins(18, 0, 12, 0)
        sl.addWidget(self.status)

        content = QWidget()
        right = QVBoxLayout(content)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        self.toast_l = label("", 9.5, P["ACCENT"])
        self.toast_l.setContentsMargins(26, 6, 26, 8)
        right.addWidget(self.toast_l)
        self.root.addWidget(side)
        self.root.addWidget(content, 1)
        self.side, self.content = side, content

        self.pages = []
        self.page_row = {}   # indice pagina -> riga del menu (le intestazioni dei gruppi occupano righe)
        hf = QFont(font(7))
        hf.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.5)
        for group, entries in self.GROUPS:
            head = QListWidgetItem(T(group).upper())
            head.setFlags(Qt.ItemFlag.NoItemFlags)
            head.setFont(hf)
            head.setForeground(QColor(P["DIM"]))
            head.setSizeHint(QSize(0, 34))
            self.nav.addItem(head)
            for _key, _name, cls in entries:
                self.page_row[len(self.pages)] = self.nav.count()
                self.nav.addItem(QListWidgetItem(self.nav_label(len(self.pages))))
                pg = cls(self)
                self.pages.append(pg)
                self.stack.addWidget(pg.w)
        rows = {r: i for i, r in self.page_row.items()}
        self.nav.currentRowChanged.connect(lambda r: r in rows and self.stack.setCurrentIndex(rows[r]))
        self.show_page(current)

    def show_page(self, i):
        self.nav.setCurrentRow(self.page_row.get(i, self.page_row[0]))

    def nav_label(self, i):
        """Voce del menu in stile cockpit: «01  PANORAMICA»."""
        return f"{i + 1:02d}  {T(self.PAGES[i][1]).upper()}"

    def on_lang(self, *_):
        code = self.lang.currentData()
        if code == i18n.get_lang():
            return
        common.update_config(lambda c: c.update(language=code))
        i18n.set_lang(code)
        # fuori dal segnale del menu: il menu stesso viene distrutto e ricreato
        QTimer.singleShot(0, self.rebuild)

    def rebuild(self):
        cur = max(0, self.stack.currentIndex())
        self.toast_timer.stop()
        for w in (self.side, self.content):
            self.root.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.build(cur)
        self.tick()

    # ------------------------------------------------------------ ricerca
    def build_index(self, force=False):
        """Indice di ricerca: pagine, titoli delle card, voci, pulsanti e giochi (ricostruito ogni 10 s)."""
        if not force and time.time() - self.find_built < 10:
            return
        self.find_built = time.time()
        idx = {}
        for i, (_key, name, _cls) in enumerate(self.PAGES):
            pname = T(name)
            idx[f"{pname}"] = (i, None, None)
            root = self.pages[i].w
            for wdg in root.findChildren((QLabel, QCheckBox, QPushButton)):
                txt = re.sub(r"<[^>]+>|&nbsp;", " ", wdg.text() or "")
                txt = re.sub(r"\s+", " ", txt).strip(" ·:")
                if 2 < len(txt) <= 70 and not re.fullmatch(r"[\d\s.,%°/·—–-]+[A-Za-z]{0,4}", txt):
                    key = f"{txt[:1].upper() + txt[1:] if txt.isupper() else txt}  —  {pname}"
                    idx.setdefault(key, (i, wdg, None))
        try:
            from . import launchers
            for k, g in launchers.load_known().items():
                idx[f"🎮 {g.get('name', k)}  —  {T('Giochi')}"] = (self.page_index("games"), None, g.get("name", k))
        except Exception:
            pass
        self.find_index = idx
        self.find_model.setStringList(sorted(idx, key=str.lower))

    def goto_result(self, text):
        self.build_index()
        hit = self.find_index.get(text)
        if not hit:   # invio senza scegliere: primo risultato che contiene il testo
            q = text.strip().lower()
            hit = next((v for k, v in sorted(self.find_index.items()) if q and q in k.lower()), None)
        if not hit:
            return
        i, wdg, game = hit
        self.show_page(i)
        if game is not None:
            self.pages[i].search.setText(game)
            return
        if wdg is not None:
            area = self.pages[i].w
            QTimer.singleShot(50, lambda: area.ensureWidgetVisible(wdg, 0, 120))
            card = wdg
            while card is not None and not isinstance(card, Card):
                card = card.parentWidget()
            if card is not None:
                card.setStyleSheet(f"QFrame#card {{ border:2px solid {P['ACCENT']}; }}")
                QTimer.singleShot(1800, lambda c=card: c.setStyleSheet(""))
        QTimer.singleShot(0, self.find.clear)

    def check_new_games(self, force=False):
        """Numero dei giochi nuovi accanto a «Giochi» nel menu (niente notifiche)."""
        from . import launchers
        try:
            m = os.stat(launchers.KNOWN_PATH).st_mtime
        except OSError:
            m = 0
        if not force and m == getattr(self, "_known_m", None):
            return
        self._known_m = m
        n = len(launchers.pending())
        gi = self.page_index("games")
        it = self.nav.item(self.page_row[gi])
        if it:
            it.setText(self.nav_label(gi) + (f"   {n}" if n else ""))
            it.setForeground(QColor(P["ACCENT"]) if n else QColor(P["MUTED"]))
        if n and self.stack.currentIndex() == gi:
            self.pages[gi].load_games()

    def toast(self, text):
        self.toast_l.setText(text)
        self.toast_timer.start(4000)

    def tick(self):
        st = common.read_state()
        fresh = time.time() - st.get("ts", 0) < 5
        g = st.get("game")
        self.status.setText(
            (f"<span style='color:{P['GOOD']}'>●</span> " + T("servizio attivo") if fresh else
             f"<span style='color:{P['BAD']}'>●</span> " + T("servizio fermo — vedi Salute"))
            + (f"<br>{g['name']} · {g['fps']:.0f} FPS" if g else ""))
        self.check_new_games()
        cur = self.stack.currentIndex()
        try:
            self.pages[cur].refresh(st)
        except Exception as e:  # una pagina non deve bloccare la finestra
            print("refresh error:", e, file=sys.stderr)


def main():
    app = QApplication(sys.argv)
    # Fusion: stesso aspetto su ogni desktop (Breeze rendeva trasparenti i menu a tendina)
    app.setStyle("Fusion")
    load_fonts()
    app.setFont(font(10))
    app.setApplicationName("bc250-control")
    app.setDesktopFileName("bc250-control")
    w = Main()
    if "--page" in sys.argv:
        # numero (01 = 1, come nel menu) o nome: --page games, --page fps, …
        arg = sys.argv[sys.argv.index("--page") + 1]
        keys = [p[0] for p in Main.PAGES]
        w.show_page(int(arg) - 1 if arg.isdigit() else keys.index(arg) if arg in keys else 0)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
