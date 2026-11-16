from __future__ import annotations

import numpy as np
from PIL import Image

from mi2_aio.ui import STANCE_BUTTONS, TEMPLATE_DIR, stance_button


def test_stance_templates_exist_and_are_binary() -> None:
    for name in ("slash", "block", "crush"):
        path = TEMPLATE_DIR / f"stance_{name}.png"
        assert path.exists(), f"missing {path}"
        image = Image.open(path).convert("L")
        values = set(np.unique(np.asarray(image)).tolist())
        assert values <= {0, 255}
        assert 255 in values


def test_stance_button_positions_and_clamping() -> None:
    assert stance_button(0) == STANCE_BUTTONS[0]
    assert stance_button(1) == STANCE_BUTTONS[1]
    assert stance_button(2) == STANCE_BUTTONS[2]
    assert stance_button(99) == STANCE_BUTTONS[-1]
    assert stance_button(-1) == STANCE_BUTTONS[0]
