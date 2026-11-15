# Security

Most of the app runs as your user. Two parts are worth knowing about:

- **`bc250-metricsfix`** (optional) runs as **root** to bind-mount corrected `gpu_metrics`/`pp_dpm_sclk` files. The
  installer copies the script to `/usr/local/lib/bc250/metricsfix.py` (root-owned) so the root service never runs
  code from your home folder. It uses only the Python standard library and touches only those two sysfs files.
- **Game and launcher files**: the app edits Steam `localconfig.vdf`/`shortcuts.vdf`, Lutris and Heroic game
  configs, and games' own settings files. Every file is backed up first under `~/.local/share/bc250/backups/`.

The MCP server only talks over stdio to the client that started it.

If you find a security problem, please open a GitHub issue **without exploit details** and ask for a private
contact, or use GitHub's private vulnerability reporting if enabled for the repository.
