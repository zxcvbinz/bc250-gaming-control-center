# MCP server

← [Project README](../README.md) · [Documentation index](README.md)

`bc250-mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server over stdio. It lets an AI
assistant watch the machine while you play, compare settings with you and change them. The installer
registers it in Claude Code automatically. For other clients, run `~/.local/bin/bc250-mcp` as a stdio server.

```sh
claude mcp add -s user bc250 -- ~/.local/bin/bc250-mcp
```

After updating the app, reconnect the server in your client (`/mcp` in Claude Code) to load the new code.

## Tools

| Tool | Arguments | Returns / does |
|---|---|---|
| `get_status` | – | live state: game, FPS, 1% low, temperatures, GPU clock, power, FPS limit, throttling |
| `get_recent` | `seconds` (60), `points` (30) | summary and timeline of the last N seconds of play |
| `list_sessions` | `limit` (15) | latest sessions with averages and maxima. `merged_ids` lists sessions merged into each one |
| `get_session` | `id`, `points` (60) | full session: summary, **parts** (continuous stretches split by alt+tab/pauses over 20 s), marks, per-mark segments, timeline. Old ids of merged sessions resolve to the merged session, with a `note` |
| `mark` | `note` | adds a mark to the running session ("shadows low", "limit 75") |
| `set_fps_limit` | `limit`, `profile` (optional) | changes the FPS limit live, globally or for a profile. `0` removes it |
| `set_gpu_clock` | `max`, `min` | changes the governor range live (temporary: a profile or game change resets it) |
| `list_profiles` | – | all game profiles |
| `save_profile` | `name` + any profile field | creates or updates a profile (see [Profiles](profiles.md)) |
| `get_game_settings` | `game` (optional), `all` | the game's own graphics settings, what the profile enforces, history of changes ([details](graphics.md)) |
| `set_game_settings` | `game`, `settings`, `save_to_profile` | changes graphics settings: now if the game is closed, at exit if it runs |
| `health_check` | – | the same checks as the Health page |
| `get_config` | – | engine, alerts, default GPU clock and overlay settings |

## A typical tuning session

1. Start the game, ask the assistant to `get_status`.
2. It sets a limit (`set_fps_limit 75`) and adds a `mark` "limit 75".
3. You play for a few minutes; it tries `limit 90` and marks again.
4. `get_session` compares the two stretches: average FPS, 1% low, max CPU/GPU temperature, throttling.
5. It saves the winner with `save_profile`.
6. For heavier changes it reads the graphics with `get_game_settings` and lowers the expensive options with
   `set_game_settings`. They apply from the next launch, and the next session shows whether temperatures
   and 1% lows improved.
