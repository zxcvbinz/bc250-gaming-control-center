"""bc250d: servizio in background.

Ogni 0.5 s: legge sensori e giochi attivi, scrive lo stato per overlay/GUI/MCP.
Applica limite FPS e profili per gioco, registra lo storico, manda gli avvisi.
"""
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time

from . import common, health, i18n
from .i18n import T
from .engine import FrameSource, write_control
from .sensors import Sensors, governor_config, governor_range, governor_set

TICK = 0.5


class History:
    def __init__(self):
        os.makedirs(common.DATA_DIR, exist_ok=True)
        self.db = sqlite3.connect(common.DB_PATH)
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions(
                id INTEGER PRIMARY KEY, game TEXT, appid TEXT, api TEXT, profile TEXT,
                start REAL, end REAL, notes TEXT);
            CREATE TABLE IF NOT EXISTS samples(
                session INTEGER, t REAL, fps REAL, low1 REAL, ft_max REAL, fps_limit INTEGER,
                cpu_temp REAL, gpu_temp REAL, gpu_clk REAL, gpu_max REAL, gpu_busy REAL,
                cpu_load REAL, power REAL, fan INTEGER, ram REAL, throttling INTEGER);
            CREATE INDEX IF NOT EXISTS samples_session ON samples(session, t);
            -- id di sessioni unite ad altre: chi chiede il vecchio id trova quella nuova
            CREATE TABLE IF NOT EXISTS session_alias(old INTEGER PRIMARY KEY, new INTEGER);
        """)
        self.session = None
        self.current = None     # (nome, appid) del gioco della sessione aperta
        self.last_seen = 0.0
        self.pending = 0

    @staticmethod
    def ident(game):
        return (game["name"], game.get("appid") or "")

    def start(self, game, profile, gap):
        """Apre una sessione, o riprende l'ultima se è dello stesso gioco e finita da meno di `gap` s."""
        now = time.time()
        name, appid = self.ident(game)
        last = self.db.execute("SELECT id, game, IFNULL(appid,''), end FROM sessions "
                               "ORDER BY end DESC LIMIT 1").fetchone()
        if last and (last[1], last[2]) == (name, appid) and now - last[3] <= gap:
            self.session = last[0]
            if profile:
                self.db.execute("UPDATE sessions SET profile=? WHERE id=?", (profile, self.session))
        else:
            # id mai usati prima: quelli delle sessioni unite restano agli alias
            nid = self.db.execute("SELECT MAX(m) + 1 FROM (SELECT IFNULL(MAX(id), 0) AS m FROM sessions "
                                  "UNION ALL SELECT IFNULL(MAX(old), 0) FROM session_alias)").fetchone()[0]
            self.db.execute(
                "INSERT INTO sessions(id, game, appid, api, profile, start, end) VALUES(?,?,?,?,?,?,?)",
                (nid, name, game["appid"], game["api"], profile, now, now))
            self.session = nid
        self.db.commit()
        self.current = (name, appid)
        self.last_seen = now

    def stop(self):
        if self.session:
            # fine = ultimo frame visto, non il momento in cui ci si accorge che il gioco è sparito
            end = self.last_seen or time.time()
            self.db.execute("UPDATE sessions SET end=MAX(end, ?) WHERE id=?", (end, self.session))
            # sessioni più corte di 20 s non servono
            self.db.execute("DELETE FROM samples WHERE session IN (SELECT id FROM sessions "
                            "WHERE id=? AND end-start < 20)", (self.session,))
            self.db.execute("DELETE FROM sessions WHERE id=? AND end-start < 20", (self.session,))
            self.db.commit()
        self.session = None
        self.current = None

    def merge_split(self, gap):
        """Unisce le sessioni consecutive dello stesso gioco separate da meno di `gap` s
        (prima un alt+tab o un caricamento lungo chiudeva la sessione)."""
        has_marks = self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='marks'").fetchone()
        prev, merged = None, 0
        for r in self.db.execute("SELECT id, game, IFNULL(appid,''), profile, start, end FROM sessions "
                                 "ORDER BY start").fetchall():
            if prev and (r[1], r[2]) == (prev[1], prev[2]) and r[4] - prev[5] <= gap:
                self.db.execute("UPDATE samples SET session=? WHERE session=?", (prev[0], r[0]))
                if has_marks:
                    self.db.execute("UPDATE marks SET session=? WHERE session=?", (prev[0], r[0]))
                end, profile = max(prev[5], r[5]), r[3] or prev[3]
                self.db.execute("UPDATE sessions SET end=?, profile=? WHERE id=?", (end, profile, prev[0]))
                self.db.execute("DELETE FROM sessions WHERE id=?", (r[0],))
                self.db.execute("UPDATE session_alias SET new=? WHERE new=?", (prev[0], r[0]))
                self.db.execute("INSERT OR REPLACE INTO session_alias VALUES(?,?)", (r[0], prev[0]))
                prev = (prev[0], prev[1], prev[2], profile, prev[4], end)
                merged += 1
            else:
                prev = r
        self.db.commit()
        return merged

    def add(self, g, s, gpu_max, throttling):
        if not self.session:
            return
        self.db.execute("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
            self.session, time.time(), g["fps"], g["low1"],
            max(g["frametimes"][-60:] or [0]), g["limit"],
            s.get("cpu_temp"), s.get("gpu_temp"), s.get("gpu_clk"), gpu_max,
            s.get("gpu_busy"), s.get("cpu_load"), s.get("power"), s.get("fan"),
            (s.get("ram") or [None])[0], int(throttling)))
        self.pending += 1
        if self.pending >= 10:
            self.db.execute("UPDATE sessions SET end=? WHERE id=?", (time.time(), self.session))
            self.db.commit()
            self.pending = 0

    def prune(self, days):
        lim = time.time() - days * 86400
        self.db.execute("DELETE FROM samples WHERE session IN (SELECT id FROM sessions WHERE start<?)", (lim,))
        self.db.execute("DELETE FROM sessions WHERE start<?", (lim,))
        self.db.commit()


def match_profile(cfg, game):
    if not game:
        return None
    name = game["name"].lower()
    for p in cfg.get("profiles", []):
        m = str(p.get("match", "")).strip()
        if not m:
            continue
        if m.startswith("appid:"):
            if game["appid"] and m[6:] == game["appid"]:
                return p
        elif m.lower() in name:
            return p
    return None


def notify(title, body, urgent=False):
    try:
        subprocess.Popen(["notify-send", "-a", "BC-250", "-i", "temperature-high" if urgent else "dialog-information",
                          "-u", "critical" if urgent else "normal", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


class Daemon:
    def __init__(self):
        self.sensors = Sensors()
        self.frames = FrameSource()
        self.hist = History()
        self.cfg = common.load_config()
        self.cfg_mtime = self._mtime()
        self.game_key = None
        self.game = None
        self.profile = None
        self.alert_last = {}
        self.alerts = []
        self.gov = governor_range() or (None, None)
        self.gov_cfg = governor_config()
        self.n = 0
        self.vrr_on = None          # stato VRR che abbiamo impostato noi
        self.no_game_since = time.monotonic()
        self.vrr_lock = threading.Lock()
        self.guard_cut = 0          # FPS tolti dalla protezione calore
        self.guard_t = 0.0
        self.apply_control()
        self.hist.prune(self.cfg["history"]["keep_days"])
        n = self.hist.merge_split(self.gap())
        if n:
            print(f"storico: unite {n} sessioni spezzate", file=sys.stderr, flush=True)

    @staticmethod
    def _mtime():
        try:
            return os.stat(common.CONF_PATH).st_mtime
        except OSError:
            return 0

    def apply_control(self):
        e = self.cfg["engine"]
        write_control(e["fps_limit"], e["limit_enabled"], e["enabled"])

    def reload_if_changed(self):
        m = self._mtime()
        if m != self.cfg_mtime:
            self.cfg_mtime = m
            self.cfg = common.load_config()
            i18n.set_lang(self.cfg.get("language", "it"))
            self.apply_control()
            if self.game:  # riapplica profilo e limite al gioco in corso
                self.apply_profile(self.game, self.profile)

    # ------------------------------------------------------------ profiles
    def apply_profile(self, game, prev_profile):
        self.profile = match_profile(self.cfg, game) if game else None
        gd = self.cfg["gpu_default"]
        if self.profile and self.profile.get("gpu_max"):
            governor_set(self.profile.get("gpu_min") or gd["min"], self.profile["gpu_max"])
        elif prev_profile and prev_profile.get("gpu_max"):
            governor_set(gd["min"], gd["max"])
        if game:
            self.apply_limit(game)

    def base_limit(self):
        """Limite voluto dal profilo (o globale), prima della protezione calore. 0 = nessuno."""
        if not self.cfg["engine"]["limit_enabled"]:
            return 0
        if self.profile and "fps_limit" in self.profile and self.profile["fps_limit"] is not None:
            return int(self.profile["fps_limit"])
        return int(self.cfg["engine"]["fps_limit"] or 0)

    def apply_limit(self, game):
        base = self.base_limit()
        if self.guard_cut and self.cfg["engine"]["limit_enabled"]:
            # senza limite la protezione parte da 120
            eff = max(40, (base or 120) - self.guard_cut)
            self.frames.set_override(game["path"], eff)
        elif not self.cfg["engine"]["limit_enabled"]:
            self.frames.set_override(game["path"], 0)
        elif self.profile and self.profile.get("fps_limit") is not None:
            self.frames.set_override(game["path"], base)
        else:
            self.frames.set_override(game["path"], None)

    # ------------------------------------------------------------ protezione calore
    def heat_guard(self, game, s):
        """Se la CPU supera la soglia del profilo, abbassa il limite di 10 FPS ogni 20 s;
        quando torna 8°C sotto la soglia per 30 s, risale di 10."""
        thr = (self.profile or {}).get("heat_guard")
        t = s.get("cpu_temp")
        if not game or not thr or t is None:
            if self.guard_cut:
                self.guard_cut = 0
                if game:
                    self.apply_limit(game)
            return
        now = time.monotonic()
        base = self.base_limit() or 120
        if t >= thr and now - self.guard_t >= 20 and base - self.guard_cut > 40:
            self.guard_cut += 10
            self.guard_t = now
            self.apply_limit(game)
            common.overlay_send("toast:" + T("Protezione calore: CPU {t:.0f}°C → limite {lim} FPS",
                                              t=t, lim=max(40, base - self.guard_cut)))
        elif self.guard_cut and t <= thr - 8 and now - self.guard_t >= 30:
            self.guard_cut -= 10
            self.guard_t = now
            self.apply_limit(game)
            if not self.guard_cut:
                common.overlay_send("toast:" + T("Protezione calore: limite ripristinato"))

    def gap(self):
        return float(self.cfg["history"].get("merge_gap_s", 300))

    def on_game_change(self, game):
        self.guard_cut = 0
        self.apply_profile(game, self.profile)
        self.game = game
        if not game:
            return  # la sessione resta aperta: il gioco può tornare (alt+tab, caricamenti)
        if self.hist.session and self.hist.current != self.hist.ident(game):
            self.hist.stop()  # è partito un altro gioco
        if not self.hist.session and self.cfg["history"]["enabled"]:
            self.hist.start(game, self.profile["name"] if self.profile else None, self.gap())

    def track_session(self, game):
        if game:
            self.hist.last_seen = time.time()
        elif self.hist.session and time.time() - self.hist.last_seen > self.gap():
            self.hist.stop()

    # ------------------------------------------------------------ VRR solo nei giochi
    def _set_vrr(self, on):
        def work():
            with self.vrr_lock:
                for o in health.vrr_outputs():
                    want = "automatic" if on else "never"
                    if o["vrr"] != want or not on:
                        # spegnendo riapplico sempre la modalità: la scheda può restare col VRR acceso
                        health.set_vrr(o["name"], want)
        self.vrr_on = on
        threading.Thread(target=work, daemon=True).start()

    def manage_vrr(self, game):
        d = self.cfg.get("display", {})
        if not d.get("vrr_games_only"):
            self.vrr_on = None
            return
        now = time.monotonic()
        want = bool(game and self.profile and self.profile.get("vrr"))
        if want:
            self.no_game_since = None
            if self.vrr_on is not True:
                self._set_vrr(True)
        else:
            if self.no_game_since is None:
                self.no_game_since = now
            # piccolo ritardo: il gioco può sparire un attimo (caricamenti, launcher)
            if self.vrr_on is None:
                # appena avviato: se è già spento non tocco lo schermo (niente schermo nero)
                if all(o["vrr"] == "never" for o in health.vrr_outputs()):
                    self.vrr_on = False
                    return
            if self.vrr_on is not False and now - self.no_game_since >= d.get("vrr_off_delay_s", 8):
                self._set_vrr(False)

    # ------------------------------------------------------------ alerts
    def check_alerts(self, s):
        a = self.cfg["alerts"]
        self.alerts = []
        if not a["enabled"]:
            return
        checks = []
        if s.get("cpu_temp") and s["cpu_temp"] >= a["cpu_temp"]:
            checks.append(("cpu", T("CPU a {t:.0f}°C", t=s["cpu_temp"]), T("Soglia {v}°C superata.", v=a["cpu_temp"])))
        if s.get("gpu_temp") and s["gpu_temp"] >= a["gpu_temp"]:
            checks.append(("gpu", T("GPU a {t:.0f}°C", t=s["gpu_temp"]), T("Soglia {v}°C superata.", v=a["gpu_temp"])))
        if s.get("fan") is not None and s["fan"] < a["fan_min_rpm"]:
            checks.append(("fan", T("Ventola a {v} rpm", v=s["fan"]), T("La ventola sembra ferma o lenta!")))
        if s.get("ram") and s["ram"][1] and s["ram"][0] / s["ram"][1] > 0.95:
            checks.append(("ram", T("RAM quasi piena"), T("{u:.1f}/{t:.1f} GiB usati.", u=s["ram"][0], t=s["ram"][1])))
        now = time.time()
        for key, title, body in checks:
            self.alerts.append({"key": key, "title": title})
            if now - self.alert_last.get(key, 0) > a["cooldown_s"]:
                self.alert_last[key] = now
                notify(title, body, urgent=key in ("cpu", "gpu", "fan"))

    # ------------------------------------------------------------ loop
    def tick(self):
        self.n += 1
        self.reload_if_changed()
        s = self.sensors.read(with_gpu_busy=(self.n % 2 == 0))
        if s.get("gpu_busy") is None:
            s["gpu_busy"] = getattr(self, "last_busy", None)
        self.last_busy = s["gpu_busy"]
        if self.n % 10 == 0:
            self.gov = governor_range() or self.gov
            self.sensors.topo = self.sensors.topology()
        if self.n % 60 == 0:
            self.gov_cfg = governor_config()

        games = self.frames.scan()
        game = max(games, key=lambda g: (g["fps"] > 1, g["frames"]), default=None)
        key = (game["path"],) if game else None
        if key != self.game_key:
            self.on_game_change(game)
            self.game_key = key
        self.track_session(game)
        self.heat_guard(game, s)
        self.manage_vrr(game)
        throttle = self.gov_cfg.get("throttle")
        throttling = bool(throttle and s.get("gpu_temp") and s["gpu_temp"] >= throttle)
        if game and self.n % 2 == 0:
            self.hist.add(game, s, self.gov[1], throttling)
        if self.n % 2 == 0:
            self.check_alerts(s)

        e = self.cfg["engine"]
        if game:
            game = dict(game, profile=self.profile["name"] if self.profile else None,
                        profile_data=self.profile, guard_cut=self.guard_cut,
                        base_limit=self.base_limit(), vrr=bool(self.vrr_on))
        state = {
            "ts": time.time(), "sensors": s, "game": game,
            "games": [{k: g[k] for k in ("name", "api", "fps", "pid")} for g in games],
            "engine": {"enabled": e["enabled"], "fps_limit": e["fps_limit"],
                       "limit_enabled": e["limit_enabled"]},
            "governor": {"min": self.gov[0], "max": self.gov[1], **self.gov_cfg},
            "throttling": throttling, "alerts": self.alerts,
            "session": self.hist.session,
        }
        common.write_json_atomic(common.STATE_PATH, state)

    def run(self):
        stop = []
        signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
        signal.signal(signal.SIGINT, lambda *_: stop.append(1))
        while not stop:
            t0 = time.monotonic()
            try:
                self.tick()
            except Exception as ex:  # il servizio non deve morire per un errore di lettura
                print("tick error:", repr(ex), file=sys.stderr, flush=True)
            time.sleep(max(0.05, TICK - (time.monotonic() - t0)))
        self.hist.stop()
        gd = self.cfg["gpu_default"]
        if self.profile and self.profile.get("gpu_max"):
            governor_set(gd["min"], gd["max"])


def main():
    Daemon().run()


if __name__ == "__main__":
    main()
