# SPDX-License-Identifier: GPL-3.0-or-later
from bc250 import gamecfg as G

INI = """[ScalabilityGroups]
sg.ShadowQuality=3

[/Script/Engine.GameUserSettings]
FrameRateLimit=0.000000
LastUserConfirmedResolutionSizeX=3440
"""


def test_unreal_read_write(tmp_path):
    p = tmp_path / "GameUserSettings.ini"
    p.write_text(INI)
    src = G.UnrealIni(str(p))
    before = src.read()
    assert before["ScalabilityGroups/sg.ShadowQuality"] == "3"
    src.write({"ScalabilityGroups/sg.ShadowQuality": 1, "ScalabilityGroups/sg.EffectsQuality": 2,
               "/Script/Engine.GameUserSettings/bUseVSync": "False", "New/Key": 5})
    after = src.read()
    assert after["ScalabilityGroups/sg.ShadowQuality"] == "1"
    assert after["ScalabilityGroups/sg.EffectsQuality"] == "2"
    assert after["/Script/Engine.GameUserSettings/bUseVSync"] == "False"
    assert after["New/Key"] == "5"
    text = p.read_text()
    assert text.index("sg.EffectsQuality") < text.index("[/Script/Engine.GameUserSettings]")


def test_diff_ignores_noise():
    a = {"S/sg.ShadowQuality": "3", "S/LastUserConfirmedResolutionSizeX": "3440"}
    b = {"S/sg.ShadowQuality": "1", "S/LastUserConfirmedResolutionSizeX": "1920"}
    assert G.diff(a, b) == {"S/sg.ShadowQuality": ["3", "1"]}


def test_mxml_nested_keys(tmp_path):
    p = tmp_path / "TKGRAPHICSSETTINGS.MXML"
    p.write_text('<Data template="X">\n'
                 '  <Property name="GraphicsDetail" value="TkGraphicsDetailPresets">\n'
                 '    <Property name="ShadowQuality" value="TkGraphicsDetailTypes">\n'
                 '      <Property name="GraphicDetail" value="Medium" />\n'
                 '    </Property>\n'
                 '  </Property>\n'
                 '  <Property name="AntiAliasing" value="FFXSR2" />\n</Data>\n')
    src = G.Mxml(str(p))
    d = src.read()
    assert d["GraphicsDetail.ShadowQuality.GraphicDetail"] == "Medium"
    src.write({"GraphicsDetail.ShadowQuality.GraphicDetail": "Low"})
    assert src.read()["GraphicsDetail.ShadowQuality.GraphicDetail"] == "Low"
    assert src.read()["AntiAliasing"] == "FFXSR2"


def test_win_to_unix():
    assert G.win_to_unix("Z:\\home\\u\\Game.exe", None) == "/home/u/Game.exe"
    assert G.win_to_unix("C:\\Games\\G.exe", "/pfx") == "/pfx/drive_c/Games/G.exe"
