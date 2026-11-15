"""Impostazioni grafiche dei giochi: trova il file, lo legge, confronta, scrive.

Motori supportati:
  unreal   GameUserSettings.ini nel prefix (AppData/Local/<Progetto>/Saved/Config/Windows[NoEditor])
  unity    PlayerPrefs nel registro di Wine (user.reg) o ~/.config/unity3d/<Company>/<Product>/prefs
  nms      No Man's Sky: Binaries/SETTINGS/TKGRAPHICSSETTINGS.MXML

I giochi leggono le impostazioni all'avvio e spesso le riscrivono all'uscita: per questo le
modifiche si scrivono solo a gioco chiuso (il servizio le applica appena il gioco si chiude).
"""
import glob
import json
import os
import re
import shutil
import struct
import time

from . import common

BACKUP_DIR = os.path.join(common.DATA_DIR, "backups")

# chiavi interessanti per analisi e tuning (le altre si leggono ma non si mostrano per prime)
INTERESTING = re.compile(
    r"quality|resolution|framerate|fps|vsync|fullscreen|window|upscal|fsr|dlss|xess|sharp|shadow|texture|"
    r"antialias|^aa|ray|reflect|ssao|ssr|ambient|bloom|blur|motion|dof|depth|foliage|effect|post|view|"
    r"draw|lod|detail|preset|graphic|scale|dynamic|anisotrop|tessel|volumetric|fog|cloud|gi|lumen|nanite",
    re.I)
# chiavi che cambiano da sole: non contano come modifica dell'utente
NOISE = re.compile(r"lastuserconfirmed|lastconfirmed|version|cache|time|count|seen|^bfirst|benchmark|hash", re.I)


def interesting(key):
    k = key.rsplit("/", 1)[-1]
    return bool(INTERESTING.search(k)) and not NOISE.search(k)


# ---------------------------------------------------------------- processo -> prefix, exe
def proc_info(pid):
    env, args = {}, []
    try:
        raw = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
        env = dict(x.decode(errors="replace").split("=", 1) for x in raw if b"=" in x)
        args = [a.decode(errors="replace") for a in open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0") if a]
    except OSError:
        pass
    prefix = env.get("WINEPREFIX")
    if not prefix and env.get("STEAM_COMPAT_DATA_PATH"):
        prefix = os.path.join(env["STEAM_COMPAT_DATA_PATH"], "pfx")
    exe = None
    for a in args:
        if a.lower().endswith(".exe") or "/" in a:
            exe = win_to_unix(a, prefix)
            if exe and exe.lower().endswith(".exe"):
                break
    return prefix, exe


def win_to_unix(path, prefix):
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", path)
    if not m:
        return path
    drive, rest = m.group(1).lower(), m.group(2).replace("\\", "/")
    if drive == "z":
        return "/" + rest
    if prefix:
        return os.path.join(prefix, f"drive_{drive}", rest)
    return None


def user_dir(prefix):
    for u in ("steamuser", os.environ.get("USER", "")):
        d = os.path.join(prefix, "drive_c", "users", u)
        if u and os.path.isdir(d):
            return d
    return None


# ---------------------------------------------------------------- sorgenti
class Source:
    engine = "?"

    def __init__(self, path):
        self.path = path

    def mtime(self):
        try:
            return os.stat(self.path).st_mtime
        except OSError:
            return 0

    def describe(self):
        return {"engine": self.engine, "path": self.path}

    def backup(self, game):
        d = os.path.join(BACKUP_DIR, re.sub(r"[^\w.-]+", "_", game))
        os.makedirs(d, exist_ok=True)
        dst = os.path.join(d, time.strftime("%Y%m%d-%H%M%S-") + os.path.basename(self.path))
        shutil.copy2(self.path, dst)
        return dst


class UnrealIni(Source):
    engine = "unreal"

    def read(self):
        out, sec = {}, ""
        try:
            for line in open(self.path, encoding="utf-8-sig", errors="replace"):
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    sec = line[1:-1]
                elif "=" in line and not line.startswith(";"):
                    k, v = line.split("=", 1)
                    out[f"{sec}/{k.strip()}"] = v.strip()
        except OSError:
            pass
        return out

    def write(self, changes):
        """changes: {"Sezione/Chiave": valore}. Aggiunge le chiavi mancanti nella loro sezione."""
        lines = open(self.path, encoding="utf-8-sig", errors="replace").read().splitlines()
        todo = dict(changes)
        sec, out = "", []
        for i, line in enumerate(lines):
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                # prima di cambiare sezione, aggiungi le chiavi mancanti di quella appena finita
                # (prima delle righe vuote che la separano dalla successiva)
                add = [f"{k.rsplit('/', 1)[1]}={v}" for k, v in list(todo.items()) if k.rsplit("/", 1)[0] == sec]
                n = 0
                while n < len(out) and not out[len(out) - 1 - n].strip():
                    n += 1
                out[len(out) - n:len(out) - n] = add
                todo = {k: v for k, v in todo.items() if k.rsplit("/", 1)[0] != sec}
                sec = s[1:-1]
                out.append(line)
                continue
            if "=" in s and not s.startswith(";"):
                key = f"{sec}/{s.split('=', 1)[0].strip()}"
                if key in todo:
                    out.append(f"{s.split('=', 1)[0].strip()}={todo.pop(key)}")
                    continue
            out.append(line)
        out += [f"{k.rsplit('/', 1)[1]}={v}" for k, v in todo.items() if k.rsplit("/", 1)[0] == sec]
        todo = {k: v for k, v in todo.items() if k.rsplit("/", 1)[0] != sec}
        for k, v in todo.items():   # sezioni nuove
            s, key = k.rsplit("/", 1)
            out += ["", f"[{s}]", f"{key}={v}"]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("\n".join(out) + "\n")


class UnityReg(Source):
    """PlayerPrefs di Unity nel registro di Wine. Interi = dword, float = hex(4) (double), stringhe = hex."""
    engine = "unity"

    def __init__(self, path, key):
        super().__init__(path)
        self.key = key   # es. Software\\\\Dogubomb\\\\BLUE PRINCE (come scritto in user.reg)

    def describe(self):
        return {"engine": self.engine, "path": self.path, "registry_key": self.key.replace("\\\\", "\\")}

    def _section(self, text):
        hdr = f"[{self.key}]"
        i = text.lower().find(hdr.lower())
        if i < 0:
            return None, None
        j = text.find("\n[", i + len(hdr))
        return i, (j if j > 0 else len(text))

    @staticmethod
    def _decode(raw):
        if raw.startswith("dword:"):
            return int(raw[6:], 16)
        m = re.match(r"hex(?:\((\w+)\))?:(.*)", raw, re.S)
        if m:
            data = bytes(int(x, 16) for x in re.sub(r"[\\\s]", "", m.group(2)).split(",") if x)
            if m.group(1) == "4" and len(data) == 8:
                return round(struct.unpack("<d", data)[0], 4)
            if m.group(1) == "4" and len(data) == 4:
                return struct.unpack("<f", data)[0]
            return data.rstrip(b"\0").decode(errors="replace")
        return raw.strip('"')

    def read(self):
        try:
            text = open(self.path, encoding="utf-8", errors="replace").read()
        except OSError:
            return {}
        a, b = self._section(text)
        if a is None:
            return {}
        out = {}
        body = re.sub(r"\\\n\s*", "", text[a:b])
        for m in re.finditer(r'^"([^"]+)"=(.+)$', body, re.M):
            name = re.sub(r"_h\d+$", "", m.group(1))   # Unity aggiunge un hash al nome
            out[name] = self._decode(m.group(2).strip())
        return out

    def write(self, changes):
        text = open(self.path, encoding="utf-8", errors="replace").read()
        a, b = self._section(text)
        if a is None:
            raise ValueError("chiave del gioco non trovata nel registro")
        body = re.sub(r"\\\n\s*", "", text[a:b])
        for name, val in changes.items():
            m = re.search(rf'^"({re.escape(name)}(?:_h\d+)?)"=(.+)$', body, re.M)
            if not m:
                raise ValueError(f"{name}: non esiste, Unity la crea da sé")
            old = m.group(2)
            if old.startswith("dword:"):
                new = f"dword:{int(val) & 0xFFFFFFFF:08x}"
            elif old.startswith("hex(4):"):
                new = "hex(4):" + ",".join(f"{x:02x}" for x in struct.pack("<d", float(val)))
            else:
                raise ValueError(f"{name}: tipo non modificabile (solo numeri)")
            body = body[:m.start(2)] + new + body[m.end(2):]
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text[:a] + body + text[b:])


class UnityPrefs(Source):
    """Unity nativo Linux: ~/.config/unity3d/<Company>/<Product>/prefs (XML)."""
    engine = "unity"
    PAT = re.compile(r'<pref name="([^"]+)" type="(\w+)">([^<]*)</pref>')

    def read(self):
        try:
            return {m.group(1): m.group(3) for m in self.PAT.finditer(open(self.path, errors="replace").read())}
        except OSError:
            return {}

    def write(self, changes):
        text = open(self.path, errors="replace").read()
        for name, val in changes.items():
            text, n = re.subn(rf'(<pref name="{re.escape(name)}" type="\w+">)[^<]*(</pref>)',
                              lambda m: f"{m.group(1)}{val}{m.group(2)}", text)
            if not n:
                raise ValueError(f"{name}: non esiste")
        open(self.path, "w").write(text)


class Mxml(Source):
    """No Man's Sky e altri giochi Hello Games: <Property name="X" value="Y"> annidati.
    Le chiavi sono il percorso: TextureQuality.GraphicDetail."""
    engine = "nms"
    TOK = re.compile(r'<Property name="([^"]+)"(?: value="([^"]*)")?\s*(/?)>|</Property>')

    def _scan(self, text):
        """[(chiave, start, end del valore)]"""
        out, stack, seen = [], [], {}
        for m in self.TOK.finditer(text):
            if m.group(0) == "</Property>":
                if stack:
                    stack.pop()
                continue
            name = m.group(1)
            path = ".".join(stack + [name])
            seen[path] = seen.get(path, 0) + 1
            key = path if seen[path] == 1 else f"{path}#{seen[path]}"
            if m.group(2) is not None:
                out.append((key, m.start(2), m.end(2)))
            if not m.group(3):          # proprietà aperta: i figli stanno dentro
                stack.append(name)
        return out

    def read(self):
        try:
            text = open(self.path, errors="replace").read()
        except OSError:
            return {}
        return {k: text[a:b] for k, a, b in self._scan(text)}

    def write(self, changes):
        text = open(self.path, errors="replace").read()
        spans = {k: (a, b) for k, a, b in self._scan(text)}
        missing = [k for k in changes if k not in spans]
        if missing:
            raise ValueError(f"non esistono: {', '.join(missing)}")
        for k in sorted(changes, key=lambda k: spans[k][0], reverse=True):
            a, b = spans[k]
            text = text[:a] + str(changes[k]) + text[b:]
        open(self.path, "w").write(text)


# ---------------------------------------------------------------- ricerca
def _unreal(prefix, name, exe):
    ud = user_dir(prefix) if prefix else None
    if not ud:
        return None
    local = os.path.join(ud, "AppData", "Local")
    names = []
    stem = re.sub(r"\.exe$", "", name, flags=re.I)
    names.append(re.split(r"-Win64|-WinGDK|-Shipping", stem)[0])
    if exe:   # <Gioco>/<Progetto>/Binaries/Win64/<exe>
        parts = exe.split("/")
        if "Binaries" in parts:
            names.append(parts[parts.index("Binaries") - 1])
    for n in names:
        for sub in ("Windows", "WindowsNoEditor", "WinGDK"):
            p = os.path.join(local, n, "Saved", "Config", sub, "GameUserSettings.ini")
            if os.path.exists(p):
                return UnrealIni(p)
    return None


def _unity(prefix, exe):
    if not exe:
        return None
    base = os.path.splitext(exe)[0]
    info = base + "_Data/app.info"
    if not os.path.exists(info):
        return None
    lines = open(info, errors="replace").read().splitlines()
    if len(lines) < 2:
        return None
    company, product = lines[0].strip(), lines[1].strip()
    if exe.lower().endswith(".exe") and prefix:
        reg = os.path.join(prefix, "user.reg")
        key = f"Software\\\\{company}\\\\{product}"
        if os.path.exists(reg):
            return UnityReg(reg, key)
    p = os.path.expanduser(f"~/.config/unity3d/{company}/{product}/prefs")
    return UnityPrefs(p) if os.path.exists(p) else None


def _nms(exe):
    if not exe or "Binaries" not in exe:
        return None
    p = os.path.join(exe.split("/Binaries/")[0], "Binaries", "SETTINGS", "TKGRAPHICSSETTINGS.MXML")
    return Mxml(p) if os.path.exists(p) else None


def detect(game):
    """Sorgente delle impostazioni grafiche del gioco in esecuzione, o None."""
    prefix, exe = proc_info(game["pid"])
    if game.get("flatpak"):
        return None
    return _nms(exe) or _unreal(prefix, game["name"], exe) or _unity(prefix, exe)


def from_saved(d):
    """Ricrea una sorgente salvata (per i giochi chiusi)."""
    if not d or not os.path.exists(d.get("path", "")):
        return None
    if d["engine"] == "unreal":
        return UnrealIni(d["path"])
    if d["engine"] == "nms":
        return Mxml(d["path"])
    if d["engine"] == "unity" and d.get("registry_key"):
        return UnityReg(d["path"], d["registry_key"].replace("\\", "\\\\"))
    if d["engine"] == "unity":
        return UnityPrefs(d["path"])
    return None


def diff(old, new):
    """{chiave: [prima, dopo]} solo per le chiavi cambiate che non sono rumore."""
    out = {}
    for k in set(old) | set(new):
        if old.get(k) != new.get(k) and not NOISE.search(k.rsplit("/", 1)[-1]):
            out[k] = [old.get(k), new.get(k)]
    return dict(sorted(out.items()))


def summary(data, limit=60):
    """Le impostazioni interessanti, per analisi e per l'MCP."""
    items = {k: v for k, v in data.items() if interesting(k)}
    return dict(list(sorted(items.items()))[:limit])


def short(k):
    return k.rsplit("/", 1)[-1]


def describe_changes(ch, n=4):
    parts = [f"{short(k)} {a}→{b}" for k, (a, b) in list(ch.items())[:n]]
    if len(ch) > n:
        parts.append(f"+{len(ch) - n}")
    return ", ".join(parts)


def dumps(d):
    return json.dumps(d, ensure_ascii=False, default=str)
