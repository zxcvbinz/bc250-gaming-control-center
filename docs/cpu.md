# CPU idle states and frequency scaling

← [Back to the docs index](README.md)

The **Board** page of the app shows two things about the CPU, read from sysfs:

| Line | Read from | Means |
|---|---|---|
| Idle states (C-states) | `/sys/devices/system/cpu/cpuidle/current_driver` | `acpi_idle`: cores can sleep in C2 when idle. `none`: only HLT. |
| Frequency scaling (cpufreq) | `/sys/devices/system/cpu/cpu0/cpufreq/` | present: the CPU frequency can be capped. Missing: the CPU always runs at its top clock. |

With cpufreq available, the same card has **Max CPU frequency**: a global cap, and each game profile can
use its own (`cpu_max`, also editable in the Shift+F2 panel and with the MCP tool `set_cpu_max`). The
service applies the profile's cap when a game starts and goes back to the global one when it exits.

The app only writes the standard `scaling_max_freq` file. The kernel accepts only frequencies between the
hardware minimum and maximum, so the worst possible result is a slower CPU. To let your user write it without
`sudo`, the installer adds a root oneshot, `bc250-cpufreq.service`, that changes the group and mode of
`scaling_max_freq` at boot and touches nothing else.

The app never changes ACPI tables, MSRs or SMU registers.

## Why they are missing on a stock BC-250

The stock BIOS ships broken CPU tables:

- The idle-state table (`_CST`) is scoped to processor objects `\_PR.C000`–`C00F` that do not exist (the
  processors are `\_PR.P000`–`P00F`). The kernel logs `ACPI BIOS Error ... Could not resolve symbol [\_PR.C000]`
  at boot, and `cpuidle` has no driver.
- The frequency-state table (`_PSS`) is an unfilled template, so `acpi-cpufreq` has nothing to load.

## The community fix

The fix is a set of replacement ACPI tables loaded from the initramfs. Use the community projects, which
document installation, verification and rollback:

- [e-tho/bc250-acpi-fix](https://github.com/e-tho/bc250-acpi-fix): idle states, frequency states and missing
  method stubs, covering all 16 threads.
- [bc250-hub CPU ACPI fix on Bazzite](https://github.com/GonzaloLombardi/bc250-hub/blob/main/docs/cpu-acpi-fix-bazzite.md):
  step-by-step for rpm-ostree (`dracut` + `rpm-ostree initramfs --enable`), with measurements.

Read them fully before installing, and keep a fallback deployment pinned. You are overriding firmware tables
on hardware with a single fan.

What to expect, from the community measurements:

- **Idle states alone save very little** at idle (under 1 W): the cores were already halting.
- **A frequency cap is what lowers temperatures** under load. A cap of 2550 MHz is reported to bring heavy
  CPU loads down by 15–25 °C. Set by hand, `scaling_max_freq` resets at reboot; set in the app, the service
  applies it again at every login.

Results vary from board to board. Measure your own temperatures and frame times before and after.
