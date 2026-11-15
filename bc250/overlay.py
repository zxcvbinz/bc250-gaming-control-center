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
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen  # noqa: E402
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
    "center": 0,
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
from .hudpaint import HudPainter, draw_series, font, fps_col, qc, temp_col  # noqa: E402


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
from .common import FIELD_DEFAULT, POS_NAMES, PROFILE_FIELDS  # noqa: E402


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
    W, H = 760, 580

    def __init__(self, hist):
        super().__init__(keyboard=True)
        self.hist = hist
        self.state, self.cfg = {}, common.load_config()
        self.sel = 0
        self.pending = {}  # modifiche appena fatte, finché il servizio non le riporta nello stato
        self.on_close = None
        self.place("center", 0)
        self.setFixedSize(self.W, self.H)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def update_from(self, state, cfg):
        self.state, self.cfg = state, cfg
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

    def draw_profile(self, p, r, g):
        prof = dict(g.get("profile_data") or {})
        now = time.monotonic()
        for k, (v, t) in list(self.pending.items()):
            if now - t < 2:
                prof[k] = v
            else:
                del self.pending[k]
        name = g.get("profile") or (g["name"].removesuffix(".exe") + " " + T("(nuovo)"))
        self.card(p, r, T("Profilo del gioco") + f" · {name}")
        cols = 4
        cw = (r.width() - 24 - (cols - 1) * 10) / cols
        chh = 40
        for i, (key, label_, _values, fmt) in enumerate(PROFILE_FIELDS):
            cx = r.left() + 12 + (i % cols) * (cw + 10)
            cy = r.top() + 26 + (i // cols) * (chh + 8)
            cell = QRectF(cx, cy, cw, chh)
            selected = i == self.sel
            p.setPen(QPen(qc(P["ACCENT"]), 1.5) if selected else Qt.PenStyle.NoPen)
            p.setBrush(qc(P["CARD2"], 255))
            p.drawRoundedRect(cell, 8, 8)
            p.setFont(font(7))
            p.setPen(qc(P["MUTED"]))
            p.drawText(QRectF(cx + 10, cy + 4, cw - 20, 12), Qt.AlignmentFlag.AlignLeft, T(label_))
            val = fmt(prof.get(key, FIELD_DEFAULT[key]), g)
            p.setFont(font(9.5, True))
            p.setPen(qc(P["TEXT"] if selected else P["TEXT"]))
            txt = f"‹  {val}  ›" if selected else val
            p.drawText(QRectF(cx + 10, cy + 17, cw - 20, 18), Qt.AlignmentFlag.AlignLeft, txt)
        p.setFont(font(7.5))
        p.setPen(qc(P["DIM"]))
        hint = T("↑ ↓ scegli  ·  ← → cambia  ·  Esc chiudi  ·  si salva da solo")
        if prof.get("vrr") is not None and PROFILE_FIELDS[self.sel][0] == "vrr":
            hint = T("VRR: al cambio lo schermo diventa nero per un attimo") + "  ·  " + hint
        p.drawText(QRectF(r.left() + 12, r.bottom() - 18, r.width() - 24, 12), Qt.AlignmentFlag.AlignRight, hint)

    def card(self, p, r, title):
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(P["CARD"], 235))
        p.drawRoundedRect(r, 10, 10)
        p.setFont(font(7.5, True))
        p.setPen(qc(P["MUTED"]))
        p.drawText(QRectF(r.left() + 12, r.top() + 8, r.width() - 24, 12), Qt.AlignmentFlag.AlignLeft, title.upper())

    def graph_card(self, p, r, title, key, unit, vmax, color_fn, vmin=0.0, fmt="{:.0f}"):
        self.card(p, r, title)
        vals = list(self.hist[key])
        cur = vals[-1] if vals else None
        p.setFont(font(15, True))
        col = color_fn(cur)
        p.setPen(qc(col))
        p.drawText(QRectF(r.left() + 12, r.top() + 22, r.width() - 24, 24), Qt.AlignmentFlag.AlignLeft,
                   (fmt.format(cur) + unit) if cur is not None else "—")
        good = [v for v in vals if v is not None]
        if good:
            p.setFont(font(7.5))
            p.setPen(qc(P["DIM"]))
            p.drawText(QRectF(r.left() + 12, r.top() + 24, r.width() - 24, 20),
                       Qt.AlignmentFlag.AlignRight,
                       T("min {a}  max {b}", a=fmt.format(min(good)), b=fmt.format(max(good))))
        gr = QRectF(r.left() + 12, r.top() + 52, r.width() - 24, r.height() - 62)
        draw_series(p, gr, vals, vmax, col, vmin=vmin)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        p.setPen(QPen(qc(P["BORDER"]), 1))
        p.setBrush(qc(P["BG"], 238))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 14, 14)
        st = self.state
        g = st.get("game") or {}
        s = st.get("sensors") or {}
        eng = st.get("engine") or {}
        gov = st.get("governor") or {}

        # --- intestazione
        p.setFont(font(13, True))
        p.setPen(qc(P["TEXT"]))
        title = g.get("name") or T("Nessun gioco attivo")
        p.drawText(QRectF(20, 14, 460, 22), Qt.AlignmentFlag.AlignLeft, title)
        p.setFont(font(8.5))
        p.setPen(qc(P["MUTED"]))
        sub = []
        if g:
            sub.append(g.get("api", ""))
            sub.append(T("profilo: {p}", p=g["profile"]) if g.get("profile") else T("nessun profilo"))
            if g.get("appid"):
                sub.append(f"Steam {g['appid']}")
            # partito dal lanciatore bc250-run? (serve per l'upscaling FSR dal profilo)
            up = (g.get("profile_data") or {}).get("upscale")
            if g.get("via_run") is True:
                sub.append(T("collegato ✓") + (f" · {T(common.UPSCALE_NAMES.get(up, ''))}" if up else ""))
            elif g.get("via_run") is False:
                sub.append(T("non collegato") + (" · " + T("upscaling non attivo") if up else ""))
        sub.append(f"BC-250 · {s.get('cores', '?')} core / {s.get('threads', '?')} thread")
        p.drawText(QRectF(20, 38, 520, 16), Qt.AlignmentFlag.AlignLeft, "  ·  ".join(sub))

        # --- badge limite FPS
        limit = g.get("limit") if g else None
        if not eng.get("limit_enabled", True):
            badge, col = T("LIMITE FPS DISATTIVATO"), P["WARN"]
        elif g and g.get("guard_cut"):
            badge, col = T("LIMITE {v} FPS · PROTEZIONE CALORE", v=limit), P["WARN"]
        elif g and limit:
            badge, col = T("LIMITE {v} FPS · ATTIVO", v=limit), P["GOOD"]
        elif g:
            badge, col = T("NESSUN LIMITE FPS"), P["MUTED"]
        else:
            gl = eng.get("fps_limit")
            badge, col = (T("LIMITE {v} FPS · PRONTO", v=gl) if gl else T("NESSUN LIMITE")), P["ACCENT"]
        p.setFont(font(8.5, True))
        bw = QFontMetrics(font(8.5, True)).horizontalAdvance(badge) + 24
        br = QRectF(W - 20 - bw, 18, bw, 26)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(qc(col, 45))
        p.drawRoundedRect(br, 13, 13)
        p.setPen(qc(col))
        p.drawText(br, Qt.AlignmentFlag.AlignCenter, badge)

        # --- FPS + frametime
        fr = QRectF(20, 64, W - 40, 128)
        self.card(p, fr, "Frame")
        fps = g.get("fps")
        p.setFont(font(30, True))
        p.setPen(qc(fps_col(fps, limit)))
        p.drawText(QRectF(fr.left() + 14, fr.top() + 22, 150, 46), Qt.AlignmentFlag.AlignLeft,
                   f"{fps:.0f}" if fps else "—")
        fv = [v for v in self.hist["fps"] if v]
        p.setFont(font(9))
        p.setPen(qc(P["MUTED"]))
        lines = [
            T("media 60s") + (f"  {sum(fv) / len(fv):.0f}" if fv else "  —"),
            f"1% low     {g['low1']:.0f}" if g.get("low1") else "1% low     —",
            f"frametime  {g['frametime']:.1f} ms" if g.get("frametime") else "frametime  —",
        ]
        for i, ln in enumerate(lines):
            p.drawText(QRectF(fr.left() + 14, fr.top() + 70 + i * 16, 170, 16), Qt.AlignmentFlag.AlignLeft, ln)
        fts = g.get("frametimes") or []
        gr = QRectF(fr.left() + 190, fr.top() + 26, fr.width() - 204, fr.height() - 38)
        p.setPen(QPen(qc(P["BORDER"]), 1))
        p.drawLine(QPointF(gr.left(), gr.bottom()), QPointF(gr.right(), gr.bottom()))
        if fts:
            target = 1000.0 / limit if limit else sum(fts) / len(fts)
            vmax = max(target * 2, max(fts) * 1.1)
            ty = gr.bottom() - gr.height() * target / vmax
            p.setPen(QPen(qc(P["DIM"]), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(gr.left(), ty), QPointF(gr.right(), ty))
            draw_series(p, gr, fts, vmax, fps_col(fps, limit), width=1.4)
            p.setFont(font(7))
            p.setPen(qc(P["DIM"]))
            p.drawText(QRectF(gr.left(), gr.top() - 12, gr.width(), 12), Qt.AlignmentFlag.AlignRight,
                       T("frametime ultimi 120 frame (ms)"))

        # --- grafici sensori
        y = fr.bottom() + 12
        cw = (W - 40 - 3 * 12) / 4
        ch = 128
        gmax = gov.get("max") or 2000
        thr = gov.get("throttle") or 85
        self.graph_card(p, QRectF(20, y, cw, ch), "CPU", "cpu_temp", "°C", 100,
                        lambda v: temp_col(v, 80, 90), vmin=30)
        self.graph_card(p, QRectF(20 + (cw + 12), y, cw, ch), "GPU", "gpu_temp", "°C", 100,
                        lambda v: temp_col(v, thr - 10, thr), vmin=30)
        self.graph_card(p, QRectF(20 + 2 * (cw + 12), y, cw, ch), T("Clock GPU (max {v})", v=gmax), "gpu_clk", "",
                        max(2000, gmax), lambda v: P["BAD"] if st.get("throttling") else P["ACCENT"], vmin=0)
        self.graph_card(p, QRectF(20 + 3 * (cw + 12), y, cw, ch), T("Consumo"), "power", " W", 160,
                        lambda v: P["PURPLE"])

        # --- riga info
        y += ch + 12
        ir = QRectF(20, y, W - 40, 50)
        self.card(p, ir, T("Sistema"))
        ram = s.get("ram") or [0, 0]
        vram = s.get("vram") or [0, 0]
        info = [
            (T("Ventola"), f"{s.get('fan') or 0} rpm", P["TEXT"] if s.get("fan") else P["BAD"]),
            (T("Carico GPU"), f"{s.get('gpu_busy') or 0:.0f}%", P["TEXT"]),
            (T("Carico CPU"), f"{s.get('cpu_load') or 0:.0f}%", P["TEXT"]),
            ("RAM", f"{ram[0]:.1f}/{ram[1]:.0f} G", P["WARN"] if ram[1] and ram[0] / ram[1] > 0.9 else P["TEXT"]),
            ("VRAM", f"{(vram[0] or 0):.0f} M", P["TEXT"]),
            ("Governor", f"{gov.get('min') or '?'}–{gov.get('max') or '?'}", P["TEXT"]),
            (T("Taglio"), T("IN CORSO") if st.get("throttling") else f"{thr}°C",
             P["BAD"] if st.get("throttling") else P["TEXT"]),
        ]
        iw = (ir.width() - 24) / len(info)
        for i, (k, v, c) in enumerate(info):
            p.setFont(font(7))
            p.setPen(qc(P["DIM"]))
            p.drawText(QRectF(ir.left() + 12 + i * iw, ir.top() + 20, iw, 10), Qt.AlignmentFlag.AlignLeft, k)
            p.setFont(font(9, True))
            p.setPen(qc(c))
            p.drawText(QRectF(ir.left() + 12 + i * iw, ir.top() + 30, iw, 16), Qt.AlignmentFlag.AlignLeft, v)

        # --- profilo del gioco
        y += 50 + 12
        pr = QRectF(20, y, W - 40, 142)
        if g:
            self.draw_profile(p, pr, g)
        else:
            self.card(p, pr, T("Profilo del gioco"))
            p.setFont(font(9))
            p.setPen(qc(P["MUTED"]))
            p.drawText(pr, Qt.AlignmentFlag.AlignCenter, T("Avvia un gioco per modificarne il profilo da qui."))

        # --- avvisi + tasti
        p.setFont(font(8))
        alerts = st.get("alerts") or []
        if alerts:
            p.setPen(qc(P["BAD"]))
            p.drawText(QRectF(20, H - 26, W - 40, 16), Qt.AlignmentFlag.AlignLeft,
                       "⚠ " + "  ·  ".join(a["title"] for a in alerts))
        p.setPen(qc(P["DIM"]))
        p.drawText(QRectF(20, H - 26, W - 40, 16), Qt.AlignmentFlag.AlignRight,
                   T("Shift+F1 limite FPS   Shift+F2 pannello   Shift+F3 overlay"))
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
        p.setBrush(qc(P["BG"], 235))
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), 22, 22)
        # avvisi di "spento" in giallo (testi in italiano e nella lingua attuale)
        off = ("DISATT", "nascosto", T("DISATTIVATO"), T("nascosto"))
        col = P["WARN"] if any(w in self.text for w in off) else P["ACCENT"]
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
    app.setQuitOnLastWindowClosed(False)
    _c = Controller(app)  # noqa: F841
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
