# SPDX-License-Identifier: GPL-3.0-or-later
"""Test isolati: HOME temporanea (niente config o storico veri) e Qt senza display."""
import os
import sys
import tempfile

_home = tempfile.mkdtemp(prefix="bc250-test-home-")
os.environ["HOME"] = _home
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["XDG_RUNTIME_DIR"] = _home
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
