# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""bc250ctl: comandi rapidi (usati dalle scorciatoie da tastiera).

  bc250ctl toggle-limit     Shift+F1  limite FPS on/off
  bc250ctl toggle-panel     Shift+F2  pannello dettagli
  bc250ctl toggle-hud       Shift+F3  overlay minimal on/off
  bc250ctl limit <n|off>    imposta il limite globale
  bc250ctl status           stato attuale (JSON)
"""
import json
import sys

from . import common
from .engine import write_control
from .i18n import T


def _limit_text(cfg):
    e = cfg["engine"]
    st = common.read_state()
    prof = (st.get("game") or {}).get("profile")
    lim = e["fps_limit"]
    for p in cfg.get("profiles", []):
        if p.get("name") == prof and p.get("fps_limit") is not None:
            lim = p["fps_limit"]
    if not e["limit_enabled"]:
        return T("Limite FPS: DISATTIVATO")
    return T("Limite FPS: {lim} ATTIVO", lim=lim) if lim else T("Limite FPS: nessuno")


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "status"
    if cmd == "toggle-limit":
        cfg = common.update_config(lambda c: c["engine"].update(limit_enabled=not c["engine"]["limit_enabled"]))
        e = cfg["engine"]
        write_control(e["fps_limit"], e["limit_enabled"], e["enabled"])  # effetto immediato
        common.overlay_send("toast:" + _limit_text(cfg))
    elif cmd == "limit" and len(argv) > 1:
        v = 0 if argv[1] in ("off", "0") else int(argv[1])
        cfg = common.update_config(lambda c: c["engine"].update(fps_limit=v, limit_enabled=bool(v)))
        e = cfg["engine"]
        write_control(e["fps_limit"], e["limit_enabled"], e["enabled"])
        common.overlay_send("toast:" + _limit_text(cfg))
    elif cmd == "toggle-panel":
        common.overlay_send("toggle-panel")
    elif cmd == "toggle-hud":
        cfg = common.update_config(lambda c: c["overlay"].update(hud_visible=not c["overlay"]["hud_visible"]))
        common.overlay_send("toast:" + (T("Overlay visibile") if cfg["overlay"]["hud_visible"] else T("Overlay nascosto")))
    elif cmd == "status":
        print(json.dumps(common.read_state(), indent=2, ensure_ascii=False))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
