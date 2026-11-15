# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""bc250-metricsfix: real GPU clock in gpu_metrics and pp_dpm_sclk on 8-core BC-250s.

With the 8-core unlock the SMU metrics table changes layout and the GPU clock field
(GfxclkFrequency) is gone: gpu_metrics current_gfxclk and pp_dpm_sclk show 3-100 MHz.
cyan-skillfish-governor (fix-freq) asks the SMU for the real clock, but only patches hwmon
freq1_input. MangoHud, the Steam overlay and LACT read gpu_metrics / pp_dpm_sclk instead.

This service (runs as root, see bc250-metricsfix.service):
  1. opens the current gpu_metrics and freq1_input (the governor's patched copies,
     which it updates in place),
  2. replaces the governor's gpu_metrics mount with its own file and bind-mounts
     pp_dpm_sclk too (the governor keeps writing to its open, now unmounted file),
  3. every 250 ms copies the governor's gpu_metrics, writes the real clock into
     current_gfxclk/average_gfxclk, and rewrites pp_dpm_sclk with it.

Only standard library, so it can run with `python3 -I` from a root-owned copy.
"""
import glob
import os
import signal
import struct
import subprocess
import sys
import time

INTERVAL = 0.25
OFF_AVG_GFXCLK = 64   # gpu_metrics v2.x: average_gfxclk_frequency (u16, MHz)
OFF_CUR_GFXCLK = 76   # gpu_metrics v2.x: current_gfxclk (u16, MHz)
RUN_DIR = "/run/bc250-metricsfix"


def log(*a):
    print("bc250-metricsfix:", *a, file=sys.stderr, flush=True)


def gpu_device():
    for name in glob.glob("/sys/class/hwmon/hwmon*/name"):
        try:
            if open(name).read().strip() == "amdgpu":
                hw = os.path.dirname(name)
                return os.path.realpath(os.path.join(hw, "device")), os.path.join(hw, "freq1_input")
        except OSError:
            pass
    return None, None


def mounted(path):
    r = subprocess.run(["findmnt", "-rn", "-M", path], capture_output=True, text=True)
    return r.returncode == 0 and bool(r.stdout.strip())


class Overlay:
    """A file in /run bind-mounted over a sysfs attribute, rewritten in place."""

    def __init__(self, target, content):
        self.target = target
        os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
        self.path = os.path.join(RUN_DIR, os.path.basename(target))
        with open(self.path, "wb") as f:
            f.write(content)
        os.chmod(self.path, 0o444)
        self.fd = os.open(self.path, os.O_RDWR)
        # the governor's overlay is a deleted file and cannot be mounted over: replace it
        # (its open file keeps being updated by the governor, we read it through src fds)
        while mounted(target):
            subprocess.run(["umount", "-l", target], check=True)
        subprocess.run(["mount", "--bind", self.path, target], check=True)

    def write(self, content):
        os.pwrite(self.fd, content, 0)
        os.ftruncate(self.fd, len(content))

    def close(self):
        subprocess.run(["umount", self.target], stderr=subprocess.DEVNULL)
        os.close(self.fd)


def main():
    dev, freq_path = gpu_device()
    if not dev:
        log("amdgpu not found")
        return 1
    metrics_path = os.path.join(dev, "gpu_metrics")
    sclk_path = os.path.join(dev, "pp_dpm_sclk")

    # The real clock comes only from the governor's fix-freq overlay on freq1_input.
    for _ in range(60):
        if mounted(freq_path):
            break
        time.sleep(1)
    else:
        log("freq1_input is not patched by cyan-skillfish-governor: enable fix-freq = true in its "
            "config. Nothing to do.")
        return 0
    # give the governor a moment to also mount its gpu_metrics (fix-metrics)
    for _ in range(10):
        if mounted(metrics_path):
            break
        time.sleep(1)
    # a previous run that died without cleaning up: its files are in RUN_DIR
    for p in (metrics_path, sclk_path):
        r = subprocess.run(["findmnt", "-rn", "-o", "SOURCE", "-M", p], capture_output=True, text=True)
        if "bc250-metricsfix" in r.stdout:
            log("removing stale mount on", p)
            subprocess.run(["umount", p], stderr=subprocess.DEVNULL)

    # opened before mounting ours: they keep pointing at the governor's files (or the real ones)
    src_metrics = os.open(metrics_path, os.O_RDONLY)
    src_freq = os.open(freq_path, os.O_RDONLY)
    levels = open(sclk_path).read().splitlines()
    lo = levels[0].split(":")[1].strip().rstrip("*").strip() if levels else "350Mhz"
    hi = levels[-1].split(":")[1].strip().rstrip("*").strip() if levels else "2230Mhz"

    def read_mhz():
        try:
            return int(os.pread(src_freq, 64, 0).split()[0]) // 1_000_000
        except (OSError, ValueError, IndexError):
            return None

    def build():
        raw = bytearray(os.pread(src_metrics, 256, 0))
        mhz = read_mhz()
        if mhz and len(raw) >= OFF_CUR_GFXCLK + 2:
            struct.pack_into("<H", raw, OFF_CUR_GFXCLK, mhz)
            struct.pack_into("<H", raw, OFF_AVG_GFXCLK, mhz)
        sclk = f"0: {lo} \n1: {mhz or 0}Mhz *\n2: {hi} \n".encode()
        return bytes(raw), sclk

    m, s = build()
    overlays = [Overlay(metrics_path, m), Overlay(sclk_path, s)]
    log(f"active: gpu_metrics and pp_dpm_sclk now report the real GPU clock ({read_mhz()} MHz)")

    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    try:
        while not stop:
            time.sleep(INTERVAL)
            try:
                m, s = build()
                overlays[0].write(m)
                overlays[1].write(s)
            except OSError as e:
                log("update failed:", e)
    finally:
        for o in reversed(overlays):
            o.close()
        log("stopped, mounts removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
