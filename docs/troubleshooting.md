# Troubleshooting

← [Project README](../README.md) · [Documentation index](README.md)

Start from the **Health** page (or `bc250ctl status`, or the MCP `health_check` tool). It checks the
services, the engine, MangoHud, the governor, the GPU clock reading, the 8-core unlock, the fan,
temperatures, swap/zram, systemd-oomd and RAM.

## The overlay doesn't appear

- Shift+F3 might have turned it off: **Overlay → Overlay on**.
- *Only while playing* is on and no game is detected. Check **Games & FPS → Running games**.
- With the bubble style and *When all is fine → Hidden*, nothing shows until there is a problem. That is
  by design.
- The game's profile may have *Overlay: hidden*.
- `systemctl --user status bc250-overlay`. It needs a Wayland session with LayerShellQt
  (`libLayerShellQtInterface.so.6`).

## A game shows no FPS / is not limited

- Vulkan/Proton games: check that `~/.local/share/vulkan/implicit_layer.d/bc250_frame.json` exists, and
  that the game is not launched with `DISABLE_BC250_LAYER=1`.
- Native OpenGL: add `bc250-gl %command%` to the launch options.
- OpenGL Flatpak: enable it in **Games & FPS → OpenGL games**, then restart the app.
- Is the engine on? **Games & FPS → FPS engine on**.
- Look for `fps-*.bin` files in `/dev/shm/bc250-$(id -u)/` while the game runs.

## The wrong profile is applied

Profiles match in order and the first match wins. A short `match` text (e.g. `game`) can match several
executables. Use the full process name or `appid:<id>`. Non-Steam Proton games never match by app id.

## The GPU clock is wrong in MangoHud / Steam / LACT

On 8-core boards, see [Real GPU clock on 8-core BC-250s](gpu-clock-8core.md). Check that the governor has
`fix-freq = true` and that `bc250-metricsfix` is active. The app itself reads the governor-corrected
hwmon value.

## Sessions in History look split

Since the session-merging logic was added, a session stays open for 5 minutes after the game disappears.
Older split sessions are merged automatically when the daemon starts. If a game really closes and you
start it again 10 minutes later, that is a new session by design. Tune it with `history.merge_gap_s`.

## The screen goes black for a second when a game starts/closes

That is VRR being switched for a profile with `vrr: true`. Set the profile's VRR to off if you don't need it.

## The machine freezes during heavy games

Usually RAM: 16 GB shared with the GPU fills up, zram fills, and the system thrashes. Give it a disk
swapfile next to zram and enable systemd-oomd. The Health page checks both.

## The MCP client can't find a session

Update the app and reconnect the server (`/mcp` in Claude Code). Old ids of merged sessions resolve
automatically. `list_sessions` shows `merged_ids`.

## Logs

```sh
journalctl --user -u bc250d -u bc250-overlay -f
journalctl -u bc250-metricsfix -u cyan-skillfish-governor-smu -f
```
