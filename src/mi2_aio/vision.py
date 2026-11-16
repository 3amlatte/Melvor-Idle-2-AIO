"""Template-matching helpers for reading the game's canvas UI.

Godot renders the UI into the window, so there is no accessibility tree to
query. Templates are PNG crops taken from `python -m mi2_aio capture`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Match:
    x: int
    y: int
    width: int
    height: int
    score: float
    scale: float

    @property
    def center(self) -> tuple[int, int]:
        return self.x + self.width // 2, self.y + self.height // 2


def _to_bgr(image: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)


def load_template(path: str | Path) -> Image.Image:
    return Image.open(path).convert("RGB")


def find_template(
    image: Image.Image,
    template: Image.Image,
    *,
    threshold: float = 0.85,
    region: tuple[int, int, int, int] | None = None,
    scales: tuple[float, ...] = (1.0, 0.95, 1.05),
) -> Match | None:
    """Find the best match of ``template`` in ``image``.

    ``region`` is (left, top, width, height) in client coordinates.
    Returns None when the best score is below ``threshold``.
    """
    haystack = _to_bgr(image)
    left = top = 0
    if region is not None:
        rx, ry, rw, rh = region
        haystack = haystack[ry : ry + rh, rx : rx + rw]
        left, top = rx, ry

    best: Match | None = None
    for scale in scales:
        if scale <= 0:
            continue
        scaled = template
        if scale != 1.0:
            size = (
                max(1, round(template.width * scale)),
                max(1, round(template.height * scale)),
            )
            scaled = template.resize(size, Image.Resampling.LANCZOS)

        needle = _to_bgr(scaled)
        if needle.shape[0] > haystack.shape[0] or needle.shape[1] > haystack.shape[1]:
            continue

        result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
        _min_val, max_val, _min_loc, max_loc = cv2.minMaxLoc(result)
        if best is None or max_val > best.score:
            best = Match(
                x=left + int(max_loc[0]),
                y=top + int(max_loc[1]),
                width=needle.shape[1],
                height=needle.shape[0],
                score=float(max_val),
                scale=scale,
            )

    if best is None or best.score < threshold:
        return None
    return best


def find_all(
    image: Image.Image,
    template: Image.Image,
    *,
    threshold: float = 0.85,
    region: tuple[int, int, int, int] | None = None,
    min_distance: int = 12,
) -> list[Match]:
    """Find every match above the threshold, with simple distance dedupe."""
    haystack = _to_bgr(image)
    left = top = 0
    if region is not None:
        rx, ry, rw, rh = region
        haystack = haystack[ry : ry + rh, rx : rx + rw]
        left, top = rx, ry

    needle = _to_bgr(template)
    if needle.shape[0] > haystack.shape[0] or needle.shape[1] > haystack.shape[1]:
        return []

    result = cv2.matchTemplate(haystack, needle, cv2.TM_CCOEFF_NORMED)
    ys, xs = np.where(result >= threshold)
    matches: list[Match] = []
    for x, y in sorted(zip(xs.tolist(), ys.tolist()), key=lambda p: -result[p[1], p[0]]):
        score = float(result[y, x])
        if any(
            abs((left + x) - m.x) < min_distance
            and abs((top + y) - m.y) < min_distance
            for m in matches
        ):
            continue
        matches.append(
            Match(
                x=left + int(x),
                y=top + int(y),
                width=needle.shape[1],
                height=needle.shape[0],
                score=score,
                scale=1.0,
            )
        )
    return matches


def mean_brightness(image: Image.Image) -> float:
    """Rough sanity check; near-zero means the capture is black."""
    grayscale = np.asarray(image.convert("L"), dtype=np.float32)
    return float(grayscale.mean())
