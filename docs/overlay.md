# Overlay

← [Project README](../README.md) · [Documentation index](README.md)

The overlay is a separate process (`bc250-overlay`) drawing Wayland **layer-shell** surfaces on the
*overlay* layer. They stay above fullscreen games, never take mouse input and never steal focus (except
the details panel while it is open). It reads the live state written by `bc250d` four times per second.

## Styles

Pick the style in **Overlay → Appearance → Style**. Each game profile can override it (see
[Profiles](profiles.md)).

| Style | Size | Shows | Best for |
|---|---|---|---|
| **Smart bubble** (`bubble`, default) | 56 px circle, grows only when needed | one value (FPS by default) with a progress ring | seeing almost nothing until something is wrong |
| **Full ring** (`ring`) | 112 px circle | FPS in the centre, four gauges around it | keeping everything in sight in a corner |
| **Compact bar** (`compact`) | one 30 px line | FPS + the metrics you tick | a classic, thin readout |
| **Full** (`full`) | ~200–600 px panel | FPS, frametime graph, all metrics you tick | benchmarking |

Size, opacity, position (6 anchors) and distance from the screen edge apply to every style.
The **Preview** at the top of the Overlay page draws the HUD at real size with the same code the game
overlay uses. The *Simulate* menu replays demo situations (CPU hot, FPS drop, GPU throttling) with the same
timings as in game.

### Smart bubble

The bubble shows a single value in the middle. You choose FPS, CPU temperature, GPU temperature or power.
It is wrapped by a ring that fills towards the FPS target. When a watched condition becomes true, the
bubble **expands towards the centre of the screen** and shows only the values involved. Once the problem
is gone it stays open for *hold* seconds (8 by default), then closes.

| Condition (`watch` key) | Triggers when | Shown as |
|---|---|---|
| CPU too hot (`cpu_temp`) | CPU ≥ threshold (default 85 °C). Red from threshold + 5 | `CPU 91°` |
| GPU too hot (`gpu_temp`) | GPU ≥ threshold (default 80 °C) | `GPU 86°` |
| FPS below target (`fps_drop`) | FPS < `fps_drop_pct` % (85) of the game's FPS limit. With no limit, the target is `fps_min` (40) | `TARGET 90` |
| Stutter (`stutter`) | 1% low < `stutter_pct` % (50) of current FPS (only above 20 FPS) | `1% LOW 21` |
| GPU throttling (`throttling`) | GPU temperature reached the governor's throttle point | `GPU CLOCK 1120` |
| RAM almost full (`ram`) | RAM used ≥ `ram_pct` % (90) | `RAM 93%` |
| Fan stopped (`fan`) | fan below the alert threshold (400 rpm) | `FAN 0` |

Daemon alerts (see [Alerts](configuration.md#alerts)) always expand the bubble.

To avoid flashing during loading screens, FPS and stutter must last **2 s** and temperatures **1 s**
before the bubble expands.

**When everything is fine** the bubble can stay *always visible*, become *almost transparent* (35 %), or
be *hidden*. Hidden means nothing on screen at all until a problem appears.

### Full ring

A watch face: FPS in the middle (red when below target) and **one arc per value, from 2 to 8**, starting
at the top and going clockwise. Each arc fills with its value and takes its colour from it. The ring
grows with the number of values: 112 px up to 4, 136 px up to 6, 160 px up to 8.

The values and their order come from **Overlay → Shown values**, the same list the compact bar and the
full panel use. Tick what you want and drag to reorder. If *Frametime graph* is ticked, a mini graph
of the last 40 frames appears under the FPS. The ring can show:

| Value | Arc full at | Colour |
|---|---|---|
| CPU / GPU temperature | 100 °C (empty at 30 °C) | green → orange (threshold − 8) → red (threshold) |
| Power | 160 W | purple |
| GPU clock | 2000 MHz | blue, red while throttling |
| GPU / CPU load | 100 % | blue |
| RAM / VRAM | total | green, orange above the RAM threshold |
| Fan | 2000 rpm | red if stopped |
| 1% low | current FPS | green, orange below 75 % of FPS |
| Frametime (ms) | 2× the target frame time | green near target, orange above |
| CPU clock | 3500 MHz | blue |

When any watched condition is active, an orange or red **halo** surrounds the ring. The ring uses the same
thresholds and *when everything is fine* setting as the bubble.

## Customising the look

**Overlay → Value style** applies to the ring, the compact bar and the full panel (and the bubble border):

| Option | Effect |
|---|---|
| Labels | small CPU / GPU / W… captions next to or under the numbers. Off = numbers only |
| Coloured border | a thin border in the main colour |
| Show the FPS limit | `⏵ 90` next to the FPS (`∞` with no limit) |
| Colours | *traffic light*: every value green/orange/red by status. *Monochrome*: values in white and arcs in the main colour; only warnings and problems stay orange/red |
| Main colour | blue, green, purple, white, coral or amber |

Together with size, opacity, position and margin, these settings go from a tiny, almost invisible ring
to a full benchmark panel. The preview at the top of the page updates live.

## Details panel (Shift+F2)

A 760×580 panel in the middle of the screen with:

- game name, API (Vulkan/OpenGL), profile, Steam app id, whether it is *linked* (started through
  `bc250-run`, with the active FSR upscaling), core/thread count;
- FPS limit badge (active, disabled, heat guard engaged);
- current FPS, 60 s average, 1% low, frametime graph of the last 120 frames;
- CPU, GPU, GPU clock and power graphs (last 60 s) with min/max;
- fan, GPU/CPU load, RAM, VRAM, governor range and throttle point;
- the **game profile editor**.

While the panel is open it takes the keyboard (like the Steam overlay):

| Key | Action |
|---|---|
| ↑ ↓ / W S / Tab | choose a field |
| ← → / A D | change its value (saved immediately, applied live) |
| Esc / Enter | close |

If the game has no profile yet, the first change creates one, matched by Steam app id or by executable name.

## Toasts

Short messages at the top centre of the screen: limit toggled (Shift+F1), overlay hidden, heat guard
changes and critical alerts. A critical alert is repeated on screen at most every 3 minutes.

## Shortcuts

| Keys | Command | Action |
|---|---|---|
| Shift+F1 | `bc250ctl toggle-limit` | FPS limit on/off (global) |
| Shift+F2 | `bc250ctl toggle-panel` | details panel |
| Shift+F3 | `bc250ctl toggle-hud` | overlay on/off |

Rebind them in **System Settings → Shortcuts → BC-250**.
