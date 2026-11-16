# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 zxcvbinz and contributors
"""bc250-cpufreq (root, all'avvio): permesso di scrittura su scaling_max_freq per un gruppo.

Così il servizio utente bc250d può impostare il tetto di frequenza CPU (globale o del profilo)
senza sudo. Tocca solo /sys/devices/system/cpu/cpu*/cpufreq/scaling_max_freq: il kernel accetta
solo frequenze tra minimo e massimo hardware, quindi il peggio possibile è una CPU più lenta.
Senza driver cpufreq (BC-250 senza fix ACPI) aspetta un po' e poi esce senza fare niente.

Uso: python3 -I cpufreqperm.py --group NOME
"""
import grp
import os
import sys
import time

CPU_SYS = "/sys/devices/system/cpu"


def targets():
    out = []
    for n in sorted(os.listdir(CPU_SYS)):
        f = os.path.join(CPU_SYS, n, "cpufreq", "scaling_max_freq")
        if n.startswith("cpu") and n[3:].isdigit() and os.path.isfile(f):
            out.append(f)
    return out


def main():
    if "--group" not in sys.argv:
        sys.exit("uso: cpufreqperm.py --group NOME")
    gid = grp.getgrnam(sys.argv[sys.argv.index("--group") + 1]).gr_gid
    # il driver cpufreq può caricarsi dopo questo servizio: aspetta fino a 60 s
    for _ in range(60):
        files = targets()
        if files:
            break
        time.sleep(1)
    else:
        print("cpufreq non disponibile: niente da fare")
        return
    for f in files:
        os.chown(f, 0, gid)
        os.chmod(f, 0o664)
    print(f"scaling_max_freq scrivibile dal gruppo {gid} su {len(files)} CPU")


if __name__ == "__main__":
    main()
