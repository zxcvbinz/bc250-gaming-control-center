# In-game graphics settings

← [Project README](../README.md) · [Documentation index](README.md)

The app reads each game's own graphics settings (preset, shadows, textures, upscaler, resolution…),
records them with every session, notices when you change them while playing, and can change them for
the next launch, by hand or through an AI assistant.

## Supported games

| Engine | Where the settings are | Examples |
|---|---|---|
| **Unreal Engine 4/5** | `<prefix>/drive_c/users/steamuser/AppData/Local/<Project>/Saved/Config/Windows[NoEditor]/GameUserSettings.ini` | Dead Island 2, State of Decay 2, Satisfactory, most recent AAA games |
| **Unity** (Proton) | Wine registry `<prefix>/user.reg`, key `Software\<Company>\<Product>` (PlayerPrefs) | resolution, fullscreen mode, quality level, per-game options |
| **Unity** (native) | `~/.config/unity3d/<Company>/<Product>/prefs` | |
| **No Man's Sky** | `Binaries/SETTINGS/TKGRAPHICSSETTINGS.MXML` | every option in the graphics menu (FSR 2, shadows, volumetrics, …) |

The game is found from its running process: the Proton prefix comes from `WINEPREFIX` /
`STEAM_COMPAT_DATA_PATH`, the executable from its command line. Unreal is matched by project name
(`DeadIsland-Win64-Shipping.exe` → `AppData/Local/DeadIsland`), Unity by `<Game>_Data/app.info`.
Flatpak games are not supported yet. Games that store settings in a custom binary format, like Blue
Prince's `Settings.dat`, show only what Unity keeps in the registry (resolution, fullscreen).

Setting keys are shown as the game names them:

- Unreal: `Section/Key`, e.g. `ScalabilityGroups/sg.ShadowQuality` (0 low … 3 epic, 4 cinematic),
  `/Script/Engine.GameUserSettings/FrameRateLimit`;
- No Man's Sky: the property path, e.g. `GraphicsDetail.ShadowQuality.GraphicDetail` = `Low` / `Medium` / `High` / `Ultra`;
- Unity: the PlayerPrefs name without its hash suffix, e.g. `Screenmanager Resolution Width`.

## What happens during a session

1. **At launch.** When the game starts presenting frames, `bc250d` finds its settings file and stores a
   snapshot with the session.
2. **While playing.** Every 5 s the daemon checks whether the file changed. Most games write it when you
   press *Apply* in the menu. Changed keys are recorded with a timestamp, a **mark** is added to the
   session ("⚙ sg.ShadowQuality 1→3") and a toast appears on screen. Keys that change by themselves
   (version, cache, "last confirmed" values) are ignored.
3. **After closing.** If the game's profile wants specific settings, they are written now. Many games
   rewrite their settings file on exit, so writing earlier would be overwritten. A timestamped backup is
   kept in `~/.local/share/bc250/backups/<game>/`.

Because of step 2, the history can explain changes in temperature, load or FPS. In **History** a session
shows the main settings at launch, every change made in game and every change applied by the profile.
The marks appear in the charts exactly when the change happened.

## Changing settings

Settings to enforce live in the game profile under `graphics`:

```json
{"name": "Dead Island 2", "match": "DeadIsland",
 "graphics": {"ScalabilityGroups/sg.ShadowQuality": "1", "ScalabilityGroups/sg.EffectsQuality": "1"}}
```

- If the game is **closed**, they are written immediately (with a backup).
- If the game is **running**, they are written as soon as it closes, and apply from the next launch.
- They are re-applied every time the game closes, so the game always starts with them.
- **You stay in control:** if you change one of those settings yourself in the game's menu, your choice
  wins and that key is removed from the profile.

The easiest way to tune them is with an AI assistant through the [MCP server](mcp.md):

| Tool | Use |
|---|---|
| `get_game_settings` | engine, file, current main settings (or all with `all: true`), what the profile enforces, history of changes |
| `set_game_settings` | `game` + `settings` object. Writes now if the game is closed, otherwise at exit. `save_to_profile` (default `true`) keeps them in the profile |
| `get_session` | includes a `graphics` list: snapshot at launch, changes in game, changes applied |

A typical calibration: play with the current settings → the assistant reads temperatures, 1% lows and
throttling from the session → it lowers the heaviest settings (shadows, volumetrics, effects) with
`set_game_settings` → next session it compares.

## Safety

- Only the game's own settings file is touched, always with a backup first.
- Files are never written while the game runs: Wine and the game would overwrite them.
- Unknown keys are refused for Unity and No Man's Sky. For Unreal, new keys are added to their section,
  because Unreal accepts many optional keys.

## Upscaling for any game (`bc250-run`)

Games without a supported settings file, or where you just want more FPS and less heat, can use
**resolution upscaling**, which works with every game.

1. Put `bc250-run %command%` in the game's launch options once (Steam: *Properties → Launch options*.
   Lutris/Heroic: set the *command prefix* to `bc250-run`).
2. Choose **FSR upscaling** in the game's profile (Profiles page, Shift+F2 panel, or MCP
   `save_profile` with `upscale`):

| Preset | Render resolution (each side) | On a 3440×1440 screen |
|---|---|---|
| `q77` ultra quality | 77 % | 2648×1108 |
| `q67` quality | 67 % | 2294×960 |
| `q59` balanced | 59 % | 2030×850 |
| `q50` performance | 50 % | 1720×720 |

At the next launch `bc250-run` starts the game inside [gamescope](https://github.com/ValveSoftware/gamescope)
at the reduced resolution, fullscreen at your screen's resolution and refresh rate, upscaled with
**AMD FSR 1** (sharpness `display.upscale_sharpness`, default 3; 0 is sharpest, 20 softest. Filter
`display.upscale_filter`: `fsr`, `nis`, `linear`, `pixel`). If the profile has `vrr: true`, gamescope
gets `--adaptive-sync`. Gamescope's own shortcuts work in game: Super+U toggles FSR, Super+I/O change
sharpness.

Without upscaling in the profile, `bc250-run` starts the game unchanged, so it is safe to leave in the
launch options. It never blocks a launch: on any error it starts the game directly. What it did is logged
in `~/.local/share/bc250/run.log`. A profile with `opengl: true` also loads the OpenGL FPS engine
(like `bc250-gl`).
