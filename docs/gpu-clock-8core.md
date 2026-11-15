# Real GPU clock on 8-core BC-250s

← [Documentation index](README.md)

## The problem

The BC-250 CPU can be unlocked from 6 to 8 cores
([GabriWar/bc250-core-cu-unlock](https://github.com/GabriWar/bc250-core-cu-unlock)). After the unlock,
the SMU (the chip's power-management firmware) fills its metrics table with a different layout. The table
keeps the same size (116 bytes), but wider per-core arrays now sit where `GfxclkFrequency` used to be
(offset `0x44`). The GPU clock field is gone.

The `amdgpu` driver still reads offset `0x44` for:

| Interface | Shows after the unlock | Read by |
|---|---|---|
| `gpu_metrics` → `current_gfxclk` | 3–100 MHz (a CPU residency counter) | MangoHud, Steam overlay, LACT, … |
| `pp_dpm_sclk` | `1: 10Mhz *` | LACT, CoreCtrl, scripts |
| hwmon `freq1_input` | garbage | sensors, many monitors |

Temperature, voltages and total power stay at their usual offsets and remain correct. Source and details:
[higorprado/bc250-8core-telemetry-report](https://github.com/higorprado/bc250-8core-telemetry-report).

## What already exists

- [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor) with `fix-freq = true`
  asks the SMU directly for the GPU clock and bind-mounts a corrected copy over hwmon `freq1_input`.
  It does **not** fix `gpu_metrics` or `pp_dpm_sclk`.
- A kernel patch (`0001-bc250-8core-telemetry.patch`, in GabriWar's `kernel/patches`) fixes everything at
  the source, but needs a custom kernel. That is awkward on image-based systems like Bazzite.

## What `bc250-metricsfix` does

A small root service (standard-library Python, about 150 lines, `bc250/metricsfix.py`):

1. waits for the governor to patch `freq1_input`, which gives the real clock;
2. opens the current `gpu_metrics` (the governor's copy with the GPU-load fix, which it keeps updating in
   place) and `freq1_input`;
3. replaces the governor's mount on `gpu_metrics` with its own file. The governor's copy is an
   already-deleted file and cannot be mounted over, so it is lazily unmounted; the governor keeps writing
   to its open file, which this service reads. It also bind-mounts its own `pp_dpm_sclk`;
4. every 250 ms copies the governor's metrics, writes the real clock into `current_gfxclk` and
   `average_gfxclk` (offsets 76 and 64 of `gpu_metrics` v2.2), and rewrites `pp_dpm_sclk` with the real
   current level;
5. on stop, removes its mounts.

The unit is `PartOf=` and `WantedBy=` the governor service, so it stops, starts and restarts with it.

Verified on a BC-250 with 8 cores: idle 1000 MHz and load 1750 MHz in `gpu_metrics` and `pp_dpm_sclk`.
That matches `vkpeak` FP32 throughput: 5337 GFLOPS ÷ (24 CU × 128 FLOP/clk) ≈ 1737 MHz.

## Requirements

- cyan-skillfish-governor with `fix-freq = true` (and ideally `fix-metrics = true`) in
  `/etc/cyan-skillfish-governor-smu/config.toml`;
- `sudo` when running the installer. The service file is `/etc/systemd/system/bc250-metricsfix.service`
  and the script is copied (root-owned) to `/usr/local/lib/bc250/metricsfix.py`, so the root service never
  runs code from your home folder.

## Check it

```sh
systemctl status bc250-metricsfix
findmnt | grep -E 'gpu_metrics|pp_dpm_sclk'      # should show /bc250-metricsfix/...
cat /sys/class/drm/card*/device/pp_dpm_sclk       # middle line = real clock, marked *
```

On a 6-core board the service is harmless: it writes the same value the driver would report.
