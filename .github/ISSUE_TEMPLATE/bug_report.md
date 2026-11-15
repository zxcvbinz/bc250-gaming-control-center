---
name: Bug report
about: Something does not work as expected
labels: bug
---

**What happened**
<!-- What you did, what you expected, what you got. -->

**Game / launcher**
<!-- e.g. Dead Island 2 on Steam (Proton 10), a Lutris game, a script in distrobox… -->

**System**
- Distribution and version (e.g. Bazzite 43):
- Kernel (`uname -r`):
- Mesa (`vulkaninfo --summary | grep driverInfo`):
- 6 or 8 cores unlocked:
- App version (`git rev-parse --short HEAD`):

**Logs**
```
journalctl --user -u bc250d -u bc250-overlay --since "15 min ago"
```
<!-- Health page screenshot, ~/.local/share/bc250/run.log for launcher issues. -->
