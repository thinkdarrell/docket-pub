"""Spatial name → dot association for Birmingham vote frames.

Replaces the old fixed-coordinate dot sampler. Because Birmingham's vote
screen reflows names upward when a member is absent, we cannot hard-code
``(x, y)`` per member. Instead:

1. OCR the names band with ``pytesseract.image_to_data`` to get per-word
   bounding boxes, then stitch adjacent words back into full names.
2. Find the colored indicator dots by saturation + chromatic-spread
   filtering (real dots are saturated AND not gray; OCR-era text blobs
   are gray and get rejected even when "saturated").
3. For each OCR'd name, pick the dot on the same horizontal row and on
   the same column side (names in the left column pair with left-column
   dots; right column with right-column dots).
4. Fuzzy-match the OCR'd name to a canonical roster name so the output
   is keyed by the exact string the rest of the pipeline persists.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

import cv2
import numpy as np
import pytesseract
from PIL import Image

# CouncilLayout + LayoutRow live in docket.analysis.ocr.rosters.
# Re-imported here so the existing matcher imports
# (from docket.analysis.ocr.layout import CouncilLayout) keep working.
from docket.analysis.ocr.rosters import CouncilLayout, LayoutRow  # noqa: F401


# --- Tuning constants ------------------------------------------------------

# Vertical fraction of the frame occupied by the two-column names band.
# Everything above this is header + count boxes; everything below is page
# chrome / ticker.
NAMES_BAND_TOP = 0.45
NAMES_BAND_BOTTOM = 0.97

# Dot detection: a real indicator dot is saturated AND chromatically
# distinct (max BGR channel much larger than min BGR channel). OCR text
# pixels can be "saturated" in HSV terms at certain thresholds but they
# are nearly grayscale so the chromatic-spread gate rejects them.
DOT_SAT_THRESHOLD = 120
DOT_MIN_SIDE_FRACTION = 0.02  # ≥2% of band height — dots are ~8-12% tall
DOT_MIN_CHROMATIC_SPREAD = 25

# Erosion kernel (in pixels) used to break thin connections between
# dots that appear stacked in the same column. Without this, the raw
# saturation mask merges a column of dots into one tall contour when
# anti-aliased pixels link them vertically. Tuned on 1080p+ frames.
DOT_EROSION_KERNEL = 15

# Rows are considered the "same row" if their centroids are within this
# fraction of band height. Tuned on 1080p+ Birmingham output.
ROW_Y_TOLERANCE_FRACTION = 0.04

# Column split: any word with centroid x below this fraction of band
# width is in the left column, otherwise the right column. Birmingham
# renders the split almost exactly at 50%, but we give it a small bias
# toward the right to keep short left-column names from drifting over.
COLUMN_SPLIT_FRACTION = 0.52

# Fuzzy-match threshold for associating OCR'd names with roster entries.
NAME_MATCH_MIN_RATIO = 0.6


@dataclass(frozen=True)
class _Dot:
    x: int  # centroid x (band-local)
    y: int  # centroid y (band-local)
    color: str  # "yes" | "no" | "abstain"


@dataclass(frozen=True)
class _NameBox:
    text: str
    x: int  # left edge (band-local)
    y: int  # centroid y (band-local)
    right: int  # right edge
    column: str  # "left" | "right"


def detect_member_rows(
    frame: np.ndarray,
    layout: CouncilLayout,
) -> dict[str, str]:
    """Return ``{canonical_name: position}`` for every member shown on ``frame``.

    Members not rendered on the frame (absent, not-yet-voted) are simply
    omitted from the result — the caller uses the keys present to decide
    who voted.
    """
    h, w = frame.shape[:2]
    if h < 200 or w < 400:
        return {}

    y_start = int(h * NAMES_BAND_TOP)
    y_end = int(h * NAMES_BAND_BOTTOM)
    band = frame[y_start:y_end, :]

    dots = _find_dots(band)
    if not dots:
        return {}

    names = _find_name_boxes(band)
    if not names:
        return {}

    canonical_names = _canonical_names_from_layout(layout)

    result: dict[str, str] = {}
    for name in names:
        canonical = _fuzzy_match_name(name.text, canonical_names)
        if canonical is None or canonical in result:
            continue
        dot = _nearest_dot_on_row(name, dots, band_height=band.shape[0])
        if dot is None:
            continue
        result[canonical] = dot.color

    return result


# --- Dot detection ---------------------------------------------------------


def _find_dots(band: np.ndarray) -> list[_Dot]:
    bh = band.shape[0]
    hsv = cv2.cvtColor(band, cv2.COLOR_BGR2HSV)
    sat_mask = (hsv[:, :, 1] > DOT_SAT_THRESHOLD).astype(np.uint8) * 255

    # Erode to break thin vertical connections between stacked dots.
    # Without this, a single column of dots can collapse into one long
    # contour because anti-aliased pixels link them.
    kernel = np.ones((DOT_EROSION_KERNEL, DOT_EROSION_KERNEL), np.uint8)
    eroded = cv2.erode(sat_mask, kernel, iterations=1)

    contours, _ = cv2.findContours(eroded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    min_side = max(10, int(bh * DOT_MIN_SIDE_FRACTION))

    dots: list[_Dot] = []
    for contour in contours:
        x, y, cw, ch = cv2.boundingRect(contour)
        if cw < min_side or ch < min_side:
            continue

        roi = band[y : y + ch, x : x + cw]
        avg_b = float(np.mean(roi[:, :, 0]))
        avg_g = float(np.mean(roi[:, :, 1]))
        avg_r = float(np.mean(roi[:, :, 2]))

        # Chromatic spread: dots are green/red/blue, not gray.
        spread = max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)
        if spread < DOT_MIN_CHROMATIC_SPREAD:
            continue

        color = _classify_dot(avg_b, avg_g, avg_r)
        if color is None:
            continue

        dots.append(_Dot(x=x + cw // 2, y=y + ch // 2, color=color))

    return dots


def _classify_dot(avg_b: float, avg_g: float, avg_r: float) -> str | None:
    """Pick yes/no/abstain from dominant BGR channel, matching the count-box rule."""
    if avg_g > avg_r and avg_g > avg_b:
        return "yes"
    if avg_r > avg_g and avg_r > avg_b:
        return "no"
    if avg_b > avg_r and avg_b > avg_g:
        return "abstain"
    return None


# --- Name box detection ----------------------------------------------------


def _find_name_boxes(band: np.ndarray) -> list[_NameBox]:
    bw = band.shape[1]
    gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    _, white = cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)
    inverted = cv2.bitwise_not(white)

    data = pytesseract.image_to_data(
        Image.fromarray(inverted),
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )

    # Stitch per-word output back into "X. Lastname" tokens by grouping
    # words that share a (block_num, par_num, line_num).
    words_per_line: dict[tuple[int, int, int], list[dict]] = {}
    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        if not text:
            continue
        try:
            conf = float(data["conf"][i])
        except (ValueError, TypeError):
            conf = -1.0
        if conf < 30:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        words_per_line.setdefault(key, []).append(
            {
                "text": text,
                "x": int(data["left"][i]),
                "y": int(data["top"][i]),
                "w": int(data["width"][i]),
                "h": int(data["height"][i]),
            }
        )

    split_x = int(bw * COLUMN_SPLIT_FRACTION)
    name_boxes: list[_NameBox] = []

    for words in words_per_line.values():
        words.sort(key=lambda w: w["x"])
        # Split a line into left-column and right-column halves, then
        # treat each half as an independent name candidate.
        left_half = [w for w in words if w["x"] + w["w"] // 2 < split_x]
        right_half = [w for w in words if w["x"] + w["w"] // 2 >= split_x]
        for half, col_label in ((left_half, "left"), (right_half, "right")):
            box = _build_name_from_words(half, col_label)
            if box is not None:
                name_boxes.append(box)

    return name_boxes


def _build_name_from_words(words: list[dict], column: str) -> _NameBox | None:
    if not words:
        return None

    # A Birmingham name is "<Initial>. <Lastname>". Require the first
    # token to look like a single-letter initial.
    first = words[0]["text"].rstrip(".")
    if len(first) != 1 or not first.isalpha():
        return None
    if len(words) < 2:
        return None

    text_parts = [first + "."]
    for w in words[1:]:
        cleaned = w["text"].rstrip(".").strip()
        if cleaned:
            text_parts.append(cleaned)
    text = " ".join(text_parts)

    x_left = min(w["x"] for w in words)
    x_right = max(w["x"] + w["w"] for w in words)
    y_center = int(sum(w["y"] + w["h"] // 2 for w in words) / len(words))

    return _NameBox(text=text, x=x_left, y=y_center, right=x_right, column=column)


# --- Spatial association ---------------------------------------------------


def _nearest_dot_on_row(
    name: _NameBox, dots: list[_Dot], band_height: int
) -> _Dot | None:
    y_tol = max(10, int(band_height * ROW_Y_TOLERANCE_FRACTION))

    candidates = [d for d in dots if abs(d.y - name.y) <= y_tol and d.x > name.right]
    if not candidates:
        return None

    # If the name is in the left column, prefer the dot closest to the
    # right edge of the name text (which is the left-column dot column).
    # If in the right column, likewise — the right-column dot lives just
    # past the right-column name's right edge.
    return min(candidates, key=lambda d: d.x - name.right)


# --- Name fuzzy matching ---------------------------------------------------


def _canonical_names_from_layout(layout: CouncilLayout) -> list[str]:
    names: list[str] = []
    for row in layout.rows:
        if row.left:
            names.append(row.left)
        if row.right:
            names.append(row.right)
    return names


def _normalize_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if ch.isalnum())


def _fuzzy_match_name(ocr_text: str, canonical: list[str]) -> str | None:
    norm_ocr = _normalize_name(ocr_text)
    if not norm_ocr:
        return None

    best_name: str | None = None
    best_ratio = 0.0
    for name in canonical:
        ratio = SequenceMatcher(None, norm_ocr, _normalize_name(name)).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = name

    if best_ratio < NAME_MATCH_MIN_RATIO:
        return None
    return best_name
