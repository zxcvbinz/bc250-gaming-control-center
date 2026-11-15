# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""Controllo salute BC-250: ogni voce ha stato, dettaglio e (se possibile) una correzione."""
import json
import os
import subprocess
import time

from . import common
from .i18n import T


def sh(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout.strip()
    except Exception as e:
        return 1, str(e)


def user_active(unit):
    return sh(["systemctl", "--user", "is-active", unit])[1] == "active"


def sys_active(unit):
    return sh(["systemctl", "is-active", unit])[1] == "active"


def sys_enabled(unit):
    return sh(["systemctl", "is-enabled", unit])[1] == "enabled"


def vrr_outputs():
    code, out = sh(["kscreen-doctor", "-j"])
    if code != 0:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    names = {0: "never", 1: "always", 2: "automatic"}
    res = []
    for o in data.get("outputs", []):
        if not o.get("enabled"):
            continue
        mode = next((m for m in o.get("modes", []) if m.get("id") == o.get("currentModeId")), {})
        res.append({
            "name": o["name"], "vrr": names.get(o.get("vrrPolicy"), str(o.get("vrrPolicy"))),
            "mode": f"{mode.get('size', {}).get('width')}x{mode.get('size', {}).get('height')}"
                    f"@{mode.get('refreshRate', 0):.0f}" if mode else "?",
            "modes": [{"id": m["id"], "w": m["size"]["width"], "h": m["size"]["height"],
                       "hz": m["refreshRate"]} for m in o.get("modes", [])],
            "current_mode": o.get("currentModeId"),
        })
    return res


def set_vrr(output, policy):
    """Cambia il VRR e riapplica la modalità attuale: senza il reset la scheda
    video può restare col VRR vecchio (successo il 2026-11-14: sfarfallio sul desktop)."""
    ok = sh(["kscreen-doctor", f"output.{output}.vrrpolicy.{policy}"])[0] == 0
    cur = next((o for o in vrr_outputs() if o["name"] == output), None)
    if ok and cur and cur["current_mode"]:
        other = next((m["id"] for m in cur["modes"] if m["id"] != cur["current_mode"]
                      and (m["w"], m["h"]) == next(((x["w"], x["h"]) for x in cur["modes"]
                                                     if x["id"] == cur["current_mode"]), None)), None)
        if other:
            sh(["kscreen-doctor", f"output.{output}.mode.{other}"])
            time.sleep(2)
            sh(["kscreen-doctor", f"output.{output}.mode.{cur['current_mode']}"])
    return ok


def mangohud_global():
    """True se MangoHud viene ancora caricato in tutti i giochi (MANGOHUD=1 nella sessione)."""
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            if open(f"/proc/{p}/comm").read().strip() != "plasmashell":
                continue
            return b"MANGOHUD=1" in open(f"/proc/{p}/environ", "rb").read().split(b"\0")
        except OSError:
            continue
    return None


def checks():
    """Lista di dict: id, title, ok (True/False/None=info), detail, fix (testo pulsante o None)."""
    st = common.read_state()
    s = st.get("sensors") or {}
    fresh = time.time() - st.get("ts", 0) < 5
    out = []

    def add(id_, title, ok, detail, fix=None):
        out.append({"id": id_, "title": title, "ok": ok, "detail": detail, "fix": fix})

    add("daemon", T("Servizio BC-250 (bc250d)"), user_active("bc250d.service") and fresh,
        T("Raccoglie sensori, FPS, storico e avvisi.") if fresh else T("Non risponde: niente overlay, storico e avvisi."),
        T("Riavvia"))
    add("overlay", T("Overlay in gioco"), user_active("bc250-overlay.service"),
        T("HUD, pannello Shift+F2 e avvisi a schermo."), T("Riavvia"))
    add("layer", T("Motore FPS (Vulkan / Proton)"), os.path.exists(common.LAYER_MANIFEST),
        T("Conta gli FPS e applica il limite in tutti i giochi Vulkan."), T("Installa"))
    mh = mangohud_global()
    flag = os.path.exists(common.MANGOHUD_FLAG)
    if mh and flag:
        add("mangohud", T("MangoHud rimosso dai giochi"), "warn",
            T("Disattivato, ma vale dal prossimo accesso: esci e rientra nella sessione."))
    else:
        add("mangohud", T("MangoHud rimosso dai giochi"), not mh,
            T("MangoHud è ancora caricato in tutti i giochi (doppio HUD/limite).") if mh else
            T("Il motore BC-250 lo sostituisce."), T("Disattiva") if mh else None)
    gov = sys_active("cyan-skillfish-governor-smu")
    add("governor", T("Governor GPU"), gov,
        T("Gestisce clock e tensione della GPU e taglia a {t}°C.", t=(st.get('governor') or {}).get('throttle') or '?')
        if gov else T("FERMO: la GPU resta a clock fisso!"),
        None if gov else T("Avvia"))
    clk, g = s.get("gpu_clk"), st.get("governor") or {}
    if clk and g.get("max"):
        add("gpuclk", T("Lettura clock GPU"), 300 <= clk <= g["max"] + 60,
            f"{clk:.0f} MHz (range {g.get('min')}–{g['max']}).")
    cores = s.get("cores")
    add("cores", T("Sblocco 8 core"), cores == 8 if cores else None,
        T("{c} core / {t} thread attivi.", c=cores or '?', t=s.get('threads') or '?')
        + ("" if cores == 8 else " " + T("Il servizio bc250-8core riapplica lo sblocco a ogni avvio.")))
    add("8coresvc", T("Servizio sblocco all'avvio"), sys_enabled("bc250-8core.service"),
        T("bc250-8core.service abilitato."))
    fan = s.get("fan")
    add("fan", T("Ventola"), bool(fan and fan > 500), T("{v} rpm (gira sempre al massimo, non regolabile).", v=fan or 0))
    ct, gt = s.get("cpu_temp"), s.get("gpu_temp")
    load = s.get("cpu_load") or 0
    if ct:
        hot = ct >= 90 or (load < 15 and ct >= 72)
        add("temps", T("Temperature"), not hot,
            T("CPU {c:.0f}°C · GPU {g:.0f}°C con carico CPU {l:.0f}%.", c=ct, g=gt or 0, l=load)
            + (" " + T("Alte a riposo: controlla polvere/pasta termica.") if load < 15 and ct >= 72 else ""))
    nv = s.get("nvme_temp")
    if nv:
        add("nvme", "SSD NVMe", nv < 70, f"{nv:.0f}°C.")
    ram, swap = s.get("ram") or [0, 1], s.get("swap") or [0, 0]
    add("swap", "Swap / zram", swap[1] >= 16,
        T("{v:.0f} GiB disponibili (zram + swapfile): evita i freeze da RAM piena.", v=swap[1]))
    add("oomd", T("Protezione RAM (systemd-oomd)"), sys_active("systemd-oomd"),
        T("Chiude il processo che esaurisce la memoria invece di bloccare il PC."))
    add("ram", T("Memoria in uso"), ram[0] / ram[1] < 0.9 if ram[1] else None, f"{ram[0]:.1f} / {ram[1]:.1f} GiB.")
    outs = vrr_outputs()
    for o in outs:
        add(f"vrr-{o['name']}", f"VRR / FreeSync ({o['name']})", None,
            T("{m} Hz · VRR: {v}. Questo monitor col VRR cambia luminosità (sfarfallio): meglio tenerlo spento.",
              m=o['mode'], v=o['vrr']))
    return out


def fix(check_id):
    """Esegue la correzione di un controllo. Ritorna (ok, messaggio)."""
    if check_id == "daemon":
        return sh(["systemctl", "--user", "restart", "bc250d.service"])[0] == 0, T("Servizio riavviato.")
    if check_id == "overlay":
        return sh(["systemctl", "--user", "restart", "bc250-overlay.service"])[0] == 0, T("Overlay riavviato.")
    if check_id == "layer":
        from .install import install_layer_manifest
        install_layer_manifest()
        return True, T("Motore installato: vale dal prossimo avvio dei giochi.")
    if check_id == "mangohud":
        os.makedirs(common.CONF_DIR, exist_ok=True)
        open(common.MANGOHUD_FLAG, "w").close()
        return True, T("MangoHud disattivato: vale dal prossimo accesso alla sessione.")
    if check_id == "governor":
        return sh(["sudo", "-n", "systemctl", "start", "cyan-skillfish-governor-smu"])[0] == 0, T("Governor avviato.")
    if check_id.startswith("vrr-"):
        return set_vrr(check_id[4:], "automatic"), T("VRR impostato su automatico.")
    return False, T("Nessuna correzione automatica.")
