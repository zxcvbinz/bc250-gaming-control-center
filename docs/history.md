# Session history

← [Project README](../README.md) · [Documentation index](README.md)

When `history.enabled` is on, `bc250d` records every game session in SQLite at
`~/.local/share/bc250/history.db`.

## What is recorded

One sample per second while the game is presenting frames:

| Column | Meaning |
|---|---|
| `fps`, `low1`, `ft_max` | FPS, 1% low (over the last 120 frames), worst frametime of the last 60 frames |
| `fps_limit` | limit applied on that frame |
| `cpu_temp`, `gpu_temp` | °C |
| `gpu_clk`, `gpu_max` | current GPU clock and governor max (MHz) |
| `gpu_busy`, `cpu_load` | % |
| `power` | SoC power (W) |
| `fan`, `ram` | rpm, GiB used |
| `throttling` | 1 if the GPU was at the governor's throttle temperature |

Sessions shorter than 20 s are discarded. Data older than `history.keep_days` (60) is pruned at startup.

## When a session starts and ends

A game is identified by **process name + Steam app id**, not by process id.

- A game "disappears" when it stops presenting frames for 2 s. This happens with alt+tab, minimising,
  some loading screens and pause menus.
- The session **stays open**. If the same game comes back within `history.merge_gap_s` (300 s), recording
  continues in the same session.
- If a different game starts, the open session is closed.
- If nothing comes back within 5 minutes, the session is closed at the time of the last frame.
- If the same game is relaunched within 5 minutes, it continues the previous session too.

The session's wall-clock span therefore includes time away from the game. The app shows both:
*in game* (sample count) and *away from the game*.

On startup the daemon also merges consecutive sessions of the same game recorded by older versions (before
this logic existed) with gaps under `merge_gap_s`. The old ids are kept as aliases (table `session_alias`),
so `get_session` with an old id still works. New sessions never reuse an aliased id.

## In the app

**History** groups sessions by game. Games are sorted by most recent play, and each shows the number of
sessions, total time in game and the last date.

- Select a **game**: totals across all its sessions (time in game, date range, profiles used, average
  FPS, average 1% low, max CPU/GPU temperature, average power, % of time throttled) and the charts of
  all sessions in a row. A purple line marks where each session starts.
- Select a **session**: its summary and charts, with the marks added during tests.

## Marks

During a test you (or an AI assistant through MCP) can add a **mark** ("shadows low", "limit 75"…). Marks
appear as purple lines in the charts. `get_session` summarises each stretch between two marks, so you can
compare settings within one session.
