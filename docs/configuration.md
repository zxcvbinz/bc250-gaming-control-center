# Configuration reference

← [Project README](../README.md) · [Documentation index](README.md)

All settings live in `~/.config/bc250/config.json`. Every page of the app writes there, and every process
(daemon, overlay) reloads it as soon as the file changes. Missing keys fall back to the defaults below, so
the file only needs what you changed.

## `engine`

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | engine active in games. Off = the layer stays passive (no counting, no limiting) |
| `fps_limit` | `60` | global FPS limit (`0` = none) |
| `limit_enabled` | `true` | the Shift+F1 switch |

## `overlay`

| Key | Default | Meaning |
|---|---|---|
| `hud_visible` | `true` | the Shift+F3 switch |
| `only_in_game` | `true` | hide the HUD on the desktop |
| `style` | `"bubble"` | `bubble`, `ring`, `compact`, `full` |
| `position` | `"top-left"` | `top-left`, `top-center`, `top-right`, `bottom-left`, `bottom-center`, `bottom-right` |
| `margin` | `24` | px from the screen edge |
| `scale` | `1.0` | 0.6 – 2.0 |
| `opacity` | `0.82` | background opacity |
| `items` | fps, frametime, cpu_temp, gpu_temp, gpu_clk, power | ordered list of shown values for `ring`, `compact` and `full`. Also `low1`, `gpu_busy`, `cpu_load`, `fan`, `ram`, `vram`, `ft` (frametime in ms), `cpu_clk`. The ring uses up to 8 (`frametime` = mini graph in the centre) |
| `graph` | `true` | frametime graph in `full` |
| `look.labels` | `true` | captions next to/under the numbers |
| `look.border` | `false` | border in the main colour |
| `look.limit_badge` | `true` | show `⏵ limit` next to the FPS |
| `look.colors` | `"status"` | `status` (traffic light) or `mono` (only problems in colour) |
| `look.accent` | `"#4fa3ff"` | main colour |

### `overlay.bubble` (bubble and ring)

| Key | Default | Meaning |
|---|---|---|
| `center` | `"fps"` | value inside the bubble: `fps`, `cpu_temp`, `gpu_temp`, `power` |
| `idle` | `"visible"` | when all is fine: `visible`, `faded`, `hidden` |
| `hold_s` | `8` | seconds the bubble stays open after the problem is gone |
| `watch` | all | conditions that expand the bubble / light the ring halo (see [Overlay](overlay.md#smart-bubble)) |
| `cpu_temp` / `gpu_temp` | `85` / `80` | °C thresholds |
| `fps_drop_pct` | `85` | % of the FPS limit |
| `fps_min` | `40` | FPS target for games without a limit |
| `stutter_pct` | `50` | 1% low as % of FPS |
| `ram_pct` | `90` | % RAM used |

## `alerts`

Desktop notifications (plus an on-screen toast for critical ones).

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | |
| `cpu_temp` | `90` | °C |
| `gpu_temp` | `88` | °C |
| `fan_min_rpm` | `400` | below this the fan is considered stopped |
| `cooldown_s` | `180` | do not repeat the same alert sooner |

## Other sections

| Key | Default | Meaning |
|---|---|---|
| `history.enabled` | `true` | record sessions |
| `history.keep_days` | `60` | prune older sessions |
| `history.merge_gap_s` | `300` | same game back within this time = same session |
| `display.vrr_games_only` | `true` | manage VRR per game (see [Profiles](profiles.md#vrr)) |
| `display.vrr_off_delay_s` | `8` | seconds after the game closes before VRR goes off |
| `launcher.mode` | `"ask"` | newly installed games: `ask` (notification with Link/Ignore), `auto`, `off` ([details](graphics.md#automatic-mode-in-detail)) |
| `display.upscale_filter` / `.upscale_sharpness` | `fsr` / `3` | gamescope filter and sharpness for profiles with `upscale` |
| `gpu_default.min` / `.max` | `1000` / `1750` | governor range without a profile |
| `language` | `"it"` | language of the app, overlay and notifications: `it`, `en` (also from the picker at the bottom of the sidebar) |
| `profiles` | `[]` | see [Profiles](profiles.md) |

## Files and paths

| Path | Content |
|---|---|
| `~/.config/bc250/config.json` | settings and profiles |
| `~/.config/bc250/mangohud-disabled` | flag: MangoHud not loaded in games |
| `~/.local/share/bc250/history.db` | history (SQLite, WAL) |
| `~/.local/lib/bc250/` | engine libraries |
| `~/.local/share/vulkan/implicit_layer.d/bc250_frame.json` | Vulkan layer manifest |
| `/dev/shm/bc250-$UID/` | live data: `state.json`, `control.bin`, `fps-<pid>-*.bin`, `overlay.sock` |
| `$XDG_RUNTIME_DIR/bc250/` | the same for Flatpak games |
| `~/.config/systemd/user/bc250d.service`, `bc250-overlay.service` | user services |
| `/etc/systemd/system/bc250-metricsfix.service` | root service (optional) |

## Command line

```sh
bc250ctl toggle-limit      # Shift+F1
bc250ctl toggle-panel      # Shift+F2
bc250ctl toggle-hud        # Shift+F3
bc250ctl limit 75          # global limit (or: off)
bc250ctl status            # live state as JSON
bc250-control --page 3     # open the app on a page (0 = Dashboard … 7 = Alerts)
```
