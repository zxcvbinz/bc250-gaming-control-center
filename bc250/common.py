# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""Percorsi, configurazione e stato condivisi tra servizio, overlay, GUI e MCP."""
import copy
import json
import os
import socket

HOME = os.path.expanduser("~")
UID = os.getuid()
CONF_DIR = os.path.join(HOME, ".config/bc250")
CONF_PATH = os.path.join(CONF_DIR, "config.json")
DATA_DIR = os.path.join(HOME, ".local/share/bc250")
DB_PATH = os.path.join(DATA_DIR, "history.db")
LIB_DIR = os.path.join(HOME, ".local/lib/bc250")
SHM_DIR = f"/dev/shm/bc250-{UID}"                       # giochi nativi e Steam
RUN_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{UID}"), "bc250")  # Flatpak
FRAME_DIRS = [SHM_DIR, RUN_DIR]
STATE_PATH = os.path.join(SHM_DIR, "state.json")
OVERLAY_SOCK = os.path.join(SHM_DIR, "overlay.sock")
LAYER_MANIFEST = os.path.join(HOME, ".local/share/vulkan/implicit_layer.d/bc250_frame.json")
MANGOHUD_FLAG = os.path.join(CONF_DIR, "mangohud-disabled")

DEFAULTS = {
    "language": "it",             # lingua dell'interfaccia (vedi i18n.LANGS)
    "engine": {
        "enabled": True,          # motore FPS nei giochi Vulkan/Proton
        "fps_limit": 60,          # limite globale
        "limit_enabled": True,    # Shift+F1
    },
    "overlay": {
        "hud_visible": True,      # Shift+F3
        "only_in_game": True,
        "position": "top-left",   # top-left top-center top-right bottom-left bottom-right
        "margin": 24,
        "scale": 1.0,
        "opacity": 0.82,
        "items": ["fps", "frametime", "cpu_temp", "gpu_temp", "gpu_clk", "power"],
        "graph": True,
        "style": "bubble",        # bubble (cerchio intelligente), ring (anello completo), compact, full
        # aspetto dei valori (anello, barra, completo): vedi hudpaint.LOOK_DEFAULT
        "look": {"labels": True, "border": False, "limit_badge": True, "colors": "status", "accent": "#ffb000"},
        # cerchio: mostra solo un valore e si allarga quando qualcosa richiede attenzione
        "bubble": {
            "center": "fps",      # fps, cpu_temp, gpu_temp, power
            "idle": "visible",    # visible, faded, hidden: come resta quando va tutto bene
            "hold_s": 8,          # quanto resta allargato dopo che il problema è sparito
            "watch": ["cpu_temp", "gpu_temp", "fps_drop", "stutter", "throttling", "ram", "fan"],
            "cpu_temp": 85, "gpu_temp": 80,
            "fps_drop_pct": 85,   # sotto l'85% del limite FPS
            "fps_min": 40,        # obiettivo quando non c'è un limite
            "stutter_pct": 50,    # 1% low sotto metà degli FPS
            "ram_pct": 90,
        },
    },
    "alerts": {
        "enabled": True,
        "cpu_temp": 90,
        "gpu_temp": 88,
        "fan_min_rpm": 400,
        "cooldown_s": 180,
    },
    # merge_gap_s: se lo stesso gioco riprende entro questo tempo (alt+tab, caricamenti) è la stessa sessione
    "history": {"enabled": True, "keep_days": 60, "merge_gap_s": 300},
    # VRR acceso solo mentre un gioco è attivo; sul desktop sempre spento
    # upscale_*: usati da bc250-run per i profili con upscaling (gamescope)
    "display": {"vrr_games_only": True, "vrr_off_delay_s": 8, "upscale_filter": "fsr", "upscale_sharpness": 3},
    "gpu_default": {"min": 1000, "max": 1750},
    # frequenza massima della CPU in MHz (None = nessun limite). Serve acpi-cpufreq (fix ACPI della
    # community, vedi docs/cpu.md) e il servizio bc250-cpufreq che dà il permesso di scrittura.
    "cpu": {"max_mhz": None},
    # mode per i giochi installati dopo: ask = notifica e chiedi se collegarli (bc250-run nelle opzioni
    # di avvio), auto = collega da solo, off = niente
    "launcher": {"auto": False, "mode": "ask"},
    # match: testo contenuto nel nome del processo, oppure "appid:<SteamAppId>"
    "profiles": [],
}

def _T(text, **kw):
    """Traduzione al momento della visualizzazione (import qui: i18n importa common)."""
    from .i18n import T
    return T(text, **kw)


# campi dei profili: (chiave, etichetta, valori, formato) — usati da pannello in gioco e GUI
# etichette e nomi restano in italiano come dati: si traducono con T() dove si mostrano
# risoluzione di rendering con gamescope + FSR 1 (serve "bc250-run %command%" nelle opzioni di avvio)
UPSCALE_NAMES = {None: "spento", "q77": "FSR 77% ultra qualità", "q67": "FSR 67% qualità",
                 "q59": "FSR 59% bilanciato", "q50": "FSR 50% prestazioni"}
STYLE_NAMES = {None: "come globale", "bubble": "cerchio", "ring": "anello", "compact": "barra", "full": "completo"}
POS_NAMES = {None: "come globale", "top-left": "alto sinistra", "top-center": "alto centro",
             "top-right": "alto destra", "bottom-left": "basso sinistra", "bottom-center": "basso centro", "bottom-right": "basso destra"}
PROFILE_FIELDS = [
    ("fps_limit", "Limite FPS", [None, 0, 30, 40, 45, 50, 60, 72, 75, 82, 90, 100, 110, 120, 144, 165],
     lambda v, g: _T("globale") if v is None else (_T("nessuno") if v == 0 else _T("{v} FPS", v=v))),
    ("gpu_max", "Clock GPU max", [None] + list(range(1000, 2001, 50)),
     lambda v, g: _T("normale") if v is None else f"{v} MHz"),
    ("vrr", "VRR", [False, True], lambda v, g: _T("automatico") if v else _T("spento")),
    ("heat_guard", "Protezione calore", [None, 80, 82, 85, 88, 90],
     lambda v, g: _T("spenta") if v is None else f"CPU {v}°C"),
    ("hud", "Overlay", [True, False], lambda v, g: _T("visibile") if v in (True, None) else _T("nascosto")),
    ("hud_position", "Posizione overlay", list(POS_NAMES), lambda v, g: _T(POS_NAMES.get(v, str(v)))),
    ("hud_style", "Stile overlay", list(STYLE_NAMES), lambda v, g: _T(STYLE_NAMES.get(v, str(v)))),
    ("upscale", "Upscaling FSR", list(UPSCALE_NAMES), lambda v, g: _T(UPSCALE_NAMES.get(v, str(v)))),
    ("cpu_max", "Frequenza CPU max", [None, 0, 3200, 2550, 2325, 1960, 1820, 1600],
     lambda v, g: _T("globale") if v is None else (_T("nessun limite") if v == 0 else f"{v} MHz")),
]
FIELD_DEFAULT = {"fps_limit": None, "gpu_max": None, "vrr": False, "heat_guard": None, "hud": True,
                 "hud_position": None, "hud_style": None,
                 "upscale": None, "cpu_max": None}

# stile «Cockpit»: nero caldo, ambra come accento, ciano per i clock
PALETTE = {
    "BG": "#0c0d0a", "SIDEBAR": "#0f100c", "CARD": "#12130f", "CARD2": "#1a1a14",
    "BORDER": "#2c2c25", "TEXT": "#e8e4d8", "MUTED": "#a39f8f", "DIM": "#7a7668",
    "ACCENT": "#ffb000", "GOOD": "#7fd88f", "WARN": "#ff8a3d", "BAD": "#ff5a4a",
    "OFF": "#22221c", "PURPLE": "#b48cff", "CYAN": "#5ad1e6", "ON_ACCENT": "#12130f",
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config():
    try:
        with open(CONF_PATH) as f:
            user = json.load(f)
    except (OSError, ValueError):
        user = {}
    return _merge(DEFAULTS, user)


def save_config(cfg):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, CONF_PATH)


def update_config(fn):
    cfg = load_config()
    fn(cfg)
    save_config(cfg)
    return cfg


def read_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_json_atomic(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def overlay_send(cmd):
    """Manda un comando all'overlay (toggle-panel, toggle-hud, toast:<testo>)."""
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.sendto(cmd.encode(), OVERLAY_SOCK)
        s.close()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------- frequenza CPU (cpufreq)
# Solo i file standard di Linux in sysfs: niente registri. Senza driver cpufreq tutto è un no-op.
CPU_SYS = "/sys/devices/system/cpu"


def _cpufreq_dirs():
    out = []
    try:
        names = os.listdir(CPU_SYS)
    except OSError:
        return out
    for n in sorted(names):
        d = os.path.join(CPU_SYS, n, "cpufreq")
        if n.startswith("cpu") and n[3:].isdigit() and os.path.isdir(d):
            out.append(d)
    return out


def cpufreq_info():
    """None senza cpufreq; altrimenti driver, frequenze (MHz), massimo hardware e massimo attuale."""
    dirs = _cpufreq_dirs()
    if not dirs:
        return None

    def rd(name, d=dirs[0]):
        try:
            with open(os.path.join(d, name)) as f:
                return f.read().strip()
        except OSError:
            return ""
    steps = sorted({int(x) // 1000 for x in rd("scaling_available_frequencies").split() if x.isdigit()}, reverse=True)
    hw_max = int(rd("cpuinfo_max_freq") or 0) // 1000
    caps = {int(rd("scaling_max_freq", d) or 0) // 1000 for d in dirs}
    writable = all(os.access(os.path.join(d, "scaling_max_freq"), os.W_OK) for d in dirs)
    return {"driver": rd("scaling_driver"), "steps": steps, "hw_max": hw_max, "max": max(caps),
            "uniform": len(caps) == 1, "writable": writable, "cpus": len(dirs)}


def set_cpu_max(mhz):
    """Imposta il tetto di frequenza su tutte le CPU (None/0 = massimo hardware). True se riuscito."""
    info = cpufreq_info()
    if not info:
        return False
    target = info["hw_max"] if not mhz else min(int(mhz), info["hw_max"])
    ok = True
    for d in _cpufreq_dirs():
        try:
            with open(os.path.join(d, "scaling_max_freq"), "w") as f:
                f.write(str(target * 1000))
        except OSError:
            ok = False
    return ok
