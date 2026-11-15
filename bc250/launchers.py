# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
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
    for aid, (_p, e) in shortcuts().items():
        out[f"shortcut:{aid}"] = {"name": e.get("AppName", aid), "store": "Steam (non Steam)",
                                  "linked": TOKEN in e.get("LaunchOptions", "")}
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
            out[f"lutris:{cid}"] = {"name": names.get(cid) or pretty, "store": "Lutris", "linked": TOKEN in pc.split(),
                                    "exe": g.get("exe", "")}
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


_lk = __import__("threading").RLock()
_depth = [0, None]


def locked(fn):
    """Lettura-modifica-scrittura di known_games.json in esclusiva (servizio e app insieme)."""
    import fcntl
    import functools

    @functools.wraps(fn)
    def wrap(*a, **kw):
        with _lk:
            if _depth[0] == 0:
                os.makedirs(common.DATA_DIR, exist_ok=True)
                _depth[1] = open(KNOWN_PATH + ".lock", "w")
                fcntl.flock(_depth[1], fcntl.LOCK_EX)
            _depth[0] += 1
            try:
                return fn(*a, **kw)
            finally:
                _depth[0] -= 1
                if _depth[0] == 0:
                    fcntl.flock(_depth[1], fcntl.LOCK_UN)
                    _depth[1].close()
    return wrap


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
    by = {"steam": set(), "lutris": set(), "heroic": set(), "shortcut": set(), "seen": set()}
    for k in keys:
        store, _, gid = k.partition(":")
        if store in by:
            by[store].add(gid)
    return by


@locked
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
    for gid in by["seen"]:
        seen_link(f"seen:{gid}", known.get(f"seen:{gid}", {"name": gid}), enable)
        done.append(f"seen:{gid}")
    steam_keys = [f"steam:{g}" for g in by["steam"]] + [f"shortcut:{g}" for g in by["shortcut"]]
    if steam_keys:
        if steam_pids() and not restart_steam:
            queued += steam_keys
        else:
            def work():
                if by["steam"]:
                    steam_edit(enable, drop_mh, only=by["steam"])
                if by["shortcut"]:
                    shortcut_edit(enable, by["shortcut"])
            with_steam_closed(work, restart=True)
            done += steam_keys
    for k in done:
        known.setdefault(k, {})["status"] = "linked" if enable else "ignored"
    for k in queued:
        known.setdefault(k, {})["status"] = "queued" if enable else "ignored"
    save_known(known)
    return done, queued


@locked
def ignore(keys):
    known = load_known()
    for k in keys:
        known.setdefault(k, {})["status"] = "ignored"
    save_known(known)


@locked
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
            if g.get("exe"):
                known[k]["exe"] = g["exe"]
            if g["linked"] and known[k].get("status") in ("pending", "queued"):
                known[k]["status"] = "linked"
            continue
        status = "linked" if g["linked"] else ("ignored" if first or mode == "off" else "pending")
        known[k] = {"name": g["name"], "store": g["store"], "status": status, "seen": time.time(),
                    **({"exe": g["exe"]} if g.get("exe") else {})}
        if status == "pending":
            new.append(k)
    for k in [k for k in known if k not in cat and not k.startswith("seen:")]:   # disinstallati
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


# ---------------------------------------------------------------- giochi non Steam dentro Steam (shortcuts.vdf binario)
def bvdf_loads(data):
    def read_str(i):
        j = data.index(b"\0", i)
        return data[i:j].decode("utf-8", "replace"), j + 1

    def read_map(i):
        out = {}
        while True:
            t = data[i]
            i += 1
            if t == 0x08:
                return out, i
            key, i = read_str(i)
            if t == 0x00:
                out[key], i = read_map(i)
            elif t == 0x01:
                out[key], i = read_str(i)
            elif t == 0x02:
                out[key] = ("int", int.from_bytes(data[i:i + 4], "little"))
                i += 4
            else:
                raise ValueError(f"tipo {t} non gestito")
    d, _ = read_map(0)
    return d


def bvdf_dumps(d):
    out = bytearray()
    for k, v in d.items():
        kb = k.encode() + b"\0"
        if isinstance(v, dict):
            out += b"\x00" + kb + bvdf_dumps(v)
        elif isinstance(v, tuple):
            out += b"\x02" + kb + int(v[1]).to_bytes(4, "little")
        else:
            out += b"\x01" + kb + str(v).encode() + b"\0"
    return bytes(out + b"\x08")


def shortcut_files():
    root = steam_root()
    return [p for p in glob.glob(os.path.join(root, "userdata", "*", "config", "shortcuts.vdf"))
            if "/userdata/0/" not in p] if root else []


def shortcuts():
    """{appid: (file, entry)} dei giochi non Steam aggiunti a Steam."""
    out = {}
    for p in shortcut_files():
        try:
            d = bvdf_loads(open(p, "rb").read())
        except (OSError, ValueError, IndexError):
            continue
        for e in (d.get("shortcuts") or {}).values():
            if isinstance(e, dict) and isinstance(e.get("appid"), tuple):
                out[str(e["appid"][1])] = (p, e)
    return out


def shortcut_edit(enable, only=None):
    changed = {}
    for p in shortcut_files():
        raw = open(p, "rb").read()
        d = bvdf_loads(raw)
        mine = False
        for e in (d.get("shortcuts") or {}).values():
            if not isinstance(e, dict) or not isinstance(e.get("appid"), tuple):
                continue
            aid = str(e["appid"][1])
            if only is not None and aid not in only:
                continue
            old = e.get("LaunchOptions", "")
            new = add_token(old) if enable else remove_token(old)
            if new != old:
                e["LaunchOptions"] = new
                changed[aid] = (e.get("AppName", aid), old, new)
                mine = True
        if mine:
            backup(p)
            open(p, "wb").write(b"\x00" + b"shortcuts\0" + bvdf_dumps(d["shortcuts"]) + b"\x08")
    return changed


# ---------------------------------------------------------------- giochi visti partire (lanciati in altro modo)
DESKTOP_DIR = os.path.expanduser("~/.local/share/applications")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "gioco"


def proc_launch(pid):
    """Come è stato lanciato un processo: comando, cartella, container, id Steam."""
    info = {}
    try:
        info["cmd"] = [a.decode(errors="replace") for a in open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0") if a]
        info["cwd"] = os.readlink(f"/proc/{pid}/cwd")
        env = dict(x.decode(errors="replace").split("=", 1)
                   for x in open(f"/proc/{pid}/environ", "rb").read().split(b"\0") if b"=" in x)
    except OSError:
        return info
    if env.get("CONTAINER_ID") or env.get("container"):
        info["container"] = env.get("CONTAINER_ID") or env.get("HOSTNAME") or ""
    gid = env.get("SteamGameId") or ""
    if gid.isdigit() and int(gid) > 0xFFFFFFFF:
        info["shortcut"] = str(int(gid) >> 32)
    if env.get("SteamAppId", "").isdigit() and env["SteamAppId"] != "0":
        info["appid"] = env["SteamAppId"]
    info["via_run"] = env.get("BC250_RUN") == "1"
    return info


@locked
def record_seen(game):
    """Il servizio ha visto partire un gioco: se non è già in elenco (Steam, Lutris, Heroic,
    scorciatoia Steam), lo aggiunge ai «rilevati», in attesa che tu lo colleghi. Niente notifiche."""
    info = proc_launch(game["pid"])
    if not info.get("cmd"):
        return None
    known = load_known()
    if info.get("appid") and f"steam:{info['appid']}" in known:
        return None
    if info.get("shortcut"):
        key = f"shortcut:{info['shortcut']}"
        if key in known:
            return None
    exe = os.path.basename(info["cmd"][0]).lower()
    for k, v in known.items():   # Lutris: stesso eseguibile
        if k.startswith("lutris:") and v.get("exe") and os.path.basename(v["exe"]).lower() == exe:
            return None
    name = re.sub(r"\.exe$", "", game["name"], flags=re.I)
    key = key if info.get("shortcut") else f"seen:{slug(name)}"
    if key in known:
        known[key]["last"] = time.time()
        known[key]["launch"] = info
        save_known(known)
        return None
    known[key] = {"name": name, "store": "Steam (non Steam)" if info.get("shortcut") else
                  ("distrobox" if info.get("container") else T_("Rilevato")),
                  "status": "linked" if info.get("via_run") else "pending", "seen": time.time(),
                  "last": time.time(), "process": game["name"], "launch": info}
    save_known(known)
    return key


def T_(s):
    from .i18n import T
    return T(s)


def _desktop_cmd(info):
    import shlex
    cmd = info.get("cmd") or []
    pre = ["distrobox", "enter", info["container"], "--"] if info.get("container") else []
    return " ".join(shlex.quote(c) for c in [os.path.expanduser("~/.local/bin/bc250-run")] + pre + cmd)


def seen_link(key, g, enable):
    """Gioco lanciato in altro modo: crea (o toglie) un lanciatore «<Gioco> (BC-250)» nel menu,
    che rifà lo stesso comando passando da bc250-run, e un profilo per il gioco."""
    path = os.path.join(DESKTOP_DIR, f"bc250-game-{slug(g['name'])}.desktop")
    script = os.path.join(common.DATA_DIR, "launch", f"{slug(g['name'])}.sh")
    if not enable:
        for f in (path, script):
            if os.path.exists(f):
                os.remove(f)
        return
    info = g.get("launch") or {}
    if not info.get("cmd"):
        raise ValueError("comando del gioco sconosciuto: avvialo una volta")
    import shlex
    os.makedirs(os.path.dirname(script), exist_ok=True)
    with open(script, "w") as f:   # script: quoting della shell, valido per qualsiasi comando
        f.write(f"#!/bin/sh\n# {g['name']}: creato dal Control Center BC-250\n"
                f"cd {shlex.quote(info.get('cwd') or os.path.expanduser('~'))} || exit 1\nexec {_desktop_cmd(info)}\n")
    os.chmod(script, 0o755)
    os.makedirs(DESKTOP_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(f"[Desktop Entry]\nType=Application\nName={g['name']} (BC-250)\n"
                f"Comment=Avvia {g['name']} con il Control Center BC-250 (profilo, upscaling FSR)\n"
                f"Exec={script}\nIcon=applications-games\n"
                "Categories=Game;\nTerminal=false\n")
    os.chmod(path, 0o755)
    proc = g.get("process") or g["name"]

    def fn(c):
        if not any(p.get("match") and p["match"].lower() in proc.lower() for p in c["profiles"]):
            c["profiles"].append({"name": g["name"], "match": proc})
    common.update_config(fn)
    return path
