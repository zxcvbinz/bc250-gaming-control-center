"""Comunicazione con il motore FPS (libbc250_vk.so / libbc250_gl.so) via memoria condivisa."""
import glob
import mmap
import os
import struct
import time

from .common import FRAME_DIRS

MAGIC = 0x30353242
CTL_FMT = "<16I"
CTL_SIZE = struct.calcsize(CTL_FMT)
FRAME_SIZE = 96 + 256 * 4
NO_OVERRIDE = 0xFFFFFFFF
RING = 256
# processi che presentano frame ma non sono giochi
IGNORE = ("steamwebhelper", "plasmashell", "kwin", "Xwayland", "bc250", "python3",
          "vulkaninfo", "gamescope", "hytale-launcher", "HytaleLauncher", "firefox", "chrome")


def write_control(fps_limit, limit_enabled, engine_enabled=True):
    data = struct.pack(CTL_FMT, MAGIC, 1, int(fps_limit or 0), int(bool(limit_enabled)),
                       int(bool(engine_enabled)), *([0] * 11))
    for d in FRAME_DIRS:
        try:
            os.makedirs(d, mode=0o700, exist_ok=True)
            path = os.path.join(d, "control.bin")
            # scrittura in posto: i giochi hanno il file mappato
            with open(path, "r+b" if os.path.exists(path) else "wb") as f:
                f.write(data)
        except OSError:
            pass


def _monotonic_ns():
    return time.clock_gettime_ns(time.CLOCK_MONOTONIC)


class FrameSource:
    """Legge i file fps-*.bin creati dai giochi."""

    def __init__(self):
        self.maps = {}  # path -> mmap
        self.prev = {}  # path -> (frames, t)

    def _map(self, path):
        m = self.maps.get(path)
        if m is None:
            try:
                with open(path, "r+b") as f:
                    m = mmap.mmap(f.fileno(), FRAME_SIZE)
            except (OSError, ValueError):
                return None
            self.maps[path] = m
        return m

    def _drop(self, path, delete=False):
        m = self.maps.pop(path, None)
        if m:
            m.close()
        self.prev.pop(path, None)
        if delete:
            try:
                os.remove(path)
            except OSError:
                pass

    def set_override(self, path, limit):
        m = self._map(path)
        if m:
            struct.pack_into("<I", m, 84, NO_OVERRIDE if limit is None else int(limit))

    def scan(self):
        """Lista dei processi che stanno presentando frame (attivi negli ultimi 2 s)."""
        now = _monotonic_ns()
        out = []
        seen = set()
        for d in FRAME_DIRS:
            for path in glob.glob(os.path.join(d, "fps-*.bin")):
                seen.add(path)
                m = self._map(path)
                if m is None:
                    continue
                magic, _ver, pid, api = struct.unpack_from("<4I", m, 0)
                if magic != MAGIC:
                    continue
                name = m[16:48].split(b"\0")[0].decode(errors="replace")
                appid = m[48:64].split(b"\0")[0].decode(errors="replace")
                # i giochi non-Steam sotto Proton hanno SteamAppId "default" o "0": non è un id
                if not appid.isdigit() or appid == "0":
                    appid = ""
                frames, last = struct.unpack_from("<QQ", m, 64)
                idx, override, active = struct.unpack_from("<3I", m, 80)
                age = (now - last) / 1e9 if last else 1e9
                # pulizia: processo terminato da più di 30 s
                if age > 30:
                    pid_alive = d != FRAME_DIRS[0] or os.path.exists(f"/proc/{pid}")
                    if not pid_alive or age > 300:
                        self._drop(path, delete=True)
                    continue
                if age > 2:
                    continue
                ring = struct.unpack_from(f"<{RING}I", m, 96)
                n = min(idx, RING)
                ft = [ring[(idx - 1 - i) % RING] / 1000.0 for i in range(n)]  # ms, più recente prima
                # FPS sull'ultimo secondo di frame
                acc, recent = 0.0, []
                for x in ft:
                    if acc > 1000 and recent:
                        break
                    recent.append(x)
                    acc += x
                fps = 1000.0 * len(recent) / acc if acc > 0 else 0.0
                win = sorted(ft[:120], reverse=True)
                low1 = 1000.0 / win[max(0, len(win) // 100)] if win and win[0] > 0 else None
                out.append({
                    "path": path, "pid": pid, "api": "Vulkan" if api == 1 else "OpenGL",
                    "name": name, "appid": appid, "frames": frames, "fps": fps,
                    "low1": low1, "frametimes": list(reversed(ft[:120])),
                    "frametime": ft[0] if ft else None,
                    "limit": active or 0,
                    "override": None if override == NO_OVERRIDE else override,
                    "flatpak": d != FRAME_DIRS[0],
                })
        for path in list(self.maps):
            if path not in seen:
                self._drop(path)
        return [g for g in out if not any(g["name"].startswith(i) for i in IGNORE)]
