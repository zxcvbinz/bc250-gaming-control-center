# SPDX-License-Identifier: GPL-3.0-or-later
from bc250 import run


def test_find_profile_by_appid_and_text(monkeypatch):
    cfg = {"profiles": [{"name": "A", "match": "appid:42"}, {"name": "B", "match": "DeadIsland"}]}
    monkeypatch.setenv("SteamAppId", "42")
    assert run.find_profile(cfg, ["/x/whatever"])["name"] == "A"
    monkeypatch.delenv("SteamAppId")
    assert run.find_profile(cfg, ["/g/DeadIsland-Win64-Shipping.exe"])["name"] == "B"
    assert run.find_profile(cfg, ["/g/other"]) is None


def test_build_gamescope(monkeypatch):
    monkeypatch.setattr(run, "screen", lambda: (3440, 1440, 165))
    monkeypatch.setattr(run.shutil, "which", lambda x: "/usr/bin/gamescope")
    monkeypatch.delenv("GAMESCOPE_WAYLAND_DISPLAY", raising=False)
    cmd, env = run.build(["/game"], {"display": {}}, {"upscale": "q67", "vrr": True})
    assert cmd[:9] == ["gamescope", "-W", "3440", "-H", "1440", "-w", "2294", "-h", "960"]
    assert "--adaptive-sync" in cmd and cmd[-2:] == ["--", "/game"]


def test_build_passthrough():
    cmd, env = run.build(["/game", "-x"], {"display": {}}, None)
    assert cmd == ["/game", "-x"] and env == {}
