# SPDX-License-Identifier: GPL-3.0-or-later
"""Ogni testo passato a T("...") ha la traduzione inglese, con gli stessi segnaposto."""
import ast
import glob
import os
import string

from bc250.lang_en import EN

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAME_IN_ENGLISH = {"FPS", "Overlay", "VRR", "RAM", "VRAM", "Display", "MangoHud", "Governor", "Swap / zram",
                   "SSD NVMe", "BC-250", "1% low", "Frametime (ms)", "CPU", "GPU", "OK"}


def t_keys():
    for path in glob.glob(os.path.join(ROOT, "bc250", "*.py")):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("T", "_T", "T_")
                    and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                yield os.path.basename(path), node.args[0].value


def fields(s):
    return {f for _, f, _, _ in string.Formatter().parse(s) if f}


def test_every_string_has_english():
    missing = sorted({k for _, k in t_keys() if k not in EN and k.strip() not in SAME_IN_ENGLISH
                      and any(c.isalpha() for c in k)})
    assert not missing, f"senza traduzione: {missing[:20]}"


def test_placeholders_match():
    bad = [k for k, v in EN.items() if fields(k) != fields(v)]
    assert not bad, bad
