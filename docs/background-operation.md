# Running the bot while you use another app

Short answer: **yes, as long as the game is not minimized.** Leave Melvor 2
unminimized — behind your other windows, on a second monitor, or parked
off-screen. The bot can read it and click it while another application has
focus.

**Screen size does not matter.** The UI readers are calibrated for a 2560x1369
client area, so at startup the bot resizes the game window to exactly that
client size (restoring it first if it is maximized). On a smaller display the
window extends beyond the screen edge, which is fine: capture uses `PrintWindow`
and clicks are posted to the window, so both work off-screen. Minimizing is the
only thing that breaks it. The bot also re-applies the size every 30 seconds, so
changing resolution, scale, or monitor mid-run recovers automatically. The
details and the rules for new UI code are in [display.md](display.md).

## Verified behaviour (demo v0.11.4-alpha)

Measured on the live game on 2026-11-11:

| Game window state | Read (capture) | Act (click) | Simulation |
|---|---|---|---|
| Focused | works | works | runs |
| Covered / not focused | **works**, live pixels (mean 53.1) | **works** via posted messages | runs (GP +95, slayer +22 in 25 s) |
| Off-screen at `-2776, 0`, not minimized | **works**, live pixels (mean 42.4) | **works** | runs |
| Any client size | works; the bot resizes to 2560x1369 at startup | works | runs |
| Minimized | **black** (mean 0.0) | impossible (client `0x0`) | still runs |

What the minimized window looked like:

```
window=160x28 at (-32000,-32000)   client=0x0 at (-32000,-32000)
capture: 2560x1369 mean=0.0 extrema=(0, 0)
```

Windows gives a minimized window no composition surface, so `PrintWindow`
returns an empty frame and there is no client area to address. The game itself
keeps simulating (the save header kept advancing), the bot is just blind.

Clicks are posted as `WM_MOUSEMOVE` / `WM_LBUTTONDOWN` / `WM_LBUTTONUP` with
client coordinates, so they work regardless of z-order. Verified by opening the
Bank tab from the Combat page while another window stayed foreground
(`GetForegroundWindow` unchanged), then returning to Combat.

## Recommended setup

1. Launch the game and log in.
2. **Do not minimize it.** The bot restores it if maximized, then resizes the
   window to a 2560x1369 client at startup (on a smaller display it extends
   off-screen). Cover it with other windows, move it to another monitor, or
   leave it off-screen.
3. Run the bot. `doctor` reports the client size, primary display size and
   scale; the startup resize is logged.

Off-screen is the cleanest option when you want the window out of the way: it
stays rendered and fully capturable while invisible.

On a single monitor with a fullscreen game, run that game in **borderless
windowed** mode. Exclusive fullscreen can minimize or otherwise disturb the
desktop window; if that happens, Melvor must be restored.

## How the bot implements it

- Capture: `PrintWindow(hwnd, hdc, PW_RENDERFULLCONTENT)` — independent of
  z-order.
- Input: `[automation].background_input = true` (default) posts window
  messages; the real cursor never moves and focus is never stolen.
- Set `background_input = false` to fall back to pyautogui, which focuses the
  game first. Use that if a future build stops accepting posted input.

```toml
[automation]
background_input = true
```

```python
from mi2_aio.input import click_game

path = click_game(win, x, y, settings.automation)   # "background" / "foreground"
```

`background_click` refuses to run against a minimized window and raises
`InputBlocked` instead of clicking blind.

## Limits worth knowing

- **Coordinates are client-relative.** Re-read `find_game_window()` after any
  move/resize; a stale `WindowInfo` clicks the wrong place. Don't drag the game
  while a task is running.
- **Keyboard is different.** Posted mouse messages are verified; typed text and
  modifier-dependent hotkeys still need the foreground path (`press`,
  `hotkey`). Mouse-only tasks are safe in the background.
- **Simulation may slow down when unfocused.** Godot can throttle rendering for
  background windows. Progress continued in testing, but don't assume a
  one-to-one tick rate with a focused window.
- **Hover states need a `WM_MOUSEMOVE`.** `background_click` sends one before
  the button events; `background_move` exists for tooltip-driven UIs.
- **Black capture means minimized**, not broken. `python -m mi2_aio doctor`
  now flags it explicitly.

## Safety

`pyautogui`'s fail-safe is only active for the foreground path, because
background input does not move the physical cursor. For background runs use the
`STOP` file, `Ctrl+C`, and `--duration` / `max_runtime_minutes`. An off-screen
window also means a stray real click cannot land on the game by accident.
