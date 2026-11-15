# Architecture

← [Documentation index](README.md)

```
 game process                         user session                              root
┌──────────────────────┐      ┌──────────────────────────────┐      ┌───────────────────────────┐
│ libbc250_vk.so       │      │ bc250d (daemon, 2 Hz)         │◄────►│ cyan-skillfish-governor   │
│  (implicit layer)    │ shm  │  sensors · games · profiles   │ D-Bus│  GPU clock / voltage       │
│ libbc250_gl.so       │◄────►│  limits · VRR · history · alerts│     └───────────────────────────┘
│  (LD_PRELOAD)        │      │  → /dev/shm/bc250-UID/state.json│     ┌───────────────────────────┐
└──────────────────────┘      └───────────┬──────────────────┘      │ bc250-metricsfix          │
                                          │ state.json                │  real clock → gpu_metrics │
              ┌───────────────────────────┼─────────────────────┐    └───────────────────────────┘
              ▼                           ▼                     ▼
      bc250-overlay               bc250-control (app)      bc250-mcp (AI)
   layer-shell HUD/panel     PyQt6, edits config.json    stdio JSON-RPC
```

Everything talks through files: shared memory for frames, a JSON state file, the JSON config and SQLite.
Any piece can crash or restart without taking the others down.

## FPS engine (`layer/`)

Two small C libraries share `layer/common.h`:

- **`libbc250_vk.so`**: an *implicit* Vulkan layer (`VK_LAYER_BC250_frame`) that wraps
  `vkQueuePresentKHR`. Because it is implicit, every Vulkan app loads it, including DXVK/VKD3D under
  Proton. The env var `DISABLE_BC250_LAYER=1` turns it off.
- **`libbc250_gl.so`**: an `LD_PRELOAD` shim that wraps `glXSwapBuffers` and `eglSwapBuffers` (and
  resolves them through `eglGetProcAddress`), for native OpenGL games and Flatpak apps.

On the first present, each process creates `fps-<pid>-<rand>.bin` in `/dev/shm/bc250-<uid>` (or
`$XDG_RUNTIME_DIR/bc250` inside Flatpak):

```c
struct bc_frame {             /* written by the game */
    uint32_t magic, version;  /* "B250", 1 */
    uint32_t pid, api;        /* 1 = Vulkan, 2 = OpenGL */
    char name[32];            /* argv[0] basename (Game.exe under Wine) */
    char appid[16];           /* $SteamAppId */
    uint64_t frames, last_ns;
    uint32_t ring_idx;
    uint32_t limit_override;  /* written by bc250d: per-game limit, 0xFFFFFFFF = global */
    uint32_t limit_active;    /* limit applied on the last frame */
    uint32_t pad;
    uint32_t ring[256];       /* frame times, µs */
};
```

It also maps `control.bin` (`struct bc_control`: global `fps_limit`, `limit_enabled`, `engine_enabled`),
written by the daemon. Limiting happens inside the present call: sleep until the next frame slot, then
busy-wait the last 0.3 ms for precise pacing. Changing the limit is a 4-byte write, so it applies on the
next frame.

## Daemon (`bc250d`)

A loop every 0.5 s:

1. reload `config.json` if it changed;
2. read sensors (hwmon, `/proc`, the governor over D-Bus);
3. scan the frame files: FPS over the last second, 1% low over 120 frames. Processes idle for more than
   2 s are "not presenting"; files of dead processes are removed;
4. pick the active game (the one presenting, with most frames), match its profile, apply the FPS limit
   (`limit_override`), GPU range and VRR;
5. heat guard, alerts, history (1 sample/s);
6. write `state.json` atomically.

## Overlay (`bc250-overlay`)

PyQt6 windows turned into layer-shell surfaces through LayerShellQt (called via `ctypes`): HUD, details
panel and toast. A Unix datagram socket (`overlay.sock`) receives commands from `bc250ctl` and the
daemon (`toggle-panel`, `toggle-hud`, `toast:<text>`). The HUD drawing lives in `bc250/hudpaint.py`,
shared with the app's preview, so the preview is exactly what you get in game.

## App (`bc250-control`)

PyQt6, Fusion style with its own dark palette. Pages: Dashboard, Games & FPS, Profiles, Overlay, Display,
Health, History, Alerts. It refreshes the visible page once per second from `state.json`, and writes only
`config.json`.

## Source map

| File | Role |
|---|---|
| `bc250/common.py` | paths, defaults, config load/save, profile field definitions, palette |
| `bc250/daemon.py` | `bc250d`: main loop, history, profiles, heat guard, VRR, alerts |
| `bc250/engine.py` | reading frame files, writing the control block |
| `bc250/sensors.py` | hwmon/proc sensors, governor D-Bus |
| `bc250/health.py` | health checks, VRR/display via `kscreen-doctor` |
| `bc250/hudpaint.py` | HUD styles, attention logic, demo data |
| `bc250/overlay.py` | layer-shell windows, details panel, command socket |
| `bc250/gui.py` | the desktop app |
| `bc250/mcp_server.py` | MCP server |
| `bc250/ctl.py` | `bc250ctl` |
| `bc250/metricsfix.py` | root service for the 8-core clock fix |
| `bc250/install.py` | installer |
| `layer/` | C engine |
