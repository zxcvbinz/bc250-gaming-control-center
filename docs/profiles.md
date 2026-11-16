# Game profiles

← [Project README](../README.md) · [Documentation index](README.md)

A profile holds the settings for one game. `bc250d` applies it when the game starts presenting frames and
restores the defaults when it stops.

Edit profiles in three places:

- **Profiles** page in the app (table, *Add*, *From running game*, *Save*);
- in game with the **Shift+F2** panel (arrow keys, saved instantly);
- through the MCP tool `save_profile`.

## Matching

`match` decides which game a profile belongs to. The first profile that matches wins.

| `match` value | Matches |
|---|---|
| `appid:275850` | the Steam game with that app id (read from `SteamAppId`) |
| any other text | a game whose process name *contains* it, case-insensitive (e.g. `HytaleClient`, `BLUE PRINCE.exe`) |

Non-Steam games run through Proton report `SteamAppId=default`. The app ignores that value, so such games
are always matched by process name. For Windows games the process name is the `.exe`.

## Fields

| Field | Values | Effect |
|---|---|---|
| `fps_limit` | `null` (use global), `0` (no limit), 30 … 165 | FPS cap for this game. Applied live through the engine, no restart |
| `gpu_max` | `null` (default range), 1000 … 2000 MHz | maximum GPU clock sent to the governor while the game runs |
| `gpu_min` | MHz | optional minimum clock (only editable via config/MCP) |
| `vrr` | `true` / `false` | turn FreeSync/VRR on while this game runs (see below) |
| `heat_guard` | `null` (off), 80 … 90 °C | dynamic FPS reduction when the CPU gets hot |
| `hud` | `true` / `false` | show the overlay in this game |
| `hud_position` | `null` (global) or an anchor | overlay position in this game |
| `hud_style` | `null` (global), `bubble`, `ring`, `compact`, `full` | overlay style in this game |
| `cpu_max` | `null` (global), `0` (no cap), 3200 … 1600 MHz | CPU frequency cap while the game runs. Needs cpufreq, see [CPU](cpu.md) |
| `upscale` | `null`, `q77`, `q67`, `q59`, `q50` | render at that resolution and upscale with FSR 1 via gamescope (needs `bc250-run %command%`, [details](graphics.md#upscaling-for-any-game-bc250-run)) |
| `opengl` | `true` / `false` | with `bc250-run`: load the OpenGL FPS engine |
| `graphics` | `{key: value}` | the game's own graphics settings to enforce, applied when the game closes ([details](graphics.md)) |
| `notes` | text | free notes |

Example (`~/.config/bc250/config.json`):

```json
"profiles": [
  {"name": "Hytale", "match": "HytaleClient", "fps_limit": 90, "gpu_max": 1750, "heat_guard": 85},
  {"name": "No Man's Sky", "match": "appid:275850", "fps_limit": 60, "hud_style": "ring", "vrr": true}
]
```

## FPS limit priority

1. **Shift+F1 off** → no limit at all, in every game.
2. **Heat guard engaged** → the profile limit (or 120 without one) minus the guard cut, never below 40.
3. **Profile `fps_limit`** → that value. `0` means unlimited.
4. Otherwise the **global limit** (Games & FPS page / `bc250ctl limit <n|off>`).

The limiter sleeps until the next frame slot, then busy-waits the last 0.3 ms, so frame pacing stays even.

## Heat guard

The BC-250's single fan cannot cool the CPU under a full 16-thread load: it can reach 95 °C+ in a minute.
The heat guard trades a few FPS for temperature:

- CPU ≥ threshold → the limit drops by **10 FPS every 20 s** (never below 40);
- CPU ≤ threshold − 8 °C for 30 s → it climbs back by 10 FPS;
- each step shows a toast. The details panel shows *LIMIT … · HEAT GUARD*.

## VRR

VRR is enabled only while a game whose profile has `vrr: true` runs. It is switched off 8 s after the game
closes (`display.vrr_off_delay_s`). On some monitors VRR causes brightness flicker on the desktop, so it
stays off by default.

Changing VRR means re-applying the display mode, so the screen **goes black for a moment** when the game
starts and closes. The **Display** page shows each output and lets you set VRR and the mode by hand.

## GPU clock

Without a profile, the governor range is `gpu_default` (default 1000–1750 MHz, editable in **Profiles →
Default GPU clock**). A profile with `gpu_max` narrows or widens it while the game runs. The governor
still throttles on temperature by itself.
