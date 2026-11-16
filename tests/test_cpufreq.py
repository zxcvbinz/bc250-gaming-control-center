# SPDX-License-Identifier: GPL-3.0-or-later
"""Tetto di frequenza CPU su un finto /sys/devices/system/cpu."""
import os

from bc250 import common

STEPS = "3200000 2550000 2325000 1960000 1820000 1600000 1271000 800000"


def fake_sys(tmp_path, cpus=4):
    for n in range(cpus):
        d = tmp_path / f"cpu{n}" / "cpufreq"
        d.mkdir(parents=True)
        for name, val in (("scaling_available_frequencies", STEPS), ("cpuinfo_max_freq", "3200000"),
                          ("scaling_max_freq", "3200000"), ("scaling_driver", "acpi-cpufreq")):
            (d / name).write_text(val + "\n")
    (tmp_path / "cpufreq").mkdir()      # non è una CPU: va ignorata
    return tmp_path


def test_no_cpufreq(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CPU_SYS", str(tmp_path))
    assert common.cpufreq_info() is None
    assert common.set_cpu_max(2550) is False


def test_info_and_cap(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CPU_SYS", str(fake_sys(tmp_path)))
    info = common.cpufreq_info()
    assert info["steps"][:2] == [3200, 2550] and info["hw_max"] == 3200 and info["cpus"] == 4
    assert common.set_cpu_max(2550)
    assert {(tmp_path / f"cpu{n}/cpufreq/scaling_max_freq").read_text() for n in range(4)} == {"2550000"}
    assert common.cpufreq_info()["max"] == 2550 and common.cpufreq_info()["uniform"]
    (tmp_path / "cpu1/cpufreq/scaling_max_freq").write_text("3200000")
    assert common.cpufreq_info()["uniform"] is False and common.cpufreq_info()["max"] == 3200
    assert common.set_cpu_max(2550) and common.cpufreq_info()["uniform"]
    # 0/None = massimo hardware; oltre il massimo viene tagliato
    assert common.set_cpu_max(0) and common.cpufreq_info()["max"] == 3200
    assert common.set_cpu_max(9999) and common.cpufreq_info()["max"] == 3200


def test_not_writable(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "CPU_SYS", str(fake_sys(tmp_path, 2)))
    for n in range(2):
        os.chmod(tmp_path / f"cpu{n}/cpufreq/scaling_max_freq", 0o444)
    if os.access(tmp_path / "cpu0/cpufreq/scaling_max_freq", os.W_OK):
        return  # root: i permessi non contano
    assert common.cpufreq_info()["writable"] is False
    assert common.set_cpu_max(2550) is False
