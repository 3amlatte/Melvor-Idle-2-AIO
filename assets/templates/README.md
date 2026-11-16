# UI templates

Drop small PNG crops here (buttons, icons, bar segments) taken from a client-area
capture:

```powershell
python -m mi2_aio capture --client -o logs/calibration.png
```

Rules that keep matching reliable:

- Crop only the distinctive part of a control, not the whole panel.
- Avoid areas that animate, show numbers, or change color with state.
- Capture at the same window size you will run with; `vision.find_template`
  handles ±5% scale, not arbitrary resizing.
- Name templates for what they mean, e.g. `btn_jump_to_enemy.png`,
  `icon_fishing.png`, `dialog_continue.png`.

Use them from a task:

```python
from mi2_aio import vision

match = vision.find_template(
    image,
    vision.load_template("assets/templates/btn_jump_to_enemy.png"),
    threshold=0.88,
)
if match:
    print(match.center, match.score)
```
