# Installation

← [Documentation index](README.md)

## Requirements

| What | Why | On Bazzite / Fedora |
|---|---|---|
| AMD BC-250 with a working `amdgpu` driver | the app reads the GPU through sysfs/hwmon | kernel 6.x with the BC-250 patches (stock on recent Bazzite) |
| KDE Plasma 6 on **Wayland** | the overlay uses LayerShellQt to stay above fullscreen games | default on Bazzite desktop |
| Python 3.11+ with **PyQt6** and **PyGObject** | GUI, overlay, D-Bus | `python3-pyqt6`, `python3-gobject` (preinstalled on Bazzite) |
| `gcc` and `make` | to build the FPS engine (two tiny C libraries) | in a toolbox/distrobox, or layered |
| [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor) (`smu` branch) with `[dbus] enabled = true` | GPU clock range control, live clock reading | optional but strongly recommended |
| `sudo` | only for the 8-core GPU clock fix (`bc250-metricsfix`) | optional |

Everything else (the daemon, overlay, GUI and MCP server) runs as your user. No root needed.

## Install or update

```sh
git clone https://github.com/zxcvbinz/bc250-gaming-control-center.git
cd bc250-gaming-control-center
python3 -m bc250.install
```

The installer is idempotent: run it again after `git pull` to update. Each step prints `✓` or `✗`:

| Step | What it does |
|---|---|
| Build the FPS engine | `make -C layer install` → `~/.local/lib/bc250/libbc250_vk.so` and `libbc250_gl.so` |
| Enable the engine in Vulkan/Proton games | writes the implicit layer manifest `~/.local/share/vulkan/implicit_layer.d/bc250_frame.json` |
| Commands | launchers in `~/.local/bin`: `bc250d`, `bc250-overlay`, `bc250-control`, `bc250ctl`, `bc250-mcp`, `bc250-gl` |
| Application menu | `~/.local/share/applications/bc250-control.desktop` |
| Background services | user units `bc250d.service` and `bc250-overlay.service`, enabled and started |
| Shortcuts | registers Shift+F1/F2/F3 in KDE global shortcuts (KGlobalAccel) |
| MangoHud | stops loading MangoHud globally (see below). Takes effect from the next login |
| OpenGL Flatpak apps | adds the GL engine to the Flatpak apps listed in `FLATPAK_GL_APPS` |
| MCP server | registers `bc250-mcp` in Claude Code (`claude mcp add -s user bc250 …`) if the `claude` CLI exists |
| Real GPU clock (8 core) | installs `bc250-metricsfix.service` with `sudo -n`. Skipped if sudo needs a password or the governor is missing |

> The launchers point at the cloned folder: keep the repository where you cloned it, or run the installer
> again after moving it.

### About MangoHud

The app replaces MangoHud. If your `~/.bashrc` exports `MANGOHUD=1`, the installer makes that line
conditional on the flag file `~/.config/bc250/mangohud-disabled` and keeps a backup (`.bashrc.bak-bc250`).
You can turn MangoHud back on from **Games & FPS → MangoHud** in the app.

## Making games use the engine

| Game type | What to do |
|---|---|
| Vulkan, DXVK/VKD3D (almost every Proton game) | nothing: the implicit layer is loaded automatically |
| Native OpenGL Steam games | launch options: `bc250-gl %command%` |
| OpenGL Flatpak apps (e.g. Hytale launcher) | toggle the app in **Games & FPS → OpenGL games** |
| Skip the engine for one game | launch options: `DISABLE_BC250_LAYER=1 %command%` |

The layer ignores processes that are not games: Steam web helper, Plasma, KWin, Xwayland, browsers, the
app itself.

## Uninstall

```sh
python3 -m bc250.install --remove
```

This stops and removes the services, shortcuts, launchers, the layer manifest, the Flatpak overrides and
`bc250-metricsfix`. MangoHud comes back from the next login. Your settings (`~/.config/bc250`) and history
(`~/.local/share/bc250`) are kept. Delete them by hand if you want a clean slate.
