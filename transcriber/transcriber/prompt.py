"""Build Whisper's initial prompt from the meeting roster plus local vocabulary.

Whisper keeps only the LAST 224 tokens of the initial prompt, so an
overflow silently drops the start. We size by characters with a
conservative ceiling (600 chars is comfortably under 224 BPE tokens for
English names) and refuse to build a prompt that would overflow rather
than let truncation happen quietly. Roster names matter more than the
fixed vocabulary, so vocabulary is trimmed first, whole sentences at a time.

The prompt is prose, not a labelled list. Whisper conditions on the prompt
as if it were the preceding transcript text, and a `Terms: A, B, C, ...`
list is both unlike speech and easy to reproduce verbatim: meetings 1, 4, 8,
and 2543 each contain a segment that is the list read back as if spoken.
Short sentences in the register of a council meeting are what the model
expects to continue, so the vocabulary is carried in those. Proper nouns
Whisper misspells come first; common words it spells unaided come last and
are the first trimmed.
"""
from __future__ import annotations

VOCABULARY_SENTENCES: tuple[str, ...] = (
    "ALEA, CJI, and APC reported.",
    "Alabama Power and ALDOT spoke at the BJCC.",
    "Woodlawn, Ensley, and Avondale were named.",
    "Pratt City, Norwood, Smithfield, and Titusville came up.",
    "ADECA and BJCTA funds went to Railroad Park and Red Mountain.",
    "Protective Stadium, Legion Field, and the Crossplex were discussed.",
    "Flock Safety license plate readers were debated.",
    "Mayor Woodfin, the City Attorney, and the President Pro Tem spoke.",
    "Granicus streams the Birmingham-Jefferson meetings.",
    "An ordinance and a resolution passed on the consent agenda before executive session.",
)

_LEAD = "Birmingham City Council."
_ROSTER_LEAD = " Councilors present are "


class PromptBudgetError(ValueError):
    """The roster alone does not fit the prompt budget."""


def build_initial_prompt(
    roster_names: list[str],
    vocabulary: tuple[str, ...] | list[str] = VOCABULARY_SENTENCES,
    max_chars: int = 600,
) -> str:
    head = _LEAD + (_ROSTER_LEAD + ", ".join(roster_names) + "." if roster_names else "")
    if len(head) > max_chars:
        raise PromptBudgetError(
            f"roster alone is {len(head)} chars; budget is {max_chars}"
        )
    sentences = list(vocabulary)
    while sentences:
        candidate = head + " " + " ".join(sentences)
        if len(candidate) <= max_chars:
            return candidate
        sentences.pop()
    return head
