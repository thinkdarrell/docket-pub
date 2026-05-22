"""Classify a video frame as either a "vote display" frame or normal footage.

Vote frames have a distinctive four-signal signature:

1. Most of the frame is near-black (the vote screen background).
2. The "Yes" count box contributes a saturated green pixel cluster.
3. The "No" count box contributes a saturated red pixel cluster.
4. The "Abstain" count box contributes a saturated blue pixel cluster.

All three colored boxes are rendered on every vote frame regardless of the
tally — even a "0" count still shows the box — so any frame missing one of
the clusters is not a vote screen. This check is count-independent,
resolution-independent (the minimum pixel counts scale with frame area),
and cheap: HSV conversion happens once and all four signals are derived
from downsampled masks.
"""

from __future__ import annotations

import cv2
import numpy as np

# --- Tuning constants ------------------------------------------------------

# Grayscale value below which a pixel counts as "black".
BLACK_THRESHOLD = 40
# Fraction of pixels that must be "black" for the frame to pass the prefilter.
BLACK_RATIO = 0.55

# Downsample target (short edge) before computing masks. Keeps the classifier
# cheap at coarse-pass fps without changing the signature.
DOWNSAMPLE_SHORT_EDGE = 480

# Saturation / value floors a pixel must clear to count toward a color cluster.
# A near-black or near-white pixel has low saturation and will not register.
COLOR_SAT_MIN = 120
COLOR_VAL_MIN = 80

# Hue ranges (OpenCV HSV: H in 0..179) for each count-box color.
GREEN_HUE = (40, 85)
RED_HUE_LOW = (0, 10)
RED_HUE_HIGH = (170, 179)
BLUE_HUE = (95, 130)

# Minimum pixels per cluster (at 480p reference) to count as "present".
# Scales linearly with downsampled frame area so it's resolution-independent.
MIN_COLOR_PIXELS_REF = 200
REF_FRAME_AREA = 480 * 854  # reference 480p 16:9 area


def is_vote_frame(
    frame: np.ndarray,
    black_threshold: int = BLACK_THRESHOLD,
    black_ratio: float = BLACK_RATIO,
) -> bool:
    """Return True if the frame matches the four-signal vote-screen signature."""
    small = _downsample(frame)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    # Signal 1: black dominance prefilter.
    black_pixels = int(np.sum(gray < black_threshold))
    if (black_pixels / gray.size) <= black_ratio:
        return False

    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    saturated = (s > COLOR_SAT_MIN) & (v > COLOR_VAL_MIN)

    area = small.shape[0] * small.shape[1]
    min_pixels = max(1, int(MIN_COLOR_PIXELS_REF * area / REF_FRAME_AREA))

    # Signal 2: green cluster.
    if int(np.sum(saturated & _hue_mask(h, GREEN_HUE))) < min_pixels:
        return False

    # Signal 3: red cluster (wraps around hue 0, so two ranges OR'd).
    red_mask = _hue_mask(h, RED_HUE_LOW) | _hue_mask(h, RED_HUE_HIGH)
    if int(np.sum(saturated & red_mask)) < min_pixels:
        return False

    # Signal 4: blue cluster.
    return int(np.sum(saturated & _hue_mask(h, BLUE_HUE))) >= min_pixels


def _downsample(frame: np.ndarray) -> np.ndarray:
    """Resize so the short edge is DOWNSAMPLE_SHORT_EDGE; leave smaller frames alone."""
    h, w = frame.shape[:2]
    short = min(h, w)
    if short <= DOWNSAMPLE_SHORT_EDGE:
        return frame
    scale = DOWNSAMPLE_SHORT_EDGE / short
    new_w = int(round(w * scale))
    new_h = int(round(h * scale))
    return cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _hue_mask(hue: np.ndarray, bounds: tuple[int, int]) -> np.ndarray:
    lo, hi = bounds
    return (hue >= lo) & (hue <= hi)
