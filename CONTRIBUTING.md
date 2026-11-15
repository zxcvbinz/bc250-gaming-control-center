# Contributing

Thanks for helping! Bug reports, game reports ("works / doesn't work with X") and pull requests are all welcome.

## Development setup

```sh
git clone https://github.com/zxcvbinz/bc250-gaming-control-center.git
cd bc250-gaming-control-center
python3 -m venv --system-site-packages .venv && . .venv/bin/activate
pip install -e ".[dev]"     # pytest, ruff (PyQt6/PyGObject usually come from the distribution)
make -C layer               # build the FPS engine
```

Run the pieces from the checkout while you work on them:

```sh
python3 -m bc250.gui        # the app
python3 -m bc250.daemon     # stop the service first: systemctl --user stop bc250d
python3 -m bc250.overlay    # stop the service first: systemctl --user stop bc250-overlay
```

`python3 -m bc250.install` installs launchers that point at this folder, so after installing, your edits are
live once you restart the services (`systemctl --user restart bc250d bc250-overlay`).

## Before opening a pull request

```sh
ruff check bc250 tests
QT_QPA_PLATFORM=offscreen pytest -q
```

CI runs the same checks plus a build of `layer/`.

- **Keep it safe for games.** Anything that runs inside a game (`layer/`) or touches game/Steam files must never
  crash a game or lose user data: fall back to doing nothing, and back files up before writing them.
- **Translations.** User-facing text goes through `T("Italian source text")` from `bc250/i18n.py`; add the
  English entry to `bc250/lang_en.py` (a test checks that every string is translated). New language: add
  `bc250/lang_xx.py` with a `XX` dict and an entry in `LANGS`.
- **Code style.** Comments and docstrings in the existing code are mostly in Italian; English is welcome in new
  code. Keep functions small and readable, follow the existing structure (see [architecture](docs/architecture.md)).
- **Docs.** If you change behaviour or add a setting, update the matching page in `docs/` and, for big
  features, the README.

## Reporting games

The most useful reports say which game, which store/launcher, which engine if you know it (Unreal, Unity…),
whether the FPS counter, the limiter, the overlay, the upscaling and the graphics-settings tracking work, and
what the Health page shows.

## License

By contributing you agree that your contribution is licensed under the [GPL-3.0-or-later](LICENSE).
