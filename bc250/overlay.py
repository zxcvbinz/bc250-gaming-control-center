# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""bc250-overlay: HUD minimal + pannello dettagli (Shift+F2) + avvisi a schermo.

Finestre Wayland layer-shell (livello Overlay): restano sopra anche ai giochi a
schermo intero e non ricevono click né tastiera.
"""
import ctypes
import os
import socket
import sys
import time
from collections import deque

os.environ["QT_WAYLAND_SHELL_INTEGRATION"] = "layer-shell"

from PyQt6 import sip  # noqa: E402
from PyQt6.QtCore import QPointF, QRectF, QSocketNotifier, Qt, QTimer  # noqa: E402
from PyQt6.QtGui import QFont, QFontMetrics, QPainter, QPen  # noqa: E402
from PyQt6.QtWidgets import QApplication, QWidget  # noqa: E402

from . import common, i18n  # noqa: E402
from .i18n import T  # noqa: E402

P = common.PALETTE

# ---------------------------------------------------------------- layer-shell via ctypes
_ls = ctypes.CDLL("libLayerShellQtInterface.so.6")
_get = _ls._ZN12LayerShellQt6Window3getEP7QWindow
_get.restype, _get.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
_setLayer = _ls._ZN12LayerShellQt6Window8setLayerENS0_5LayerE
_setLayer.argtypes = [ctypes.c_void_p, ctypes.c_int]
_setAnchors = _ls._ZN12LayerShellQt6Window10setAnchorsE6QFlagsINS0_6AnchorEE
_setAnchors.argtypes = [ctypes.c_void_p, ctypes.c_int]
_setMargins = _ls._ZN12LayerShellQt6Window10setMarginsERK8QMargins
_setMargins.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
_setKbd = _ls._ZN12LayerShellQt6Window24setKeyboardInteractivityENS0_21KeyboardInteractivityE
_setKbd.argtypes = [ctypes.c_void_p, ctypes.c_int]
_setEZ = _ls._ZN12LayerShellQt6Window16setExclusiveZoneEi
_setEZ.argtypes = [ctypes.c_void_p, ctypes.c_int]

A_TOP, A_BOTTOM, A_LEFT, A_RIGHT = 1, 2, 4, 8
ANCHORS = {
    "top-left": A_TOP | A_LEFT, "top-center": A_TOP, "top-right": A_TOP | A_RIGHT,
    "bottom-left": A_BOTTOM | A_LEFT, "bottom-center": A_BOTTOM, "bottom-right": A_BOTTOM | A_RIGHT,
    "center": 0, "bottom-bar": A_BOTTOM | A_LEFT | A_RIGHT,
}


class LayerWindow(QWidget):
    def __init__(self, keyboard=False):
        super().__init__()
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowTransparentForInput
        if not keyboard:
            flags |= Qt.WindowType.WindowDoesNotAcceptFocus
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.winId()
        self._lw = _get(sip.unwrapinstance(self.windowHandle()))
        _setLayer(self._lw, 3)
        # pannello: tastiera esclusiva mentre è aperto (come l'overlay di Steam)
        _setKbd(self._lw, 1 if keyboard else 0)
        _setEZ(self._lw, -1)
        self.place("top-left", 24)

    def place(self, position, margin):
        _setAnchors(self._lw, ANCHORS.get(position, A_TOP | A_LEFT))
        m = (ctypes.c_int * 4)(margin, margin, margin, margin)
        _setMargins(self._lw, ctypes.addressof(m))


# ---------------------------------------------------------------- HUD
from .hudpaint import HudPainter, display_font, draw_series, font, fps_col, load_fonts, qc, temp_col  # noqa: E402


class Hud(LayerWindow):
    def __init__(self):
        super().__init__()
        self.state, self.cfg = {}, common.load_config()
        self.painter = HudPainter()
        self.anim = QTimer(self)
        self.anim.timeout.connect(self.animate)

    def update_from(self, state, cfg):
        self.state, self.cfg = state, cfg
        o = cfg["overlay"]
        self.place(o["position"], int(o["margin"]))
        self.painter.update(state, cfg)
        if not self.isVisible():
            # riparte dal cerchio chiuso e trasparente: compare allargandosi
            self.painter.w_cur = float(self.painter.D)
            self.painter.alpha = 0.0
        self.resize_to()
        self.update()
        if not self.anim.isActive():
            self.painter.step(0)
            self.anim.start(16)

    def wants_visible(self):
        return self.painter.visible(self.cfg)

    def resize_to(self):
        w, h = self.painter.size(self.state, self.cfg)
        if (self.width(), self.height()) != (w, h):
            self.setFixedSize(w, h)

    def animate(self):
        moving = self.painter.step()
        self.resize_to()
        self.update()
        if not moving:
            self.anim.stop()
            if not self.wants_visible():
                self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        self.painter.paint(p, self.state, self.cfg, self.width(), self.height())
        p.end()


# ---------------------------------------------------------------- profilo modificabile dal pannello
from .common import FIELD_DEFAULT, PROFILE_FIELDS  # noqa: E402


def edit_profile(game, key, value):
    """Imposta un campo del profilo del gioco (lo crea se non esiste)."""
    def fn(c):
        prof = None
        if game.get("profile"):
            prof = next((p for p in c["profiles"] if p.get("name") == game["profile"]), None)
        name = game["name"].removesuffix(".exe")
        match = f"appid:{game['appid']}" if game.get("appid") else game["name"]
        if prof is None:
            # il servizio può non aver ancora riportato il profilo appena creato: niente doppioni
            prof = next((p for p in c["profiles"] if p.get("match") == match or p.get("name") == name), None)
        if prof is None:
            prof = {"name": name, "match": match}
            c["profiles"].append(prof)
        prof[key] = value
    return common.update_config(fn)


# ---------------------------------------------------------------- pannello dettagli
class Panel(LayerWindow):
    """Pannello Shift+F2 in stile «cockpit»: barra a tutta larghezza in basso, il gioco resta visibile sopra.

    Tre colonne: FPS del gioco · frametime e sensori · profilo modificabile con le frecce.
    """
    H = 330
    LEFT_W, RIGHT_W = 400, 470

    def __init__(self, hist):
        super().__init__(keyboard=True)
        self.hist = hist
        self.state, self.cfg = {}, common.load_config()
        self.sel = 0
        self.pending = {}  # modifiche appena fatte, finché il servizio non le riporta nello stato
        self.on_close = None
        self.place("bottom-bar", 0)
        self.fit_width()
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def fit_width(self):
        scr = self.screen() or QApplication.primaryScreen()
        w = scr.geometry().width() if scr else 1920
        if (self.width(), self.height()) != (w, self.H):
            self.setFixedSize(w, self.H)

    def update_from(self, state, cfg):
        self.state, self.cfg = state, cfg
        self.fit_width()
        self.update()

    def keyPressEvent(self, e):
        k = e.key()
        g = self.state.get("game")
        if k in (Qt.Key.Key_Escape, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self.on_close:
                self.on_close()
            return
        if k in (Qt.Key.Key_Up, Qt.Key.Key_W):
            self.sel = (self.sel - 1) % len(PROFILE_FIELDS)
        elif k in (Qt.Key.Key_Down, Qt.Key.Key_S, Qt.Key.Key_Tab):
            self.sel = (self.sel + 1) % len(PROFILE_FIELDS)
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_A, Qt.Key.Key_D) and g:
            key, _label, values, _fmt = PROFILE_FIELDS[self.sel]
            prof = g.get("profile_data") or {}
            cur = self.pending[key][0] if key in self.pending else prof.get(key, FIELD_DEFAULT[key])
            i = values.index(cur) if cur in values else 0
            i = (i + (1 if k in (Qt.Key.Key_Right, Qt.Key.Key_D) else -1)) % len(values)
            self.cfg = edit_profile(g, key, values[i])
            self.pending[key] = (values[i], time.monotonic())
        self.update()

    # ------------------------------------------------------------ pezzi
    @staticmethod
    def caption(p, x, y, w, text, align=Qt.AlignmentFlag.AlignLeft, col=None):
        f = font(7.5)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
        p.setFont(f)
        p.setPen(qc(col or P["MUTED"]))
        text = QFontMetrics(f).elidedText(text.upper(), Qt.TextElideMode.ElideRight, int(w))
        p.drawText(QRectF(x, y, w, 14), align | Qt.AlignmentFlag.AlignVCenter, text)

    @staticmethod
    def meter(p, r, frac, color_at, segments=10):
        """Barra a segmenti: color_at(i, n) dà il colore del segmento acceso i."""
        gap = 3
        sw = (r.width() - gap * (segments - 1)) / segments
        lit = 0 if frac is None else round(max(0.0, min(1.0, frac)) * segments)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(segments):
            p.setBrush(qc(color_at(i, segments) if i < lit else P["OFF"]))
            p.drawRect(QRectF(r.left() + i * (sw + gap), r.top(), sw, r.height()))

    def status(self, g, eng, limit):
        """(testo, colore) dello stato del limite FPS, come il vecchio badge."""
        if not eng.get("limit_enabled", True):
            return T("LIMITE FPS DISATTIVATO"), P["WARN"]
        if g and g.get("guard_cut"):
            return T("LIMITE {v} FPS · PROTEZIONE CALORE", v=limit), P["WARN"]
        if g and limit:
            fps = g.get("fps")
            if fps and fps < limit * 0.9:
                return T("SOTTO IL LIMITE"), fps_col(fps, limit)
            return T("STABILE"), P["GOOD"]
        if g:
            return T("NESSUN LIMITE FPS"), P["MUTED"]
        gl = eng.get("fps_limit")
        return (T("LIMITE {v} FPS · PRONTO", v=gl) if gl else T("NESSUN LIMITE")), P["ACCENT"]

    def draw_game(self, p, r, g, eng):
        x, w = r.left() + 24, r.width() - 48
        p.setFont(display_font(15))
        p.setPen(qc(P["TEXT"]))
        fm = QFontMetrics(p.font())
        title = (g.get("name") or T("Nessun gioco attivo")).removesuffix(".exe").upper()
        p.drawText(QRectF(x, r.top() + 18, w, 26), Qt.AlignmentFlag.AlignLeft, fm.elidedText(title, Qt.TextElideMode.ElideRight, int(w * 0.62 if g.get("api") else w)))
        if g.get("api"):
            self.caption(p, x, r.top() + 24, w, g["api"], Qt.AlignmentFlag.AlignRight)

        if not g:
            # nessun gioco: niente numero grande, solo lo stato del limite globale
            stext, scol = self.status(g, eng, None)
            p.setFont(font(9.5, True))
            p.setPen(qc(scol))
            p.drawText(QRectF(x, r.top() + 64, w, 20), Qt.AlignmentFlag.AlignLeft, "● " + stext)
            p.setFont(font(8.5))
            p.setPen(qc(P["MUTED"]))
            p.drawText(QRectF(x, r.top() + 92, w, 60), int(Qt.AlignmentFlag.AlignLeft.value | Qt.TextFlag.TextWordWrap.value),
                       T("Il pannello mostra FPS e frametime quando un gioco è in esecuzione."))
            return
        fps = g.get("fps")
        limit = g.get("limit")
        col = fps_col(fps, limit)
        if col == P["GOOD"]:
            col = P["ACCENT"]   # tutto bene: ambra, il colore del pannello; avvisi e problemi restano colorati
        big = font(54, True)
        p.setFont(big)
        p.setPen(qc(col))
        txt = f"{fps:.0f}" if fps else "—"
        p.drawText(QRectF(x - 2, r.top() + 52, w, 80), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, txt)
        tx = x + QFontMetrics(big).horizontalAdvance(txt) + 16
        p.setFont(font(9))
        p.setPen(qc(P["TEXT"]))
        p.drawText(QRectF(tx, r.top() + 72, w, 18), Qt.AlignmentFlag.AlignLeft,
                   T("/ {v} LIMITE", v=limit) if limit else T("/ SENZA LIMITE"))
        stext, scol = self.status(g, eng, limit)
        p.setFont(font(8.5, True))
        p.setPen(qc(scol))
        p.drawText(QRectF(tx, r.top() + 94, r.right() - tx - 12, 18), Qt.AlignmentFlag.AlignLeft, "● " + stext)

        fv = [v for v in self.hist["fps"] if v]
        stats = [(T("media 60s"), f"{sum(fv) / len(fv):.1f}" if fv else "—"),
                 ("1% low", f"{g['low1']:.0f}" if g.get("low1") else "—"),
                 ("frame", f"{g['frametime']:.1f}ms" if g.get("frametime") else "—")]
        cw = w / 3
        for i, (k, v) in enumerate(stats):
            self.caption(p, x + i * cw, r.top() + 150, cw, k)
            p.setFont(font(13, True))
            p.setPen(qc(P["TEXT"]))
            p.drawText(QRectF(x + i * cw, r.top() + 166, cw, 24), Qt.AlignmentFlag.AlignLeft, v)

        sub = []
        if g:
            sub.append(T("profilo: {p}", p=g["profile"]) if g.get("profile") else T("nessun profilo"))
            up = (g.get("profile_data") or {}).get("upscale")
            if g.get("via_run") is True:
                sub.append(T("collegato ✓") + (f" · {T(common.UPSCALE_NAMES.get(up, ''))}" if up else ""))
            elif g.get("via_run") is False:
                sub.append(T("non collegato") + (" · " + T("upscaling non attivo") if up else ""))
            if g.get("appid"):
                sub.append(f"Steam {g['appid']}")
        if sub:
            p.setFont(font(8))
            p.setPen(qc(P["MUTED"]))
            fm = QFontMetrics(p.font())
            p.drawText(QRectF(x, r.bottom() - 34, w, 16), Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText("  ·  ".join(sub), Qt.TextElideMode.ElideRight, int(w)))

    def draw_center(self, p, r, g, s, gov, st):
        x, w = r.left() + 24, r.width() - 48
        fps = g.get("fps")
        limit = g.get("limit") if g else None
        fts = g.get("frametimes") or []
        target = 1000.0 / limit if limit else (sum(fts) / len(fts) if fts else None)
        self.caption(p, x, r.top() + 18, w, T("frametime · ultimi 120 frame"))
        if target:
            self.caption(p, x, r.top() + 18, w, T("obiettivo {v} ms ┄┄", v=f"{target:.1f}"), Qt.AlignmentFlag.AlignRight)
        gr = QRectF(x, r.top() + 40, w, 96)
        p.setPen(QPen(qc(P["BORDER"]), 1))
        p.setBrush(qc(P["CARD"], 255))
        p.drawRect(gr)
        inner = gr.adjusted(6, 8, -6, -6)
        if fts:
            vmax = max(target * 2, max(fts) * 1.1)
            ty = inner.bottom() - inner.height() * target / vmax
            p.setPen(QPen(qc(P["DIM"]), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(inner.left(), ty), QPointF(inner.right(), ty))
            col = fps_col(fps, limit)
            draw_series(p, inner, fts, vmax, P["ACCENT"] if col == P["GOOD"] else col, fill=False, width=1.6)
        else:
            p.setFont(font(8.5))
            p.setPen(qc(P["DIM"]))
            p.drawText(gr, Qt.AlignmentFlag.AlignCenter, T("nessun dato dal motore FPS"))

        gmax = gov.get("max") or 2000
        thr = gov.get("throttle") or 85
        guard = ((g.get("profile_data") or {}).get("heat_guard")) if g else None
        throttling = st.get("throttling")

        def temp_seg(lo, hi, warn, bad):
            return lambda i, n: temp_col(lo + (hi - lo) * (i + 1) / n, warn, bad)

        cpu, gpu, clk, pw = s.get("cpu_temp"), s.get("gpu_temp"), s.get("gpu_clk"), s.get("power")
        meters = [
            ("CPU", f"{cpu:.0f}°C" if cpu is not None else "—", P["TEXT"],
             None if cpu is None else (cpu - 30) / 70, temp_seg(30, 100, 80, 90),
             T("taglio {t}°", t=thr) + (" · " + T("guardia {t}°", t=guard) if guard else "")),
            ("GPU", f"{gpu:.0f}°C" if gpu is not None else "—", P["TEXT"],
             None if gpu is None else (gpu - 30) / 70, temp_seg(30, 100, thr - 10, thr),
             T("carico {v}%", v=f"{s.get('gpu_busy') or 0:.0f}")),
            (T("clock"), f"{clk:.0f}" if clk else "—", P["BAD"] if throttling else P["CYAN"],
             None if not clk else clk / max(2000, gmax), lambda i, n: P["BAD"] if throttling else P["CYAN"],
             T("TAGLIO IN CORSO") if throttling else f"MHz · {gov.get('min') or '?'}–{gmax}"),
            ("SoC", f"{pw:.0f} W" if pw is not None else "—", P["TEXT"],
             None if pw is None else pw / 160, lambda i, n: P["MUTED"],
             T("ventola {v} rpm", v=s.get("fan") or 0)),
        ]
        gap = 22 if w > 700 else 12
        mw = (w - gap * 3) / 4
        y = gr.bottom() + 18
        for i, (name, val, vcol, frac, seg, sub) in enumerate(meters):
            mx = x + i * (mw + gap)
            self.caption(p, mx, y, mw, name)
            p.setFont(font(10, True))
            p.setPen(qc(vcol))
            p.drawText(QRectF(mx, y - 2, mw, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val)
            self.meter(p, QRectF(mx, y + 22, mw, 10), frac, seg)
            fan_bad = name == "SoC" and not s.get("fan")
            self.caption(p, mx, y + 38, mw, sub, col=P["BAD"] if fan_bad or (throttling and i == 2) else P["DIM"])

        ram = s.get("ram") or [0, 0]
        vram = s.get("vram") or [0, 0]
        info = [f"RAM {ram[0]:.1f}/{ram[1]:.0f}G", f"VRAM {(vram[0] or 0):.0f}M",
                f"CPU {s.get('cpu_load') or 0:.0f}%",
                f"{s.get('cores', '?')}C/{s.get('threads', '?')}T"
                + (f" ≤{st['cpufreq']['max']} MHz" if (st.get("cpufreq") or {}).get("max") else ""),
                "GOVERNOR " + (T("TAGLIO") if throttling else T("normale")).upper()]
        alerts = st.get("alerts") or []
        if alerts:
            p.setFont(font(8.5, True))
            p.setPen(qc(P["BAD"]))
            fm = QFontMetrics(p.font())
            p.drawText(QRectF(x, r.bottom() - 34, w, 16), Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText("⚠ " + "  ·  ".join(a["title"] for a in alerts), Qt.TextElideMode.ElideRight, int(w)))
        else:
            self.caption(p, x, r.bottom() - 33, w, "    ".join(info))

    def draw_profile(self, p, r, g):
        x, w = r.left() + 24, r.width() - 48
        if not g:
            self.caption(p, x, r.top() + 18, w, T("Profilo del gioco"))
            p.setFont(font(9))
            p.setPen(qc(P["MUTED"]))
            p.drawText(QRectF(x, r.top() + 40, w, r.height() - 80), int(Qt.AlignmentFlag.AlignCenter.value | Qt.TextFlag.TextWordWrap.value),
                       T("Avvia un gioco per modificarne il profilo da qui."))
            self.caption(p, x, r.bottom() - 33, w, T("Shift+F1 limite · Shift+F3 overlay · Esc chiudi"), col=P["DIM"])
            return
        prof = dict(g.get("profile_data") or {})
        now = time.monotonic()
        for k, (v, t) in list(self.pending.items()):
            if now - t < 2:
                prof[k] = v
            else:
                del self.pending[k]
        name = g.get("profile") or (g["name"].removesuffix(".exe") + " " + T("(nuovo)"))
        fm = QFontMetrics(font(7.5))
        self.caption(p, x, r.top() + 18, w, fm.elidedText(T("Profilo del gioco") + " · " + name,
                                                          Qt.TextElideMode.ElideRight, int(w * 0.9)))
        rh = 26
        top = r.top() + 40
        for i, (key, label_, _values, fmt) in enumerate(PROFILE_FIELDS):
            ry = top + i * rh
            row = QRectF(x, ry, w, rh - 2)
            selected = i == self.sel
            val = fmt(prof.get(key, FIELD_DEFAULT[key]), g)
            if selected:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(qc(P["ACCENT"]))
                p.drawRect(row)
                p.setFont(font(9.5, True))
                p.setPen(qc(P["ON_ACCENT"]))
                val = f"‹ {val} ›"
            else:
                p.setPen(QPen(qc(P["OFF"]), 1))
                p.drawLine(QPointF(x, row.bottom() + 1), QPointF(x + w, row.bottom() + 1))
                p.setFont(font(9.5))
                p.setPen(qc(P["MUTED"]))
            p.drawText(row.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       T(label_).upper())
            if not selected:
                p.setPen(qc(P["TEXT"]))
            p.drawText(row.adjusted(10, 0, -10, 0), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, val)
        hint = T("↑↓ scegli · ←→ cambia · Esc chiudi · salva da solo")
        if PROFILE_FIELDS[self.sel][0] == "vrr":
            hint = T("VRR: al cambio lo schermo diventa nero per un attimo")
        self.caption(p, x, r.bottom() - 33, w, hint, col=P["WARN"] if PROFILE_FIELDS[self.sel][0] == "vrr" else P["DIM"])

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(P["BG"], 240))
        p.drawRect(QRectF(0, 0, W, H))
        p.setBrush(qc(P["ACCENT"]))
        p.drawRect(QRectF(0, 0, W, 2))
        st = self.state
        g = st.get("game") or {}
        s = st.get("sensors") or {}
        eng = st.get("engine") or {}
        gov = st.get("governor") or {}

        # colonne laterali fisse sugli schermi larghi, in proporzione su quelli stretti
        lw, rw = min(self.LEFT_W, W * 0.25), min(self.RIGHT_W, W * 0.3)
        left = QRectF(0, 2, lw, H - 2)
        right = QRectF(W - rw, 2, rw, H - 2)
        center = QRectF(left.right(), 2, right.left() - left.right(), H - 2)
        p.setPen(QPen(qc(P["BORDER"]), 1))
        p.drawLine(QPointF(left.right(), 2), QPointF(left.right(), H))
        p.drawLine(QPointF(right.left(), 2), QPointF(right.left(), H))

        self.draw_game(p, left, g, eng)
        self.draw_center(p, center, g, s, gov, st)
        self.draw_profile(p, right, g)
        p.end()


# ---------------------------------------------------------------- avviso a schermo
class Toast(LayerWindow):
    def __init__(self):
        super().__init__()
        self.text = ""
        self.place("top-center", 40)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def show_text(self, text, ms=1800):
        self.text = text
        w = QFontMetrics(font(11, True)).horizontalAdvance(text) + 48
        self.setFixedSize(w, 44)
        self.update()
        self.show()
        self.timer.start(ms)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(P["BG"], 240))
        p.drawRect(QRectF(0, 0, self.width(), self.height()))
        # avvisi di "spento" in giallo (testi in italiano e nella lingua attuale)
        off = ("DISATT", "nascosto", T("DISATTIVATO"), T("nascosto"))
        col = P["WARN"] if any(w in self.text for w in off) else P["ACCENT"]
        p.setBrush(qc(col))
        p.drawRect(QRectF(0, 0, 3, self.height()))
        p.setPen(qc(col))
        p.setFont(font(11, True))
        p.drawText(QRectF(0, 0, self.width(), self.height()), Qt.AlignmentFlag.AlignCenter, self.text)
        p.end()


# ---------------------------------------------------------------- controller
class Controller:
    def __init__(self, app):
        self.app = app
        self.cfg = common.load_config()
        self.cfg_mtime = 0
        self.hist = {k: deque(maxlen=120) for k in ("fps", "cpu_temp", "gpu_temp", "gpu_clk", "power")}
        self.hud = Hud()
        self.panel = Panel(self.hist)
        self.panel.on_close = lambda: self.set_panel(False)
        self.toast = Toast()
        self.panel_on = False
        self.last_hist = 0
        self.alert_shown = {}
        os.makedirs(common.SHM_DIR, mode=0o700, exist_ok=True)
        try:
            os.remove(common.OVERLAY_SOCK)
        except OSError:
            pass
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        self.sock.bind(common.OVERLAY_SOCK)
        self.sock.setblocking(False)
        self.notifier = QSocketNotifier(self.sock.fileno(), QSocketNotifier.Type.Read)
        self.notifier.activated.connect(self.on_cmd)
        self.timer = QTimer()
        self.timer.timeout.connect(self.tick)
        self.timer.start(250)
        self.tick()

    def on_cmd(self):
        while True:
            try:
                data = self.sock.recv(4096).decode(errors="replace")
            except BlockingIOError:
                return
            if data == "toggle-panel":
                self.set_panel(not self.panel_on)
            elif data == "toggle-hud":
                self.tick()
            elif data.startswith("toast:"):
                self.cfg = common.load_config()
                self.tick()
                self.toast.show_text(data[6:])

    def set_panel(self, on):
        self.panel_on = on
        if on:
            self.panel.update_from(common.read_state(), self.cfg)
            self.panel.show()
            self.panel.activateWindow()
            self.panel.setFocus()
        else:
            self.panel.hide()
        self.tick()

    def tick(self):
        try:
            m = os.stat(common.CONF_PATH).st_mtime
        except OSError:
            m = 0
        if m != self.cfg_mtime:
            self.cfg_mtime = m
            self.cfg = common.load_config()
            i18n.set_lang(self.cfg.get("language", "it"))
        st = common.read_state()
        stale = time.time() - st.get("ts", 0) > 5
        g = st.get("game") if not stale else None
        if time.monotonic() - self.last_hist >= 0.5 and not stale:
            self.last_hist = time.monotonic()
            s = st.get("sensors") or {}
            self.hist["fps"].append(g.get("fps") if g else None)
            for k in ("cpu_temp", "gpu_temp", "gpu_clk", "power"):
                self.hist[k].append(s.get(k))
        o = self.cfg["overlay"]
        prof = (g or {}).get("profile_data") or {}
        want_hud = (o["hud_visible"] and not stale and (g or not o["only_in_game"])
                    and prof.get("hud", True) is not False)
        if want_hud:
            ov = dict(o)
            if prof.get("hud_position"):
                ov["position"] = prof["hud_position"]
            if prof.get("hud_style"):
                ov["style"] = prof["hud_style"]
            self.hud.update_from(st, dict(self.cfg, overlay=ov))
            # cerchio con «nascosto»: compare solo quando qualcosa richiede attenzione
            want_hud = self.hud.wants_visible()
        if want_hud != self.hud.isVisible():
            self.hud.setVisible(bool(want_hud))
        if self.panel_on:
            self.panel.update_from(st, self.cfg)
        # avvisi critici anche a schermo, una volta ogni 3 minuti
        now = time.monotonic()
        for a in st.get("alerts") or []:
            if now - self.alert_shown.get(a["key"], -1e9) > 180:
                self.alert_shown[a["key"]] = now
                self.toast.show_text("⚠ " + a["title"], 4000)


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("bc250-overlay")
    load_fonts()
    app.setQuitOnLastWindowClosed(False)
    _c = Controller(app)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
