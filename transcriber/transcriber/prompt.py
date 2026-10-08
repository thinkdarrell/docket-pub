"""Build Whisper's initial prompt from the meeting roster plus local vocabulary.

Whisper keeps only the LAST 224 tokens of the initial prompt, so an
overflow silently drops the start. We size by characters with a
conservative ceiling (600 chars is comfortably under 224 BPE tokens for
English names) and refuse to build a prompt that would overflow rather
than let truncation happen quietly. Roster names matter more than the
fixed vocabulary, so vocabulary is trimmed first.
"""
from __future__ import annotations

LOCAL_VOCABULARY: tuple[str, ...] = (
    "ALEA", "CJI", "APC", "Alabama Power", "BJCC", "Woodlawn", "Ensley",
    "Avondale", "Pratt City", "Norwood", "Smithfield", "Titusville", "ADECA",
    "ALDOT", "BJCTA", "Granicus", "Birmingham-Jefferson", "Railroad Park",
    "Red Mountain", "Protective Stadium", "Legion Field", "Crossplex",
    "Flock Safety", "license plate reader", "Mayor Woodfin", "City Attorney",
    "Pro Tem", "ordinance", "resolution", "consent agenda", "executive session",
)

_LEAD = "Birmingham City Council."
_ROSTER_LEAD = " Councilors: "
_VOCAB_LEAD = " Terms: "


class PromptBudgetError(ValueError):
    """The roster alone does not fit the prompt budget."""


def build_initial_prompt(
    roster_names: list[str],
    vocabulary: tuple[str, ...] | list[str] = LOCAL_VOCABULARY,
    max_chars: int = 600,
) -> str:
    head = _LEAD + (_ROSTER_LEAD + ", ".join(roster_names) + "." if roster_names else "")
    if len(head) > max_chars:
        raise PromptBudgetError(
            f"roster alone is {len(head)} chars; budget is {max_chars}"
        )
    vocab = list(vocabulary)
    while vocab:
        candidate = head + _VOCAB_LEAD + ", ".join(vocab) + "."
        if len(candidate) <= max_chars:
            return candidate
        vocab.pop()
    return head
