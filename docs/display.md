# Display independence

**Rule: every feature must work on any monitor, resolution, aspect ratio and
display scale.** This page defines the invariant and the checklist new UI code
must follow. It is not optional and does not depend on the developer's screen.

## The invariant

The bot never reads or clicks using desktop/screen coordinates and never assumes
the game window matches the monitor.

```
PrintWindow capture ──► crop to client ──► normalize to 2560x1369 ──► readers
                                                          │
click target in 2560x1369 ──► to_client(client_size) ──► posted client click
```

Two reference-space coordinates exist for every element:

- **Readers** consume an image resized to `ui.REFERENCE_SIZE` (2560x1369).
- **Clicks** are defined in the same space and scaled with `ui.to_client(...)`
  into the live client area before they are posted.

Because both sides share one reference space, a window of any size behaves the
same. Templates are captured at the reference size, so they match normalized
captures on every machine.

## What the bot does automatically

| Situation | Handling |
|---|---|
| Any client size | Startup calls `ensure_reference_size`: the window is resized so its client area is exactly 2560x1369. |
| Small display (laptop, 1080p) | Windows allows an oversized window; it extends off-screen. `PrintWindow` still renders the full client and posted clicks still work. |
| Maximized window | Restored first (`ShowWindow(SW_RESTORE)`), then resized. A maximized window is clamped to the monitor work area, so leaving it maximized would break the readers on a small screen. |
| Display scale 125% / 150% / 200% | The process is per-monitor DPI aware (v2, with fallbacks), so Win32 client coordinates are physical pixels and match the captured pixels. |
| Multi-monitor / negative coordinates | Everything is client-relative; the window can sit at negative screen coordinates. |
| Resolution, scale or monitor changed mid-run | The runner re-checks the window every 30 seconds and re-applies the reference size if it drifted. |
| Aspect ratio | The window is forced to the reference aspect, so the game's UI scales uniformly. |
| Minimized | Unsupported by Windows (no composition surface). The bot reports it and refuses to act blind. |

`doctor` prints the primary display size and scale, the current client size, and
a note when the display is smaller than the reference.

## Rules for new features

1. **Never use screen/desktop coordinates.** Do not read the monitor size,
   `GetSystemMetrics(SM_CXSCREEN)`, `pyautogui.size()`, or the cursor position
   to place a click.
2. **Define regions and click points in `src/mi2_aio/ui.py`** as reference-space
   pixels, next to the existing ones, with a short comment.
3. **Readers always start from a normalized capture**:
   `image = ui.normalize(capture_client(ctx.window))`. Never measure a raw
   capture whose size can differ.
4. **Clicks always go through `ui.to_client`** (directly or via a task's
   `_click` helper). `to_client` clamps to the client rectangle, so edge points
   cannot land one pixel outside.
5. **Templates are captured at the reference size** and matched against
   normalized images. A template captured at another size will only match that
   size.
6. **Do not hardcode offsets from the window origin.** Use client coordinates;
   the window may be off-screen or on another monitor.
7. **Do not require maximized or a specific resolution.** If a layout genuinely
   needs more space, resize to the reference rather than changing the reference.
8. **If a feature needs a new reference size**, that is a project-wide change:
   update `ui.REFERENCE_SIZE`, re-capture every template and region, and update
   this document. Never introduce a second reference space.
9. **Test at more than one size.** `tests/test_display.py` pins normalization,
   scaling, clamping, layout tolerance and the maximize/restore path; extend it
   when you add geometry code.

## Why the reference is 2560x1369

It is the client area of the maximized game window on the development machine,
so all regions and templates were calibrated from real screenshots at that size.
Nothing depends on that monitor: the bot forces this client size everywhere
else.

## Verification record

| Display / window | Result |
|---|---|
| 2560x1440 monitor, maximized (2560x1369 client) | baseline |
| 1904x1041 client | resize + readers + clicks verified |
| 2994x1561 client | resize + readers + clicks verified |
| 1264x681 client at startup | resized to 2560x1369, dungeon navigation verified live |
| Shrunk to 1184x661 mid-run | re-applied at the 30 s check, run continued |
| Off-screen at negative coordinates | capture and clicks verified |
| Maximized on a smaller work area | restored and resized (unit-tested; see `tests/test_display.py`) |

## Caveats

- **Minimized is impossible**, not merely difficult: Windows returns a black
  frame and there is no client area. Leave the game covered or off-screen.
- **Exclusive fullscreen** can minimize or disturb the window. Run other games
  in borderless windowed mode while the bot works.
- **The game must allow resizing.** The demo build does. If a future build
  enforces a maximum window size, `layout_ready` will refuse to run with a clear
  message instead of clicking the wrong place.
- **Non-uniform UI scaling** (for example the game stretching only one axis)
  would break template matching. The forced reference aspect prevents it.
