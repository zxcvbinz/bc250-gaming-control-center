"""bc250-mcp: server MCP (stdio) per Claude Code.

Permette a Claude di leggere i dati live e lo storico delle partite, segnare i
momenti dei test e cambiare limite FPS / clock GPU / profili per trovare
l'impostazione migliore insieme all'utente.
"""
import json
import sqlite3
import sys
import time

from . import common, health
from .engine import write_control
from .sensors import governor_range, governor_set

PROTOCOL = "2025-06-18"


def db():
    con = sqlite3.connect(common.DB_PATH, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("CREATE TABLE IF NOT EXISTS marks(session INTEGER, t REAL, note TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS session_alias(old INTEGER PRIMARY KEY, new INTEGER)")
    return con


def r1(v, n=1):
    return None if v is None else round(v, n)


def summarize(rows):
    if not rows:
        return {}
    def col(k):
        return [r[k] for r in rows if r[k] is not None]
    fps = col("fps")
    out = {
        "samples": len(rows),
        "seconds": r1(rows[-1]["t"] - rows[0]["t"], 0),
        "fps_avg": r1(sum(fps) / len(fps)) if fps else None,
        "fps_min": r1(min(fps)) if fps else None,
        "fps_1pct_low_avg": r1(sum(col("low1")) / len(col("low1"))) if col("low1") else None,
        "frametime_spike_max_ms": r1(max(col("ft_max"))) if col("ft_max") else None,
        "throttling_pct": r1(100 * sum(col("throttling")) / len(rows)),
    }
    for k in ("cpu_temp", "gpu_temp", "gpu_clk", "power", "gpu_busy", "cpu_load", "ram"):
        v = col(k)
        if v:
            out[k] = {"avg": r1(sum(v) / len(v)), "max": r1(max(v))}
    lim = col("fps_limit")
    out["fps_limit"] = max(set(lim), key=lim.count) if lim else None
    return out


def downsample(rows, points=60):
    if not rows:
        return []
    step = max(1, len(rows) // points)
    out = []
    for i in range(0, len(rows), step):
        chunk = rows[i:i + step]
        def avg(k):
            v = [r[k] for r in chunk if r[k] is not None]
            return r1(sum(v) / len(v)) if v else None
        out.append({"t": r1(chunk[0]["t"] - rows[0]["t"], 0), "fps": avg("fps"), "low1": avg("low1"),
                    "cpu_temp": avg("cpu_temp"), "gpu_temp": avg("gpu_temp"), "gpu_clk": avg("gpu_clk"),
                    "power": avg("power"), "gpu_busy": avg("gpu_busy"), "cpu_load": avg("cpu_load")})
    return out


# ---------------------------------------------------------------- tools
def t_get_status(_):
    st = common.read_state()
    s = st.get("sensors") or {}
    g = st.get("game")
    return {
        "age_s": r1(time.time() - st.get("ts", 0)),
        "game": {k: (r1(g[k]) if isinstance(g[k], float) else g[k]) for k in
                 ("name", "api", "appid", "fps", "low1", "frametime", "limit", "profile")} if g else None,
        "engine": st.get("engine"),
        "sensors": {k: r1(s.get(k)) if isinstance(s.get(k), float) else s.get(k) for k in
                    ("cpu_temp", "gpu_temp", "gpu_clk", "gpu_busy", "cpu_load", "power", "fan",
                     "cpu_mhz", "nvme_temp", "cores", "threads")},
        "ram_gib": [r1(x) for x in s.get("ram") or []],
        "vram_mib": [r1(x, 0) for x in s.get("vram") or []],
        "governor": st.get("governor"), "throttling": st.get("throttling"),
        "alerts": st.get("alerts"), "session_id": st.get("session"),
    }


def t_get_recent(a):
    secs = float(a.get("seconds", 60))
    con = db()
    rows = con.execute("SELECT * FROM samples WHERE t > ? ORDER BY t", (time.time() - secs,)).fetchall()
    return {"summary": summarize(rows), "timeline": downsample(rows, int(a.get("points", 30)))}


def t_list_sessions(a):
    con = db()
    out = []
    for s in con.execute("SELECT * FROM sessions ORDER BY start DESC LIMIT ?", (int(a.get("limit", 15)),)):
        rows = con.execute("SELECT * FROM samples WHERE session=? ORDER BY t", (s["id"],)).fetchall()
        sm = summarize(rows)
        merged = [r[0] for r in con.execute("SELECT old FROM session_alias WHERE new=?", (s["id"],))]
        out.append({"id": s["id"], "game": s["game"], "profile": s["profile"],
                    **({"merged_ids": merged} if merged else {}),
                    "start": time.strftime("%Y-%m-%d %H:%M", time.localtime(s["start"])),
                    "minutes": r1((s["end"] - s["start"]) / 60),
                    "fps_avg": sm.get("fps_avg"), "fps_1pct_low_avg": sm.get("fps_1pct_low_avg"),
                    "cpu_temp_max": (sm.get("cpu_temp") or {}).get("max"),
                    "gpu_temp_max": (sm.get("gpu_temp") or {}).get("max"),
                    "throttling_pct": sm.get("throttling_pct")})
    return out


def resolve(con, sid):
    """Id di sessione, seguendo gli alias delle sessioni unite."""
    try:
        r = con.execute("SELECT new FROM session_alias WHERE old=?", (sid,)).fetchone()
    except sqlite3.Error:
        r = None
    return r[0] if r else sid


def parts(rows, gap=20):
    """Tratti di gioco continui: si separano dove il gioco ha smesso di disegnare (alt+tab, caricamenti)."""
    out, cur = [], []
    for r in rows:
        if cur and r["t"] - cur[-1]["t"] > gap:
            out.append(cur)
            cur = []
        cur.append(r)
    if cur:
        out.append(cur)
    return out


def t_get_session(a):
    con = db()
    asked = int(a["id"])
    sid = resolve(con, asked)
    s = con.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
    if not s:
        raise ValueError("sessione non trovata")
    rows = con.execute("SELECT * FROM samples WHERE session=? ORDER BY t", (sid,)).fetchall()
    marks = [{"t": r1(m["t"] - s["start"], 0), "note": m["note"]}
             for m in con.execute("SELECT * FROM marks WHERE session=? ORDER BY t", (sid,))]
    # riassunto per ogni tratto tra due segni: utile per confrontare impostazioni
    segments = []
    bounds = [s["start"]] + [m["t"] + s["start"] for m in marks] + [s["end"] + 1]
    labels = ["inizio"] + [m["note"] for m in marks]
    for i in range(len(bounds) - 1):
        seg = [r for r in rows if bounds[i] <= r["t"] < bounds[i + 1]]
        if seg:
            segments.append({"from_mark": labels[i], "summary": summarize(seg)})
    merged = [r[0] for r in con.execute("SELECT old FROM session_alias WHERE new=? ORDER BY old", (sid,))]
    pp = [{"start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p[0]["t"])),
           "minutes": r1((p[-1]["t"] - p[0]["t"]) / 60), "summary": summarize(p)} for p in parts(rows)]
    out = {"id": sid, "game": s["game"], "profile": s["profile"], "api": s["api"],
           "start": time.strftime("%Y-%m-%d %H:%M", time.localtime(s["start"])),
           "minutes": r1((s["end"] - s["start"]) / 60)}
    if asked != sid:
        out["note"] = f"la sessione {asked} è stata unita alla {sid} (stesso gioco, ripreso entro pochi minuti)"
    if merged:
        out["merged_ids"] = merged
    out.update({"summary": summarize(rows), "parts": pp, "marks": marks, "segments": segments,
            "timeline": downsample(rows, int(a.get("points", 60)))})
    return out


def t_mark(a):
    st = common.read_state()
    sid = st.get("session")
    if not sid:
        raise ValueError("nessuna partita in corso")
    con = db()
    con.execute("INSERT INTO marks VALUES(?,?,?)", (sid, time.time(), a["note"]))
    con.commit()
    return {"ok": True, "session": sid, "note": a["note"]}


def t_set_fps_limit(a):
    lim = a.get("limit")
    lim = int(lim) if lim not in (None, 0, "off") else 0
    prof = a.get("profile")
    if prof:
        def fn(c):
            for p in c["profiles"]:
                if p["name"].lower() == prof.lower():
                    p["fps_limit"] = lim or None
                    return
            raise ValueError("profilo non trovato")
        cfg = common.update_config(fn)
    else:
        cfg = common.update_config(lambda c: c["engine"].update(fps_limit=lim, limit_enabled=bool(lim)))
    e = cfg["engine"]
    write_control(e["fps_limit"], e["limit_enabled"], e["enabled"])
    common.overlay_send(f"toast:Limite FPS: {lim or 'nessuno'}" + (f" ({prof})" if prof else ""))
    return {"ok": True, "engine": e}


def t_set_gpu_clock(a):
    mx, mn = a.get("max"), a.get("min")
    ok = governor_set(mn, mx)
    return {"ok": ok, "current": governor_range("Current"), "allowed": governor_range("Allowed"),
            "note": "Temporaneo: un profilo o il cambio gioco lo reimposta."}


def t_profiles(_):
    return common.load_config()["profiles"]


def t_save_profile(a):
    prof = {k: a[k] for k in ("name", "match", "fps_limit", "gpu_max", "gpu_min", "vrr", "heat_guard",
                              "hud", "hud_position", "hud_style", "notes") if k in a}

    def fn(c):
        for i, p in enumerate(c["profiles"]):
            if p["name"].lower() == prof["name"].lower():
                c["profiles"][i] = {**p, **prof}
                return
        c["profiles"].append(prof)
    common.update_config(fn)
    return {"ok": True, "profiles": common.load_config()["profiles"]}


def t_health(_):
    return health.checks()


def t_config(_):
    c = common.load_config()
    return {k: c[k] for k in ("engine", "alerts", "gpu_default", "overlay")}


TOOLS = {
    "get_status": (t_get_status, "Stato live: gioco, FPS, 1% low, temperature, clock GPU, watt, limite FPS, throttling.", {}),
    "get_recent": (t_get_recent, "Riassunto + timeline degli ultimi N secondi di gioco (dallo storico).",
                   {"seconds": {"type": "number", "description": "finestra in secondi (default 60)"},
                    "points": {"type": "integer", "description": "punti della timeline (default 30)"}}),
    "list_sessions": (t_list_sessions, "Elenco delle ultime partite registrate con medie e massimi.",
                      {"limit": {"type": "integer"}}),
    "get_session": (t_get_session, "Dettaglio di una partita: riassunto, parti continue (separate da alt+tab/pause), segni, confronto per tratti tra i segni, timeline. Accetta anche id di sessioni poi unite.",
                    {"id": {"type": "integer"}, "points": {"type": "integer"}}, ["id"]),
    "mark": (t_mark, "Segna un momento nella partita in corso (es. 'ombre basse', 'limite 75'), per confrontare i tratti.",
             {"note": {"type": "string"}}, ["note"]),
    "set_fps_limit": (t_set_fps_limit, "Cambia il limite FPS in diretta (globale o di un profilo). limit=0 per toglierlo.",
                      {"limit": {"type": "integer"}, "profile": {"type": "string"}}, ["limit"]),
    "set_gpu_clock": (t_set_gpu_clock, "Cambia in diretta il range clock GPU del governor (MHz, 500-2000).",
                      {"max": {"type": "integer"}, "min": {"type": "integer"}}),
    "list_profiles": (t_profiles, "Profili per gioco (match nome processo o appid:<id>, fps_limit, gpu_max).", {}),
    "save_profile": (t_save_profile, "Crea o aggiorna un profilo per gioco.",
                     {"name": {"type": "string"}, "match": {"type": "string"},
                      "fps_limit": {"type": ["integer", "null"]}, "gpu_max": {"type": ["integer", "null"]},
                      "gpu_min": {"type": ["integer", "null"]},
                      "vrr": {"type": "boolean", "description": "VRR automatico in questo gioco (schermo nero un attimo all'avvio/chiusura)"},
                      "heat_guard": {"type": ["integer", "null"], "description": "°C CPU oltre cui abbassare il limite FPS di 10 ogni 20 s"},
                      "hud": {"type": "boolean"}, "hud_position": {"type": ["string", "null"]},
                      "hud_style": {"type": ["string", "null"], "description": "bubble, compact, full o null (globale)"},
                      "notes": {"type": "string"}}, ["name"]),
    "health_check": (t_health, "Controllo salute della BC-250 (servizi, governor, core, ventola, swap, VRR...).", {}),
    "get_config": (t_config, "Configurazione attuale (motore, avvisi, clock GPU di default, overlay).", {}),
}


def handle(msg):
    method, mid = msg.get("method"), msg.get("id")
    if method == "initialize":
        return {"protocolVersion": msg.get("params", {}).get("protocolVersion", PROTOCOL),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "bc250", "version": "1.0"}}
    if method == "ping":
        return {}
    if method == "tools/list":
        tools = []
        for name, spec in TOOLS.items():
            fn, desc, props = spec[0], spec[1], spec[2]
            req = spec[3] if len(spec) > 3 else []
            tools.append({"name": name, "description": desc,
                          "inputSchema": {"type": "object", "properties": props, "required": req}})
        return {"tools": tools}
    if method == "tools/call":
        p = msg.get("params", {})
        spec = TOOLS.get(p.get("name"))
        if not spec:
            return {"content": [{"type": "text", "text": "tool sconosciuto"}], "isError": True}
        try:
            res = spec[0](p.get("arguments") or {})
            return {"content": [{"type": "text", "text": json.dumps(res, ensure_ascii=False, default=str)}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"errore: {e}"}], "isError": True}
    if mid is None:
        return None  # notifica
    raise KeyError(method)


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid = msg.get("id")
        try:
            res = handle(msg)
            if mid is None:
                continue
            out = {"jsonrpc": "2.0", "id": mid, "result": res}
        except KeyError as e:
            out = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"metodo sconosciuto {e}"}}
        except Exception as e:
            out = {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}
        sys.stdout.write(json.dumps(out) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
