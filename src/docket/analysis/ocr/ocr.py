"""OCR helpers for Birmingham vote-display frames.

Two public functions:
- ``extract_vote_text(frame)`` returns the full white-on-black text of a
  vote frame (header + names) for logging and debugging.
- ``extract_counts(frame)`` returns ``{yeas, nays, abstentions}`` read
  cleanly from the three colored count boxes. This is the signal the
  terminal-frame pipeline consumes.

Member-level dot sampling used to live here under fixed-coordinate
layouts; it has moved to ``vote_layout.detect_member_rows`` which works
spatially and survives name reflow when members are absent.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytesseract
from PIL import Image

# --- Tuning constants ------------------------------------------------------

# Vertical band of the frame (as a fraction of height) where vote count boxes
# live. Birmingham renders them just under the header, around 22-42% from
# the top. The band is kept tight on purpose — a looser crop pulls in dots
# from the name list and breaks box detection.
COUNT_BAND_TOP = 0.22
COUNT_BAND_BOTTOM = 0.42

# Minimum count-box side as a fraction of band height. Real count boxes
# fill most of the band height; tiny blobs are OCR specks / noise.
COUNT_BOX_MIN_SIDE_FRACTION = 0.3
# Minimum chromatic spread (max-min BGR channel) for a blob to count as a
# colored box rather than grayscale text.
COUNT_BOX_MIN_CHROMATIC_SPREAD = 30
# Fractional inner padding applied before OCR'ing the digit inside a box.
# A tight pad lets saturated edge pixels leak into the digit image.
COUNT_BOX_INNER_PAD_FRACTION = 0.12

# Saturation threshold to consider a pixel "colored" when looking for boxes
# vs "white" when isolating text on the colored background.
COLOR_SAT_THRESHOLD = 40
TEXT_SAT_THRESHOLD = 50
TEXT_VALUE_THRESHOLD = 30

# Minimum bounding-box dimension (in pixels) to count as a vote count box.
MIN_BOX_SIZE = 40

# OCR upscale factor for the count digits — Tesseract reads small digits poorly.
DIGIT_UPSCALE = 8


# --- Vote frame text OCR ---------------------------------------------------


def extract_vote_text(frame: np.ndarray) -> str:
    """Return the white-on-black text (header + names) from a vote frame.

    Used only for debug logging — the terminal-frame pipeline reads
    counts via ``extract_counts`` and members via
    ``vote_layout.detect_member_rows``, so this output is no longer
    machine-consumed.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

    _, white_text = cv2.threshold(gray, 180, 255, cv2.THRESH_BINARY)
    full_color_mask = (hsv[:, :, 1] > TEXT_SAT_THRESHOLD) & (hsv[:, :, 2] > TEXT_VALUE_THRESHOLD)
    white_text[full_color_mask] = 0
    inverted = cv2.bitwise_not(white_text)
    return pytesseract.image_to_string(Image.fromarray(inverted), config="--psm 6")


def _read_count_boxes(frame: np.ndarray, frame_height: int) -> list[dict]:
    """Locate the colored count boxes and OCR their digits.

    Returns a list of ``{x, color, digit}`` dicts sorted left-to-right.

    Selection rules:
    - box side ≥ ``COUNT_BOX_MIN_SIDE_FRACTION`` of band height
    - chromatic spread ≥ ``COUNT_BOX_MIN_CHROMATIC_SPREAD`` (rejects
      grayscale text blobs even when they cross the saturation floor)
    """
    y_start = int(frame_height * COUNT_BAND_TOP)
    y_end = int(frame_height * COUNT_BAND_BOTTOM)
    count_band = frame[y_start:y_end, :]
    band_height = count_band.shape[0]
    count_hsv = cv2.cvtColor(count_band, cv2.COLOR_BGR2HSV)

    sat_mask = (count_hsv[:, :, 1] > COLOR_SAT_THRESHOLD).astype(np.uint8) * 255
    contours, _ = cv2.findContours(sat_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    min_side = max(MIN_BOX_SIZE, int(band_height * COUNT_BOX_MIN_SIDE_FRACTION))

    boxes: list[dict] = []
    for contour in contours:
        x, y_rel, cw, ch = cv2.boundingRect(contour)
        if cw < min_side or ch < min_side:
            continue
        y_abs = y_rel + y_start
        box_roi = frame[y_abs : y_abs + ch, x : x + cw]
        avg_b = float(np.mean(box_roi[:, :, 0]))
        avg_g = float(np.mean(box_roi[:, :, 1]))
        avg_r = float(np.mean(box_roi[:, :, 2]))
        spread = max(avg_r, avg_g, avg_b) - min(avg_r, avg_g, avg_b)
        if spread < COUNT_BOX_MIN_CHROMATIC_SPREAD:
            continue

        color = _classify_box_color(box_roi)
        digit = _ocr_digit_in_box(frame, x, y_abs, cw, ch)
        boxes.append({"x": x, "color": color, "digit": digit})

    boxes.sort(key=lambda b: b["x"])
    return boxes


def extract_counts(frame: np.ndarray) -> dict[str, int | None]:
    """Return ``{"yeas": int|None, "nays": int|None, "abstentions": int|None}``.

    Each count is read from its own color-classified box, so a bad OCR
    on one box doesn't corrupt the others. Unreadable digits become
    ``None`` — never a silent zero.
    """
    h = frame.shape[0]
    boxes = _read_count_boxes(frame, h)

    # Keep only the largest box per color (in case spurious blobs slipped
    # through the filters), then read each digit into a dict.
    by_color: dict[str, str] = {}
    for box in boxes:
        color = box["color"]
        if color in ("yes", "no", "abstain") and color not in by_color:
            by_color[color] = box["digit"]

    def _parse(raw: str | None) -> int | None:
        if not raw:
            return None
        # Keep digits only; "Q"/"O" → we don't guess, we return None.
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            return None
        value = int(digits)
        return value if 0 <= value <= 20 else None

    return {
        "yeas": _parse(by_color.get("yes")),
        "nays": _parse(by_color.get("no")),
        "abstentions": _parse(by_color.get("abstain")),
    }


def _classify_box_color(box_bgr: np.ndarray) -> str:
    """Classify a count box as red/green/blue based on average BGR.

    Hue-based classification is unreliable because of MPEG color smearing;
    averaging the BGR channels and taking the dominant one is more robust.
    """
    avg_b = float(np.mean(box_bgr[:, :, 0]))
    avg_g = float(np.mean(box_bgr[:, :, 1]))
    avg_r = float(np.mean(box_bgr[:, :, 2]))

    if avg_r > avg_g and avg_r > avg_b:
        # Yellow/green can also be red-dominant; disambiguate by green level.
        return "no" if avg_g < 100 else "yes"
    if avg_g > avg_r and avg_g > avg_b:
        return "yes"
    if avg_b > avg_r and avg_b > avg_g:
        return "abstain"
    return "unknown"


def _ocr_digit_in_box(frame: np.ndarray, x: int, y_abs: int, cw: int, ch: int) -> str:
    """Read a single digit out of a count box.

    Strategy: white text sits on a saturated background, so the inverted
    saturation channel isolates the text. Threshold + upscale + Tesseract
    with a digit whitelist.

    The inner pad is proportional (``COUNT_BOX_INNER_PAD_FRACTION``) so
    that saturated edge pixels on high-resolution frames don't leak into
    the digit image — a hard-coded 2-pixel pad is too tight on 1820p.
    """
    pad = max(2, int(min(cw, ch) * COUNT_BOX_INNER_PAD_FRACTION))
    box_roi = frame[y_abs + pad : y_abs + ch - pad, x + pad : x + cw - pad]
    if box_roi.size == 0:
        return ""

    roi_hsv = cv2.cvtColor(box_roi, cv2.COLOR_BGR2HSV)
    sat_inv = cv2.bitwise_not(roi_hsv[:, :, 1])
    _, sat_t = cv2.threshold(sat_inv, 200, 255, cv2.THRESH_BINARY)
    upscaled = cv2.resize(
        sat_t,
        (sat_t.shape[1] * DIGIT_UPSCALE, sat_t.shape[0] * DIGIT_UPSCALE),
        interpolation=cv2.INTER_CUBIC,
    )
    digit_img = cv2.bitwise_not(upscaled)  # black text on white for Tesseract

    # Try PSM 8 (single word) first — it handles the Birmingham count
    # font better than PSM 10 (single character), which returns empty
    # for stylized digits. Fall through if it returns nothing.
    for psm in (8, 13, 10):
        result = pytesseract.image_to_string(
            Image.fromarray(digit_img),
            config=f"--psm {psm} -c tessedit_char_whitelist=0123456789",
        ).strip()
        if result:
            return result
    return ""
