"""bc250-run: lanciatore universale. Opzioni di avvio del gioco:  bc250-run %command%

Legge il profilo del gioco (per SteamAppId o per testo nel comando) e:
  - upscale: fa girare il gioco dentro gamescope a risoluzione ridotta, ingrandito con FSR 1
    (vale per qualsiasi gioco: Vulkan, OpenGL, Proton, Lutris, Heroic)
  - opengl: carica il motore FPS OpenGL (come bc250-gl)
Senza niente da fare lancia il gioco così com'è. Non deve mai impedire l'avvio del gioco.
"""
import glob
import os
import shutil
import sys
import time

from . import common

# preset: frazione della risoluzione dello schermo su ogni lato (come i preset FSR)
UPSCALE = {"q77": 0.77, "q67": 2 / 3, "q59": 0.59, "q50": 0.5}
LOG = os.path.join(common.DATA_DIR, "run.log")


def log(msg):
    try:
        os.makedirs(common.DATA_DIR, exist_ok=True)
        with open(LOG, "a") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except OSError:
        pass


def find_profile(cfg, args):
    appid = os.environ.get("SteamAppId") or os.environ.get("SteamGameId") or ""
    text = " ".join(args).lower()
    for p in cfg.get("profiles", []):
        m = str(p.get("match", "")).strip()
        if not m:
            continue
        if m.startswith("appid:"):
            if appid and m[6:] == appid:
                return p
        elif m.lower() in text:
            return p
    return None


def screen():
    """(larghezza, altezza, Hz) dello schermo in uso."""
    try:
        from .health import vrr_outputs
        for o in vrr_outputs():
            if "@" in o.get("mode", ""):
                size, hz = o["mode"].split("@")
                w, h = size.split("x")
                return int(w), int(h), int(float(hz))
    except Exception:
        pass
    for c in sorted(glob.glob("/sys/class/drm/card*-*")):
        try:
            if open(f"{c}/status").read().strip() == "connected":
                w, h = open(f"{c}/modes").readline().strip().split("x")
                return int(w), int(h), 60
        except (OSError, ValueError):
            continue
    return 1920, 1080, 60


def even(x):
    return max(2, int(round(x / 2)) * 2)


def build(args, cfg, prof):
    env = {}
    cmd = list(args)
    if prof and prof.get("opengl"):
        lib = os.path.join(common.LIB_DIR, "libbc250_gl.so")
        env["LD_PRELOAD"] = lib + (":" + os.environ["LD_PRELOAD"] if os.environ.get("LD_PRELOAD") else "")
    scale = UPSCALE.get((prof or {}).get("upscale"))
    if scale and shutil.which("gamescope") and not os.environ.get("GAMESCOPE_WAYLAND_DISPLAY"):
        ow, oh, hz = screen()
        d = cfg.get("display", {})
        gs = ["gamescope", "-W", str(ow), "-H", str(oh), "-w", str(even(ow * scale)), "-h", str(even(oh * scale)),
              "-r", str(hz), "-F", d.get("upscale_filter", "fsr"),
              "--fsr-sharpness", str(d.get("upscale_sharpness", 3)), "-f", "--force-grab-cursor"]
        if prof.get("vrr"):
            gs.append("--adaptive-sync")
        cmd = gs + ["--"] + cmd
    return cmd, env


def main():
    args = sys.argv[1:]
    if not args:
        print("uso: bc250-run %command%   (nelle opzioni di avvio del gioco)", file=sys.stderr)
        return 2
    try:
        cfg = common.load_config()
        prof = find_profile(cfg, args)
        cmd, env = build(args, cfg, prof)
        how = " ".join(cmd[:cmd.index("--")]) if cmd[0] == "gamescope" else "diretto"
        log(f"{(prof or {}).get('name', '-')}: {how} | {args[-1]}")
    except Exception as ex:   # il gioco deve partire comunque
        log(f"errore, lancio diretto: {ex!r}")
        cmd, env = args, {}
    os.environ.update(env)
    os.environ["BC250_RUN"] = "1"   # il servizio sa che il gioco è passato dal lanciatore
    # il percorso dell'app serviva solo a noi: il gioco parte con l'ambiente di prima
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    pp = [x for x in os.environ.get("PYTHONPATH", "").split(":") if x and x != root]
    if pp:
        os.environ["PYTHONPATH"] = ":".join(pp)
    else:
        os.environ.pop("PYTHONPATH", None)
    os.execvp(cmd[0], cmd)


if __name__ == "__main__":
    sys.exit(main())
