# BC-250 Control Center

Centro di controllo per la AMD BC-250: monitor, motore FPS al posto di MangoHud,
overlay in gioco, profili per gioco, VRR, salute del sistema, storico e server MCP.

## Pezzi
| Componente | Cosa fa |
|---|---|
| `layer/` (C) | `libbc250_vk.so` layer Vulkan implicito + `libbc250_gl.so` (LD_PRELOAD OpenGL). Conta i frame e applica il limite FPS, cambiabile a caldo. |
| `bc250d` | Servizio utente: sensori, giochi attivi, profili, storico SQLite, avvisi. Scrive lo stato in `/dev/shm/bc250-$UID/state.json`. |
| `bc250-overlay` | HUD minimal + pannello dettagli + avvisi a schermo (Wayland layer-shell, sopra anche ai giochi a schermo intero). |
| `bc250-control` | GUI: Panoramica, Giochi e FPS, Profili, Overlay, Display (VRR), Salute, Storico, Avvisi. |
| `bc250ctl` | Comandi rapidi: `toggle-limit`, `toggle-panel`, `toggle-hud`, `limit <n|off>`, `status`. |
| `bc250-mcp` | Server MCP per Claude Code (stato live, storico, segni nei test, limite FPS, clock GPU, profili). |

## Tasti
- **Shift+F1** limite FPS on/off
- **Shift+F2** pannello dettagli
- **Shift+F3** overlay on/off

## File
- Configurazione: `~/.config/bc250/config.json`
- Storico: `~/.local/share/bc250/history.db`
- Motore: `~/.local/lib/bc250/`, manifest `~/.local/share/vulkan/implicit_layer.d/bc250_frame.json`
- Giochi Steam OpenGL nativi: opzioni di avvio `bc250-gl %command%`
- Disattivare il motore per un singolo gioco: `DISABLE_BC250_LAYER=1 %command%`

## Installare / aggiornare / rimuovere
```sh
cd ~/bc250-tools/bc250-control
python3 -m bc250.install            # installa o aggiorna
python3 -m bc250.install --remove   # rimuove tutto (MangoHud torna attivo al prossimo accesso)
```
