"""Lettura sensori BC-250 (solo lettura, nessun privilegio richiesto)."""
import glob
import os
import re
import time


def rd(path, default=None):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def num(path, div=1.0):
    v = rd(path)
    try:
        return int(v) / div
    except (TypeError, ValueError):
        return None


def hwmon(prefix):
    for h in glob.glob("/sys/class/hwmon/hwmon*"):
        if (rd(h + "/name") or "").startswith(prefix):
            return h
    return None


class Sensors:
    def __init__(self):
        self.gpu_hw = hwmon("amdgpu")
        self.cpu_hw = hwmon("k10temp")
        self.nct = hwmon("nct668")
        self.nvme = hwmon("nvme")
        self.card = next((c for c in glob.glob("/sys/class/drm/card[0-9]")
                          if os.path.exists(c + "/device/mem_info_vram_total")), None)
        self.prev_stat = {}
        self.prev_gfx = None
        self.topo = self.topology()

    @staticmethod
    def topology():
        topo = {}
        for c in glob.glob("/sys/devices/system/cpu/cpu[0-9]*"):
            n = int(c.rsplit("cpu", 1)[1])
            core = rd(c + "/topology/core_id")
            if core is not None and rd(c + "/online", "1") == "1":
                topo.setdefault(int(core), []).append(n)
        return {k: sorted(v) for k, v in sorted(topo.items())}

    def cpu_usage(self):
        usage = {}
        with open("/proc/stat") as f:
            for line in f:
                m = re.match(r"cpu(\d*)\s+(.*)", line)
                if not m:
                    continue
                vals = list(map(int, m.group(2).split()))
                idle, total = vals[3] + vals[4], sum(vals[:8])
                key = int(m.group(1)) if m.group(1) else "all"
                p = self.prev_stat.get(key)
                self.prev_stat[key] = (idle, total)
                usage[key] = (100.0 * (1 - (idle - p[0]) / (total - p[1]))
                              if p and total > p[1] else 0.0)
        return usage

    @staticmethod
    def cpu_freqs():
        freqs, i = {}, 0
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("processor"):
                    i = int(line.split(":")[1])
                elif line.startswith("cpu MHz"):
                    freqs[i] = float(line.split(":")[1])
        return freqs

    def gpu_busy(self):
        """Carico GPU dai contatori fdinfo (drm-engine-gfx), come nvtop."""
        clients = {}
        for fd in glob.glob("/proc/[0-9]*/fdinfo/*"):
            try:
                with open(fd) as f:
                    txt = f.read()
            except OSError:
                continue
            if "drm-driver:\tamdgpu" not in txt:
                continue
            cid = re.search(r"drm-client-id:\s*(\d+)", txt)
            gfx = re.search(r"drm-engine-gfx:\s*(\d+)", txt)
            if cid and gfx:
                clients[cid.group(1)] = int(gfx.group(1))
        now = time.monotonic()
        prev, self.prev_gfx = self.prev_gfx, (now, clients)
        if not prev:
            return None
        dt = (now - prev[0]) * 1e9
        delta = sum(max(0, v - prev[1].get(k, v)) for k, v in clients.items())
        return max(0.0, min(100.0, 100.0 * delta / dt)) if dt > 0 else None

    def read(self, with_gpu_busy=True):
        d = {"t": time.time()}
        u = self.cpu_usage()
        d["cpu_load"] = u.pop("all", None)
        d["cpu_threads"] = u
        d["cpu_freq"] = self.cpu_freqs()
        d["cpu_mhz"] = max(d["cpu_freq"].values()) if d["cpu_freq"] else None
        d["cpu_temp"] = num(f"{self.cpu_hw}/temp1_input", 1000) if self.cpu_hw else None
        if self.gpu_hw:
            d["gpu_temp"] = num(f"{self.gpu_hw}/temp1_input", 1000)
            d["gpu_clk"] = num(f"{self.gpu_hw}/freq1_input", 1e6)
            d["power"] = (num(f"{self.gpu_hw}/power1_average", 1e6)
                          or num(f"{self.gpu_hw}/power1_input", 1e6))
            d["vddgfx"] = num(f"{self.gpu_hw}/in0_input")
            d["vddnb"] = num(f"{self.gpu_hw}/in1_input")
        if self.card:
            dev = self.card + "/device"
            d["vram"] = [num(dev + "/mem_info_vram_used", 2**20), num(dev + "/mem_info_vram_total", 2**20)]
            d["gtt"] = [num(dev + "/mem_info_gtt_used", 2**30), num(dev + "/mem_info_gtt_total", 2**30)]
        if with_gpu_busy:
            d["gpu_busy"] = self.gpu_busy()
        d["fans"], d["board_temps"] = [], {}
        if self.nct:
            for i in range(1, 9):
                rpm = num(f"{self.nct}/fan{i}_input")
                if rpm:
                    d["fans"].append([rd(f"{self.nct}/fan{i}_label") or f"fan{i}", int(rpm)])
            for i in range(1, 8):
                t = num(f"{self.nct}/temp{i}_input", 1000)
                if t:
                    d["board_temps"][rd(f"{self.nct}/temp{i}_label") or f"temp{i}"] = t
        d["fan"] = d["fans"][0][1] if d["fans"] else None
        if self.nvme:
            d["nvme_temp"] = num(f"{self.nvme}/temp1_input", 1000)
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                mem[k] = int(v.split()[0]) / 2**20
        d["ram"] = [mem["MemTotal"] - mem["MemAvailable"], mem["MemTotal"]]
        d["swap"] = [mem["SwapTotal"] - mem["SwapFree"], mem["SwapTotal"]]
        d["cores"] = len(self.topo)
        d["threads"] = sum(len(v) for v in self.topo.values())
        return d


# ---------------------------------------------------------------- governor (D-Bus)
GOV_BUS = "com.cyanskillfish.Governor"
GOV_PATH = "/com/cyanskillfish/Governor/Range/"
GOV_IFACE = "com.cyanskillfish.Governor.Range"


def _bus():
    from gi.repository import Gio
    return Gio.bus_get_sync(Gio.BusType.SYSTEM, None)


def governor_range(which="Current"):
    """(min, max) MHz del governor, oppure None se non raggiungibile."""
    try:
        from gi.repository import GLib
        bus = _bus()
        out = []
        for prop in ("Min", "Max"):
            v = bus.call_sync(GOV_BUS, GOV_PATH + which, "org.freedesktop.DBus.Properties", "Get",
                              GLib.Variant("(ss)", (GOV_IFACE, prop)), None, 0, 2000, None)
            out.append(v.unpack()[0])
        return tuple(out)
    except Exception:
        return None


def governor_set(mn=None, mx=None):
    """Imposta il range clock GPU in diretta. Ritorna True se riuscito."""
    try:
        from gi.repository import GLib
        bus = _bus()
        allowed = governor_range("Allowed") or (500, 2000)
        cur = governor_range("Current") or (allowed[0], allowed[1])
        if mx is not None and mn is None and mx < cur[0]:
            mn = mx
        order = [("Min", mn), ("Max", mx)]
        if mn is not None and mn > cur[1]:
            order.reverse()  # alzo prima il massimo, poi il minimo
        for prop, val in order:
            if val is None:
                continue
            val = int(max(allowed[0], min(allowed[1], val)))
            bus.call_sync(GOV_BUS, GOV_PATH + "Current", "org.freedesktop.DBus.Properties", "Set",
                          GLib.Variant("(ssv)", (GOV_IFACE, prop, GLib.Variant("u", val))),
                          None, 0, 2000, None)
        return True
    except Exception:
        return False


def governor_config():
    cfg = rd("/etc/cyan-skillfish-governor-smu/config.toml") or ""
    th = re.search(r"^throttling\s*=\s*(\d+)", cfg, re.M)
    rec = re.search(r"^throttling_recovery\s*=\s*(\d+)", cfg, re.M)
    return {"throttle": int(th.group(1)) if th else None,
            "recovery": int(rec.group(1)) if rec else None}
