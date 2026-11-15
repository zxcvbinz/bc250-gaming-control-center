# Changelog

## 0.1.0 — first public release

- FPS engine: implicit Vulkan layer + OpenGL `LD_PRELOAD`, live FPS limit (Shift+F1).
- In-game overlay: smart bubble, full ring (2–8 gauges), compact bar, full panel; fully customisable with live
  preview; details panel with game profile editor (Shift+F2).
- Per-game profiles: FPS limit, GPU clock, VRR, heat guard, overlay, FSR upscaling, graphics settings.
- `bc250-run` launcher with gamescope + FSR 1 upscaling, added automatically to every Steam, Lutris and Heroic
  game; games started any other way are detected and can be linked from the Games page.
- In-game graphics settings (Unreal Engine, Unity, No Man's Sky): snapshot at launch, changes tracked while
  playing, profile settings applied at exit.
- Session history grouped by game, kept together across alt+tab; marks; graphics changes.
- Real GPU clock in `gpu_metrics`/`pp_dpm_sclk` on 8-core boards (`bc250-metricsfix`).
- Health checks, alerts, MCP server for AI assistants, global search, Italian/English UI.
