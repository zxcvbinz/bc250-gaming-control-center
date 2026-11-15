"""Mette (o toglie) «bc250-run» nelle opzioni di avvio di tutti i giochi: Steam, Lutris, Heroic.

bc250-run senza upscaling nel profilo lancia il gioco invariato, quindi metterlo ovunque è sicuro.
Steam riscrive localconfig.vdf quando si chiude: si modifica solo a Steam chiuso (lo chiudiamo
e riapriamo noi se serve). Ogni file viene salvato prima in ~/.local/share/bc250/backups/launchers/.
"""
import glob
import json
import os
import re
import shutil
import subprocess
import time

from . import common

TOKEN = "bc250-run"
BACKUP = os.path.join(common.DATA_DIR, "backups", "launchers")
STEAM_ROOTS = [os.path.expanduser(p) for p in ("~/.local/share/Steam", "~/.steam/steam", "~/.var/app/com.valvesoftware.Steam/.local/share/Steam")]
# app Steam che non sono giochi
TOOL_NAME = re.compile(r"proton|steam linux runtime|steamworks|redistributable|steamvr|sdk|dedicated server", re.I)


def backup(path):
    os.makedirs(BACKUP, exist_ok=True)
    dst = os.path.join(BACKUP, time.strftime("%Y%m%d-%H%M%S-") + os.path.basename(path))
    shutil.copy2(path, dst)
    return dst


# ---------------------------------------------------------------- VDF (KeyValues testuale di Valve)
_TOK = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])|//[^\n]*', re.S)


def vdf_loads(text):
    stack, cur, key = [], {}, None
    for m in _TOK.finditer(text):
        s, brace = m.group(1), m.group(2)
        if s is None and brace is None:
            continue   # commento
        if brace == "{":
            new = {}
            cur[key] = new
            stack.append(cur)
            cur, key = new, None
        elif brace == "}":
            cur = stack.pop()
        elif key is None:
            key = s
        else:
            cur[key] = s
            key = None
    return cur


def vdf_dumps(d, depth=0):
    out, tab = [], "\t" * depth
    for k, v in d.items():
        if isinstance(v, dict):
            out.append(f'{tab}"{k}"\n{tab}{{\n{vdf_dumps(v, depth + 1)}{tab}}}\n')
        else:
            out.append(f'{tab}"{k}"\t\t"{v}"\n')
    return "".join(out)


def _ci(d, *keys):
    """Scende nel dict ignorando maiuscole/minuscole, creando i livelli mancanti."""
    for k in keys:
        found = next((x for x in d if x.lower() == k.lower()), None)
        if found is None:
            d[k] = {}
            found = k
        d = d[found]
    return d


# ---------------------------------------------------------------- opzioni di avvio
def add_token(opts, drop_mangohud=False):
    """Inserisce bc250-run davanti a %command% conservando il resto ("" -> "bc250-run %command%")."""
    o = opts.strip()
    if drop_mangohud:
        o = re.sub(r"(^|\s)mangohud(\s+--dlsym)?(?=\s)", r"\1", o).strip()
    if TOKEN in o.split():
        return o
    if "%command%" in o:
        return o.replace("%command%", f"{TOKEN} %command%", 1)
    return f"{TOKEN} %command% {o}".strip()


def remove_token(opts):
    o = re.sub(rf"(^|\s){TOKEN}(?=\s)", r"\1", opts).strip()
    o = re.sub(r"\s{2,}", " ", o)
    return "" if o == "%command%" else o


# ---------------------------------------------------------------- Steam
def steam_pids():
    pids = []
    for p in glob.glob("/proc/[0-9]*/comm"):
        try:
            if open(p).read().strip() == "steam":
                pids.append(int(p.split("/")[2]))
        except (OSError, ValueError):
            pass
    return pids


def steam_root():
    for r in STEAM_ROOTS:
        if os.path.isdir(os.path.join(r, "steamapps")):
            return os.path.realpath(r)
    return None


def installed_games(root):
    libs = {os.path.join(root, "steamapps")}
    try:
        lf = vdf_loads(open(os.path.join(root, "steamapps", "libraryfolders.vdf"), errors="replace").read())
        for v in _ci(lf, "libraryfolders").values():
            if isinstance(v, dict) and v.get("path"):
                libs.add(os.path.join(v["path"], "steamapps"))
    except OSError:
        pass
    games = {}
    for lib in libs:
        for acf in glob.glob(os.path.join(lib, "appmanifest_*.acf")):
            try:
                st = _ci(vdf_loads(open(acf, errors="replace").read()), "AppState")
            except OSError:
                continue
            if st.get("appid") and not TOOL_NAME.search(st.get("name", "")):
                games[st["appid"]] = st.get("name", st["appid"])
    return games


def steam_configs(root):
    return [p for p in glob.glob(os.path.join(root, "userdata", "*", "config", "localconfig.vdf"))
            if not p.split("/userdata/")[1].startswith("0/")]


def steam_edit(enable, drop_mangohud=False, only_new=False, only=None):
    """Modifica localconfig.vdf (Steam deve essere chiuso). Ritorna {appid: (prima, dopo)}."""
    root = steam_root()
    if not root:
        return {}
    games = installed_games(root)
    changed = {}
    for cfgp in steam_configs(root):
        text = open(cfgp, errors="replace").read()
        data = vdf_loads(text)
        apps = _ci(data, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
        mine = {}
        for appid in games:
            if only is not None and appid not in only:
                continue
            a = apps.get(appid)
            if a is None:
                if not enable:
                    continue
                a = apps[appid] = {}
            old = a.get("LaunchOptions", "")
            plain_mh = drop_mangohud and re.fullmatch(r"\s*mangohud(\s+--dlsym)?\s+%command%\s*", old)
            if only_new and old.strip() and TOKEN not in old and not plain_mh:
                continue   # manutenzione automatica: non toccare giochi con opzioni proprie già scelte
            new = add_token(old, drop_mangohud) if enable else remove_token(old)
            if new != old:
                a["LaunchOptions"] = new
                mine[appid] = (old, new)
        if mine:
            backup(cfgp)
            tmp = cfgp + ".bc250tmp"
            open(tmp, "w").write(vdf_dumps(data))
            os.replace(tmp, cfgp)
            changed.update(mine)
    return {k: (games.get(k, k),) + v for k, v in changed.items()}


def steam_restart_args():
    for pid in steam_pids():
        try:
            args = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")[1:]
            return [a.decode() for a in args if a and a not in (b"-srt-logger-opened", b"-testoobeupdater")]
        except OSError:
            continue
    return ["-silent"]


def with_steam_closed(fn, restart=True, timeout=40):
    """Chiude Steam (se aperto), esegue fn(), lo riapre con gli stessi argomenti."""
    running = bool(steam_pids())
    args = steam_restart_args() if running else []
    if running:
        subprocess.run(["steam", "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        t0 = time.time()
        while steam_pids() and time.time() - t0 < timeout:
            time.sleep(0.5)
        if steam_pids():
            raise RuntimeError("Steam non si è chiuso: chiudilo e riprova")
        time.sleep(1)
    try:
        return fn()
    finally:
        if running and restart:
            subprocess.Popen(["setsid", "-f", "steam"] + args, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)


# ---------------------------------------------------------------- Lutris
LUTRIS_GAMES = "~/.local/share/lutris/games"


def lutris_edit(enable, only=None):
    import yaml
    changed = {}
    for p in glob.glob(os.path.expanduser(LUTRIS_GAMES + "/*.yml")):
        if only is not None and os.path.basename(p)[:-4] not in only:
            continue
        try:
            data = yaml.safe_load(open(p)) or {}
        except (OSError, yaml.YAMLError):
            continue
        sysc = data.get("system") or {}
        old = str(sysc.get("prefix_command") or "")
        g = data.get("game") or {}
        if enable and g.get("appid") and not g.get("exe"):
            continue   # gioco Steam lanciato da Lutris: passa già dalle opzioni di avvio di Steam
        if enable:
            new = old if TOKEN in old.split() else (f"{TOKEN} {old}".strip())
        else:
            new = " ".join(x for x in old.split() if x != TOKEN)
        if new == old:
            continue
        if new:
            sysc["prefix_command"] = new
        else:
            sysc.pop("prefix_command", None)
        data["system"] = sysc
        backup(p)
        with open(p, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        changed[os.path.basename(p)] = (os.path.basename(p), old, new)
    return changed


# ---------------------------------------------------------------- Heroic
def heroic_edit(enable, only=None):
    changed = {}
    for p in glob.glob(os.path.expanduser("~/.config/heroic/GamesConfig/*.json")):
        try:
            data = json.load(open(p))
        except (OSError, ValueError):
            continue
        for gid, gc in data.items():
            if not isinstance(gc, dict) or (only is not None and gid not in only):
                continue
            wr = gc.get("wrapperOptions") or []
            has = any(w.get("exe") == TOKEN for w in wr)
            if enable and not has:
                gc["wrapperOptions"] = [{"exe": TOKEN, "args": ""}] + wr
            elif not enable and has:
                gc["wrapperOptions"] = [w for w in wr if w.get("exe") != TOKEN]
            else:
                continue
            changed[gid] = (gid, has, not has)
        if any(k in changed for k in data):
            backup(p)
            json.dump(data, open(p, "w"), indent=2)
    return changed


# ---------------------------------------------------------------- tutto insieme
def apply_all(enable=True, restart_steam=True, drop_mangohud=None):
    """Applica a Steam (chiudendolo se serve), Lutris e Heroic. Ritorna il riepilogo."""
    if drop_mangohud is None:
        drop_mangohud = os.path.exists(common.MANGOHUD_FLAG)
    res = {"steam": {}, "lutris": {}, "heroic": {}, "errors": []}
    try:
        res["steam"] = with_steam_closed(lambda: steam_edit(enable, drop_mangohud), restart_steam)
    except Exception as e:
        res["errors"].append(f"Steam: {e}")
    for k, fn in (("lutris", lutris_edit), ("heroic", heroic_edit)):
        try:
            res[k] = fn(enable)
        except Exception as e:
            res["errors"].append(f"{k}: {e}")
    return res


def maintain():
    """Manutenzione automatica (dal servizio): aggiunge bc250-run ai giochi nuovi.
    Steam solo se è chiuso; giochi con opzioni di avvio già scelte dall'utente non vengono toccati."""
    out = {}
    if not steam_pids():
        out["steam"] = steam_edit(True, os.path.exists(common.MANGOHUD_FLAG), only_new=True)
    out["lutris"] = lutris_edit(True)
    out["heroic"] = heroic_edit(True)
    return out


def launched_with_run(pid):
    try:
        return b"BC250_RUN=1" in open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
    except OSError:
        return None


# ---------------------------------------------------------------- giochi nuovi: rileva e chiedi
KNOWN_PATH = os.path.join(common.DATA_DIR, "known_games.json")
# launcher.mode: ask = chiedi per ogni gioco nuovo, auto = collega da solo, off = non fare niente


def catalog():
    """Tutti i giochi installati: {"steam:275850": {"name", "store", "linked"}}."""
    out = {}
    root = steam_root()
    if root:
        games = installed_games(root)
        opts = {}
        for cfgp in steam_configs(root)[:1]:
            try:
                apps = _ci(vdf_loads(open(cfgp, errors="replace").read()),
                           "UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
                opts = {k: v.get("LaunchOptions", "") for k, v in apps.items() if isinstance(v, dict)}
            except OSError:
                pass
        for appid, name in games.items():
            out[f"steam:{appid}"] = {"name": name, "store": "Steam", "linked": TOKEN in opts.get(appid, "")}
    names = {}
    try:
        import sqlite3
        db = sqlite3.connect(os.path.expanduser("~/.local/share/lutris/pga.db"))
        names = {r[1]: r[0] for r in db.execute("SELECT name, configpath FROM games")}
    except Exception:
        pass
    try:
        import yaml
        for p in glob.glob(os.path.expanduser(LUTRIS_GAMES + "/*.yml")):
            cid = os.path.basename(p)[:-4]
            try:
                data = yaml.safe_load(open(p)) or {}
            except Exception:
                continue
            g = data.get("game") or {}
            if g.get("appid") and not g.get("exe"):
                continue   # gioco Steam
            pc = str((data.get("system") or {}).get("prefix_command") or "")
            pretty = re.sub(r"-\d+$", "", cid).replace("-", " ").title()
            out[f"lutris:{cid}"] = {"name": names.get(cid) or pretty, "store": "Lutris", "linked": TOKEN in pc.split()}
    except ImportError:
        pass
    for p in glob.glob(os.path.expanduser("~/.config/heroic/GamesConfig/*.json")):
        try:
            data = json.load(open(p))
        except (OSError, ValueError):
            continue
        for gid, gc in data.items():
            if isinstance(gc, dict):
                out[f"heroic:{gid}"] = {"name": gc.get("title") or gid, "store": "Heroic",
                                        "linked": any(w.get("exe") == TOKEN for w in gc.get("wrapperOptions") or [])}
    return out


def load_known():
    try:
        return json.load(open(KNOWN_PATH))
    except (OSError, ValueError):
        return {}


def save_known(known):
    os.makedirs(common.DATA_DIR, exist_ok=True)
    tmp = KNOWN_PATH + ".tmp"
    json.dump(known, open(tmp, "w"), indent=1, ensure_ascii=False)
    os.replace(tmp, KNOWN_PATH)


def pending():
    return {k: v for k, v in load_known().items() if v.get("status") == "pending"}


def _split(keys):
    by = {"steam": set(), "lutris": set(), "heroic": set()}
    for k in keys:
        store, _, gid = k.partition(":")
        if store in by:
            by[store].add(gid)
    return by


def link(keys, enable=True, restart_steam=False):
    """Collega (o scollega) i giochi indicati. I giochi Steam con Steam aperto restano in coda
    («queued») e vengono collegati alla prossima chiusura di Steam, a meno di restart_steam."""
    by = _split(keys)
    known = load_known()
    drop_mh = os.path.exists(common.MANGOHUD_FLAG)
    done, queued = [], []
    if by["lutris"]:
        lutris_edit(enable, by["lutris"])
        done += [f"lutris:{g}" for g in by["lutris"]]
    if by["heroic"]:
        heroic_edit(enable, by["heroic"])
        done += [f"heroic:{g}" for g in by["heroic"]]
    if by["steam"]:
        if steam_pids() and not restart_steam:
            queued += [f"steam:{g}" for g in by["steam"]]
        else:
            with_steam_closed(lambda: steam_edit(enable, drop_mh, only=by["steam"]), restart=True)
            done += [f"steam:{g}" for g in by["steam"]]
    for k in done:
        known.setdefault(k, {})["status"] = "linked" if enable else "ignored"
    for k in queued:
        known.setdefault(k, {})["status"] = "queued" if enable else "ignored"
    save_known(known)
    return done, queued


def ignore(keys):
    known = load_known()
    for k in keys:
        known.setdefault(k, {})["status"] = "ignored"
    save_known(known)


def scan(mode="ask"):
    """Dal servizio, ogni minuto: trova i giochi nuovi. Ritorna la lista dei nuovi da chiedere.
    Al primo giro tutti i giochi già installati sono «conosciuti» (niente domande per quelli vecchi)."""
    known = load_known()
    first = not known
    cat = catalog()
    new = []
    for k, g in cat.items():
        if k in known:
            known[k]["name"] = g["name"]
            if g["linked"] and known[k].get("status") in ("pending", "queued"):
                known[k]["status"] = "linked"
            continue
        status = "linked" if g["linked"] else ("ignored" if first or mode == "off" else "pending")
        known[k] = {"name": g["name"], "store": g["store"], "status": status, "seen": time.time()}
        if status == "pending":
            new.append(k)
    for k in [k for k in known if k not in cat]:   # disinstallati
        del known[k]
    save_known(known)
    if mode == "auto" and new:
        link(new)
        new = []
    # Steam in coda: si collegano appena Steam è chiuso
    q = [k for k, v in known.items() if v.get("status") == "queued"]
    if q and not steam_pids():
        link(q)
    return new
