# src/docket/ai/transcripts/guard.py
"""Hallucination guard: every quoted excerpt must be found in the text the model saw.

Both sides are normalized the same way before matching (spec Section 3,
"Hallucination guard"); a fuzzy window pass catches what the normalizer
misses, such as a stray space inside a word from the PDF extractor. The
offsets returned point into the ORIGINAL source so callers can compute
`char_offset`, pages, and segment positions.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

_QUOTES = {"‘": "'", "’": "'", "‚": "'", "“": '"', "”": '"', "„": '"',
           "′": "'", "″": '"'}
_SOFT_HYPHEN = "­"


def normalize_with_map(s: str) -> tuple[str, list[int]]:
    out: list[str] = []
    idx: list[int] = []
    i, n = 0, len(s)
    pending_space = False
    while i < n:
        ch = s[i]
        if ch == _SOFT_HYPHEN:
            i += 1
            continue
        # "ap-\nproved", "ap- \nproved", "ap-\n proved" -> "approved": a hyphen followed by
        # optional spaces and a line break joins the word (pdfplumber emits all three).
        if ch == "-":
            j = i + 1
            while j < n and s[j] in " \t":
                j += 1
            if j < n and s[j] in "\r\n":
                i = j
                while i < n and s[i] in " \t\r\n":
                    i += 1
                continue
        if ch.isspace():
            pending_space = True
            i += 1
            continue
        if pending_space and out:
            out.append(" ")
            idx.append(i)
            pending_space = False
        elif pending_space:
            pending_space = False
        ch = _QUOTES.get(ch, ch)
        # NFKD so compatibility forms still fold ("ﬁ" -> "fi") and accents become separate combining
        # marks, which are then dropped: "Peña" and "Peña" (a model may emit either) both match "pena".
        for c in unicodedata.normalize("NFKD", ch).lower():
            if unicodedata.combining(c):
                continue
            out.append(c)
            idx.append(i)
        i += 1
    return "".join(out), idx


def normalize(s: str) -> str:
    return normalize_with_map(s)[0]


@dataclass(frozen=True)
class CitationMatch:
    kind: Literal["exact", "fuzzy", "missing"]
    start: int | None
    end: int | None
    ratio: float


MISSING = CitationMatch("missing", None, None, 0.0)
MAX_FUZZY_ANCHORS = 50


def find_citation(excerpt: str, source: str, *, fuzzy_threshold: float = 0.92) -> CitationMatch:
    ne = normalize(excerpt)
    if not ne:
        return MISSING
    ns, m = normalize_with_map(source)
    pos = ns.find(ne)
    if pos >= 0:
        return CitationMatch("exact", m[pos], m[pos + len(ne) - 1] + 1, 1.0)
    # Fuzzy pass, anchored: never a full sweep of the source. An anchor is an exact
    # hit of any three-word shingle of the excerpt; windows are tried only where the
    # excerpt would sit around each anchor. A quote with no three consecutive words
    # intact anywhere in the source is reported missing. Cost is O(anchors), not
    # O(len(source)), so a 300-page minutes text costs the same as a short one.
    words = ne.split(" ")
    anchors: set[int] = set()
    for k in range(max(1, len(words) - 2)):
        shingle = " ".join(words[k:k + 3])
        if len(shingle) < 8:
            continue
        off = ne.find(shingle)
        pos = ns.find(shingle)
        while pos >= 0 and len(anchors) < MAX_FUZZY_ANCHORS:
            anchors.add(max(0, pos - off))
            pos = ns.find(shingle, pos + 1)
    wlen = int(len(ne) * 1.15) + 4
    best, best_span = 0.0, (0, 0)
    for a in sorted(anchors):
        for start in range(max(0, a - 8), min(a + 9, len(ns)), 4):
            seg = ns[start:start + wlen]
            blocks = [b for b in SequenceMatcher(None, ne, seg, autojunk=False).get_matching_blocks() if b.size]
            if not blocks:
                continue
            # Tighten to the matched blocks so slack text around the quote (the window
            # is deliberately generous) does not drag the ratio down, and so the
            # offsets hug the quote.
            lo = start + blocks[0].b
            hi = start + blocks[-1].b + blocks[-1].size
            r = SequenceMatcher(None, ne, ns[lo:hi], autojunk=False).ratio()
            if r > best:
                best, best_span = r, (lo, hi)
    if best < fuzzy_threshold:
        return MISSING
    lo, hi = best_span
    return CitationMatch("fuzzy", m[lo], m[hi - 1] + 1, best)


_NUM_WORDS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
              "seven": "7", "eight": "8", "nine": "9", "ten": "10", "eleven": "11", "twelve": "12",
              "thirteen": "13", "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
              "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30", "forty": "40",
              "fifty": "50", "sixty": "60", "seventy": "70", "eighty": "80", "ninety": "90"}
_TENS = {"twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"}


def canonical_statute(s: str) -> str:
    """Comparable form for a statute cite, spoken or written."""
    words = re.findall(r"[a-z]+|\d+", normalize(s))
    out: list[str] = []
    i = 0
    while i < len(words):
        w = words[i]
        if w in _TENS and i + 1 < len(words) and words[i + 1] in _NUM_WORDS and len(_NUM_WORDS[words[i + 1]]) == 1:
            out.append(str(int(_NUM_WORDS[w]) + int(_NUM_WORDS[words[i + 1]])))
            i += 2
            continue
        out.append(_NUM_WORDS.get(w, w))
        i += 1
    return "".join(out)


def window(source: str, start: int, end: int, radius: int) -> str:
    return source[max(0, start - radius):min(len(source), end + radius)]
