"""Installazione / aggiornamento del Centro di controllo BC-250.

Tutto in file utente, tranne la correzione del clock GPU per le BC-250 a 8 core
(servizio di sistema, chiede sudo; si salta se sudo non è disponibile).

python3 -m bc250.install            installa o aggiorna tutto
python3 -m bc250.install --remove   rimuove servizi, scorciatoie, motore e collegamenti
"""
import json
import os
import re
import shutil
import subprocess
import sys

from . import common

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(common.HOME, ".local/bin")
APPS = os.path.join(common.HOME, ".local/share/applications")
UNITS = os.path.join(common.HOME, ".config/systemd/user")
BASHRC = os.path.join(common.HOME, ".bashrc")

COMMANDS = {
    "bc250d": "bc250.daemon",
    "bc250-overlay": "bc250.overlay",
    "bc250-control": "bc250.gui",
    "bc250ctl": "bc250.ctl",
    "bc250-mcp": "bc250.mcp_server",
}
# (file .desktop, azione, nome, tasti Qt, comando)
SHIFT = 0x02000000
SHORTCUTS = [
    ("bc250-limit.desktop", "BC-250: limite FPS on/off", SHIFT | 0x01000030, "toggle-limit"),
    ("bc250-panel.desktop", "BC-250: pannello dettagli", SHIFT | 0x01000031, "toggle-panel"),
    ("bc250-hud.desktop", "BC-250: overlay on/off", SHIFT | 0x01000032, "toggle-hud"),
]
FLATPAK_GL_APPS = ["com.hypixel.HytaleLauncher"]


def run(cmd, check=False):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)}: {r.stderr.strip()}")
    return r


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


def build_layer():
    run(["make", "-C", os.path.join(ROOT, "layer"), "install"], check=True)


def install_layer_manifest():
    manifest = {
        "file_format_version": "1.2.0",
        "layer": {
            "name": "VK_LAYER_BC250_frame",
            "type": "GLOBAL",
            "library_path": os.path.join(common.LIB_DIR, "libbc250_vk.so"),
            "api_version": "1.3.0",
            "implementation_version": "1",
            "description": "BC-250 FPS counter and limiter",
            "functions": {"vkGetInstanceProcAddr": "bc250_GetInstanceProcAddr",
                          "vkGetDeviceProcAddr": "bc250_GetDeviceProcAddr"},
            "disable_environment": {"DISABLE_BC250_LAYER": "1"},
        },
    }
    write(common.LAYER_MANIFEST, json.dumps(manifest, indent=2) + "\n")


def install_commands():
    for name, module in COMMANDS.items():
        write(os.path.join(BIN, name),
              f'#!/bin/sh\ncd "{ROOT}" && exec python3 -m {module} "$@"\n', 0o755)
    # lanciatore universale (opzioni di avvio: bc250-run %command%): senza cd, il gioco
    # deve partire nella sua cartella
    write(os.path.join(BIN, "bc250-run"),
          f'#!/bin/sh\nexport PYTHONPATH="{ROOT}${{PYTHONPATH:+:$PYTHONPATH}}"\nexec python3 -m bc250.run "$@"\n', 0o755)
    # per i giochi Steam OpenGL nativi:  bc250-gl %command%
    write(os.path.join(BIN, "bc250-gl"),
          f'#!/bin/sh\nexport LD_PRELOAD="{common.LIB_DIR}/libbc250_gl.so${{LD_PRELOAD:+:$LD_PRELOAD}}"\nexec "$@"\n',
          0o755)


def install_units():
    write(os.path.join(UNITS, "bc250d.service"), f"""[Unit]
Description=BC-250 Control Center - servizio sensori, FPS, storico e avvisi
After=graphical-session.target

[Service]
ExecStart={BIN}/bc250d
Restart=always
RestartSec=3
Nice=5

[Install]
WantedBy=graphical-session.target
""")
    write(os.path.join(UNITS, "bc250-overlay.service"), f"""[Unit]
Description=BC-250 Control Center - overlay in gioco
PartOf=graphical-session.target
After=graphical-session.target bc250d.service

[Service]
ExecStart={BIN}/bc250-overlay
Restart=always
RestartSec=3

[Install]
WantedBy=graphical-session.target
""")
    run(["systemctl", "--user", "daemon-reload"])
    run(["systemctl", "--user", "enable", "bc250d.service", "bc250-overlay.service"])
    run(["systemctl", "--user", "restart", "bc250d.service", "bc250-overlay.service"])


def install_desktop():
    icon = os.path.join(ROOT, "bc250", "assets", "icon.svg")
    write(os.path.join(APPS, "bc250-control.desktop"), f"""[Desktop Entry]
Type=Application
Name=BC-250 Control Center
GenericName=Centro di controllo BC-250
Comment=Temperature, FPS, overlay, profili giochi, VRR e salute della BC-250
Exec={BIN}/bc250-control
Icon={icon}
Categories=System;Monitor;Settings;
Terminal=false
StartupWMClass=bc250-control
""")
    old = os.path.join(APPS, "bc250-monitor.desktop")
    if os.path.exists(old):
        os.remove(old)
    for desktop, name, _key, cmd in SHORTCUTS:
        write(os.path.join(APPS, desktop), f"""[Desktop Entry]
Type=Application
Name={name}
Exec={BIN}/bc250ctl {cmd}
NoDisplay=true
StartupNotify=false
Terminal=false
""")
    run(["update-desktop-database", APPS])


def register_shortcuts():
    """Registra le scorciatoie globali in KDE (KGlobalAccel), come fa Impostazioni di sistema."""
    ok = True
    for desktop, name, key, _cmd in SHORTCUTS:
        r1 = run(["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel",
                  "org.kde.KGlobalAccel", "doRegister", "as", "4", desktop, "_launch", name, name])
        r2 = run(["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel",
                  "org.kde.KGlobalAccel", "setShortcut", "asaiu", "4", desktop, "_launch", name, name,
                  "1", str(key), "4"])
        ok = ok and r1.returncode == 0 and r2.returncode == 0
    return ok


def disable_mangohud_global():
    """Sostituisce `export MANGOHUD=1` in ~/.bashrc con una versione controllata da un file flag."""
    line = '[ -f "$HOME/.config/bc250/mangohud-disabled" ] || export MANGOHUD=1'
    try:
        txt = open(BASHRC).read()
    except OSError:
        txt = ""
    if line not in txt and re.search(r"^export MANGOHUD=1\s*$", txt, re.M):
        shutil.copy2(BASHRC, BASHRC + ".bak-bc250")
        txt = re.sub(r"^export MANGOHUD=1\s*$", line, txt, flags=re.M)
        write(BASHRC, txt)
    os.makedirs(common.CONF_DIR, exist_ok=True)
    open(common.MANGOHUD_FLAG, "w").close()


def flatpak_gl(app, on=True):
    if on:
        run(["flatpak", "override", "--user",
             f"--filesystem={common.LIB_DIR}:ro", "--filesystem=xdg-run/bc250:create",
             f"--env=LD_PRELOAD={common.LIB_DIR}/libbc250_gl.so",
             f"--env=BC250_DIR={common.RUN_DIR}", app])
    else:
        run(["flatpak", "override", "--user", "--unset-env=LD_PRELOAD", "--unset-env=BC250_DIR",
             f"--nofilesystem={common.LIB_DIR}", "--nofilesystem=xdg-run/bc250", app])


def flatpak_gl_enabled(app):
    r = run(["flatpak", "override", "--user", "--show", app])
    return "libbc250_gl.so" in r.stdout


def register_mcp():
    claude = shutil.which("claude") or os.path.join(common.HOME, ".local/bin/claude")
    if not os.path.exists(claude):
        return False
    run([claude, "mcp", "remove", "-s", "user", "bc250"])
    r = run([claude, "mcp", "add", "-s", "user", "bc250", "--", os.path.join(BIN, "bc250-mcp")])
    return r.returncode == 0


SYS_LIB = "/usr/local/lib/bc250"
SYS_UNIT = "/etc/systemd/system/bc250-metricsfix.service"
GOV_UNIT = "cyan-skillfish-governor-smu.service"
METRICSFIX_UNIT = f"""[Unit]
Description=BC-250: real GPU clock in gpu_metrics and pp_dpm_sclk (8-core unlock)
After={GOV_UNIT}
PartOf={GOV_UNIT}

[Service]
Type=simple
ExecStart=/usr/bin/python3 -I {SYS_LIB}/metricsfix.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy={GOV_UNIT}
"""


def sudo(cmd, input=None):
    r = subprocess.run(["sudo", "-n"] + cmd, input=input, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip() or f"sudo {' '.join(cmd)} fallito")
    return r


def install_metrics_fix():
    """Copia root-owned dello script (il servizio gira come root: niente codice modificabile dall'utente)."""
    if run(["systemctl", "cat", GOV_UNIT]).returncode != 0:
        return False  # serve cyan-skillfish-governor con fix-freq
    sudo(["install", "-D", "-m", "0644", "-o", "root", "-g", "root",
          os.path.join(ROOT, "bc250", "metricsfix.py"), f"{SYS_LIB}/metricsfix.py"])
    sudo(["tee", SYS_UNIT], input=METRICSFIX_UNIT)
    sudo(["systemctl", "daemon-reload"])
    sudo(["systemctl", "enable", "bc250-metricsfix.service"])
    sudo(["systemctl", "restart", "bc250-metricsfix.service"])


def remove_metrics_fix():
    try:
        sudo(["systemctl", "disable", "--now", "bc250-metricsfix.service"])
        sudo(["rm", "-f", SYS_UNIT, f"{SYS_LIB}/metricsfix.py"])
        sudo(["systemctl", "daemon-reload"])
    except RuntimeError:
        pass


def install():
    steps = [
        ("Compilo il motore FPS", build_layer),
        ("Attivo il motore nei giochi Vulkan/Proton", install_layer_manifest),
        ("Comandi in ~/.local/bin", install_commands),
        ("Menu applicazioni", install_desktop),
        ("Servizi in background", install_units),
        ("Scorciatoie Shift+F1/F2/F3", register_shortcuts),
        ("Tolgo MangoHud dai giochi (dal prossimo accesso)", disable_mangohud_global),
        ("Motore OpenGL per Hytale (Flatpak)", lambda: [flatpak_gl(a) for a in FLATPAK_GL_APPS]),
        ("Server MCP per Claude Code", register_mcp),
        ("Clock GPU reale per MangoHud/Steam/LACT (8 core, sudo)", install_metrics_fix),
    ]
    if not os.path.exists(common.CONF_PATH):
        common.save_config(common.load_config())
    for title, fn in steps:
        try:
            res = fn()
            print(f"  ✓ {title}" + ("" if res is not False else "  (da verificare)"))
        except Exception as e:
            print(f"  ✗ {title}: {e}")


def remove():
    run(["systemctl", "--user", "disable", "--now", "bc250d.service", "bc250-overlay.service"])
    for f in ("bc250d.service", "bc250-overlay.service"):
        try:
            os.remove(os.path.join(UNITS, f))
        except OSError:
            pass
    for desktop, *_ in SHORTCUTS:
        run(["busctl", "--user", "call", "org.kde.kglobalaccel", "/kglobalaccel",
             "org.kde.KGlobalAccel", "unRegister", "as", "2", desktop, "_launch"])
    for f in [common.LAYER_MANIFEST] + [os.path.join(APPS, d) for d, *_ in SHORTCUTS] + \
             [os.path.join(APPS, "bc250-control.desktop")] + [os.path.join(BIN, n) for n in COMMANDS] + \
             [os.path.join(BIN, "bc250-gl"), os.path.join(BIN, "bc250-run"), common.MANGOHUD_FLAG]:
        try:
            os.remove(f)
        except OSError:
            pass
    for a in FLATPAK_GL_APPS:
        flatpak_gl(a, False)
    remove_metrics_fix()
    print("Rimosso. MangoHud tornerà attivo dal prossimo accesso.")


if __name__ == "__main__":
    remove() if "--remove" in sys.argv else install()
