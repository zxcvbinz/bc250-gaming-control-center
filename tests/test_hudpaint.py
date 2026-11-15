# SPDX-License-Identifier: GPL-3.0-or-later
import copy

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtGui import QImage, QPainter  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from bc250 import common, hudpaint  # noqa: E402

app = QApplication.instance() or QApplication([])


def cfg_with(**over):
    c = copy.deepcopy(common.DEFAULTS)
    c["overlay"].update(over)
    return c


def test_attention_rules():
    cfg = cfg_with()
    assert hudpaint.attention(hudpaint.demo_state("ok", cfg), cfg) == {}
    assert "cpu_temp" in hudpaint.attention(hudpaint.demo_state("hot", cfg), cfg)
    drop = hudpaint.attention(hudpaint.demo_state("drop", cfg), cfg)
    assert "fps_drop" in drop and "stutter" in drop
    assert "throttling" in hudpaint.attention(hudpaint.demo_state("throttle", cfg), cfg)


def test_bubble_expands_after_debounce():
    cfg = cfg_with(style="bubble")
    h = hudpaint.HudPainter()
    st = hudpaint.demo_state("drop", cfg)
    h.update(st, cfg, now=0)
    assert h.keys == []
    h.update(st, cfg, now=2.5)
    assert set(h.keys) >= {"fps_drop", "stutter"}


@pytest.mark.parametrize("style", ["bubble", "ring", "compact", "full"])
@pytest.mark.parametrize("n", [2, 5, 8])
def test_every_style_paints(style, n):
    items = ["fps", "frametime", "cpu_temp", "gpu_temp", "power", "gpu_clk", "gpu_busy", "ram", "fan"][:n + 1]
    cfg = cfg_with(style=style, items=items, look={"colors": "mono", "border": True})
    h = hudpaint.HudPainter()
    st = hudpaint.demo_state("hot", cfg)
    h.update(st, cfg, now=5)
    h.settle()
    w, hh = h.size(st, cfg)
    assert w > 0 and hh > 0
    img = QImage(w, hh, QImage.Format.Format_ARGB32)
    p = QPainter(img)
    h.paint(p, st, cfg, w, hh)
    p.end()
