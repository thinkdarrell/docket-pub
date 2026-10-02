"""Recognize the agenda line by which a council adopts earlier minutes.

Single definition of that shape, shared by the agenda PDF parser (which must
keep the line at ingest) and the adoption sweep (which acts on it).
"""

from __future__ import annotations

import re

# Month names as the clerk writes them: full, or abbreviated ("Nov.", "Sept").
MONTH_PATTERN = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?"
    r"|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)

# The title must open with the approval: "Approval of Minutes from ...",
# "Adoption of the Minutes ...", "Approval of the December 5, 2024 Minutes",
# "APPROVAL OF PREVIOUS MINUTES: ...", and the clerk's occasional "APPROVAL
# MINUTES FROM ...". A resolution that merely mentions adopting something, and
# "MINUTES NOT READY: ...", do not match.
_ADOPTION_TITLE_PATTERNS = [
    re.compile(
        r"^\s*(?:approval|adoption)\s+(?:of\s+)?(?:the\s+)?(?:\S+\s+){0,4}?minutes\b",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*minutes from the (?:\w+\s+)?meeting of\b", re.IGNORECASE),
]


def is_adoption_title(title: str) -> bool:
    """True if the title matches any adoption pattern."""
    if not title:
        return False
    return any(p.search(title) for p in _ADOPTION_TITLE_PATTERNS)
