# SPDX-License-Identifier: GPL-3.0-or-later
from bc250 import launchers as L


def test_add_token_keeps_existing_options():
    assert L.add_token("") == "bc250-run %command%"
    assert L.add_token("-novid -high") == "bc250-run %command% -novid -high"
    opts = 'PROTON_USE_WINED3D=1 WINEDLLOVERRIDES=\\"x=n,b\\" %command% -skip_intro'
    assert L.add_token(opts) == 'PROTON_USE_WINED3D=1 WINEDLLOVERRIDES=\\"x=n,b\\" bc250-run %command% -skip_intro'


def test_add_token_is_idempotent_and_drops_mangohud():
    assert L.add_token("bc250-run %command%") == "bc250-run %command%"
    assert L.add_token("mangohud %command%", drop_mangohud=True) == "bc250-run %command%"
    assert L.add_token("mangohud --dlsym %command%", drop_mangohud=True) == "bc250-run %command%"
    assert L.add_token("mangohud %command%") == "mangohud bc250-run %command%"


def test_remove_token_restores():
    for opts in ("", "PROTON_LOG=1 %command% -windowed"):
        assert L.remove_token(L.add_token(opts)) == opts


def test_text_vdf_roundtrip():
    text = ('"UserLocalConfigStore"\n{\n\t"Software"\n\t{\n\t\t"Valve"\n\t\t{\n\t\t\t"Steam"\n\t\t\t{\n'
            '\t\t\t\t"apps"\n\t\t\t\t{\n\t\t\t\t\t"275850"\n\t\t\t\t\t{\n'
            '\t\t\t\t\t\t"LaunchOptions"\t\t"A=\\"1\\" %command%"\n\t\t\t\t\t}\n\t\t\t\t}\n\t\t\t}\n\t\t}\n\t}\n}\n')
    d = L.vdf_loads(text)
    assert L.vdf_loads(L.vdf_dumps(d)) == d
    assert d["UserLocalConfigStore"]["Software"]["Valve"]["Steam"]["apps"]["275850"]["LaunchOptions"] == 'A=\\"1\\" %command%'


def test_binary_vdf_roundtrip():
    entry = {"appid": ("int", 3772918909), "AppName": "Some Launcher", "Exe": '"/x/game.exe"',
             "LaunchOptions": "", "IsHidden": ("int", 0), "tags": {}}
    raw = b"\x00shortcuts\x00" + L.bvdf_dumps({"0": entry}) + b"\x08"
    d = L.bvdf_loads(raw)
    assert d["shortcuts"]["0"]["appid"] == ("int", 3772918909)
    assert b"\x00shortcuts\x00" + L.bvdf_dumps(d["shortcuts"]) + b"\x08" == raw


def test_slug():
    assert L.slug("BLUE PRINCE.exe") == "blue-prince-exe"
    assert L.slug("???") == "gioco"
