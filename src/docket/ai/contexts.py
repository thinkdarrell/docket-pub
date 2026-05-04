"""Dataclasses that mediate between DB rows and prompt strings.

Each context's from_row() factory normalizes NULL columns so rendered
prompts never contain the literal string "None".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from docket.ai.results import MeetingPhase


# Significance threshold separating "distinctive" items (Sonnet leads with them)
# from "routine" items (Sonnet treats as background, summarizes as a count).
# Tunable; chosen at 6 because Haiku consistently scores routine demolitions /
# vehicle abatements / weed clearances at 4-5 and reserves 6+ for items with
# specific dollar amounts, named contracts, or citywide policy impact.
DISTINCTIVE_SIGNIFICANCE_THRESHOLD = 6.0


def _format_dollars(amount: Decimal | None) -> str:
    if amount is None:
        return "(none)"
    return f"${amount:,.2f}"


@dataclass(frozen=True)
class AgendaItemContext:
    item_id: int
    title: str
    description: str
    sponsor: str
    dollars_amount: str
    topic: str
    is_consent_label: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "AgendaItemContext":
        return cls(
            item_id=row["id"],
            title=row["title"],
            description=row["description"] or "(no description provided)",
            sponsor=row["sponsor"] or "(no sponsor listed)",
            dollars_amount=_format_dollars(row["dollars_amount"]),
            topic=row["topic"] or "Uncategorized",
            is_consent_label="Yes" if row["is_consent"] else "No",
        )

    def render_user_prompt(self) -> str:
        from docket.ai.prompts import ITEM_USER_TEMPLATE
        return ITEM_USER_TEMPLATE.format(
            title=self.title,
            description=self.description,
            sponsor=self.sponsor,
            dollars_amount=self.dollars_amount,
            topic=self.topic,
            is_consent=self.is_consent_label,
        )


@dataclass(frozen=True)
class RoutineCluster:
    """A bucket of routine items grouped by topic, with sample titles for context."""
    topic: str                      # 'public_safety', 'contracts', etc. — or 'uncategorized'
    count: int
    sample_titles: tuple[str, ...]  # up to 3 representative titles


@dataclass(frozen=True)
class MeetingContext:
    """Input for one meeting executive-summary call.

    Items are pre-split by significance score so Sonnet sees what's distinctive
    separately from routine recurring business. This prevents demolitions /
    abatements / weed clearances (which are numerous on every meeting) from
    drowning out the items citizens actually want to know about.
    """
    meeting_id: int
    meeting_type: str
    meeting_date: date
    phase: MeetingPhase
    distinctive_items: Sequence[str]              # full Haiku summaries
    routine_clusters: Sequence[RoutineCluster]    # grouped by topic with counts

    @property
    def total_substantive_count(self) -> int:
        return len(self.distinctive_items) + sum(c.count for c in self.routine_clusters)

    def render_user_prompt(self) -> str:
        from docket.ai.prompts import MEETING_USER_TEMPLATE

        if self.distinctive_items:
            distinctive_block = "\n".join(f"- {s}" for s in self.distinctive_items)
        else:
            distinctive_block = "(none — this meeting was entirely routine business)"

        if self.routine_clusters:
            routine_lines = []
            for c in self.routine_clusters:
                samples = "; ".join(t.strip().splitlines()[0][:80] for t in c.sample_titles)
                routine_lines.append(f"- {c.count} {c.topic} item{'s' if c.count != 1 else ''} (e.g., {samples})")
            routine_block = "\n".join(routine_lines)
        else:
            routine_block = "(none)"

        return MEETING_USER_TEMPLATE.format(
            meeting_type=self.meeting_type,
            meeting_date=self.meeting_date.isoformat(),
            phase=self.phase,
            distinctive_count=len(self.distinctive_items),
            distinctive_block=distinctive_block,
            routine_count=sum(c.count for c in self.routine_clusters),
            routine_block=routine_block,
        )

    @classmethod
    def from_meeting_items(
        cls,
        *,
        meeting_id: int,
        meeting_type: str,
        meeting_date: date,
        phase: MeetingPhase,
        rows: Sequence[dict[str, Any]],
    ) -> "MeetingContext":
        """Build the context from raw item rows. Each row needs:
        summary (str, non-empty), significance_score (float|None), topic (str|None), title (str)."""
        distinctive: list[str] = []
        # routine items grouped by topic
        from collections import defaultdict
        routine_by_topic: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in rows:
            sig = r.get("significance_score") or 0.0
            if float(sig) >= DISTINCTIVE_SIGNIFICANCE_THRESHOLD:
                distinctive.append(r["summary"])
            else:
                topic = r.get("topic") or "uncategorized"
                routine_by_topic[topic].append(r)

        clusters = tuple(
            RoutineCluster(
                topic=topic,
                count=len(items),
                sample_titles=tuple(it["title"] for it in items[:3]),
            )
            for topic, items in sorted(routine_by_topic.items(), key=lambda kv: -len(kv[1]))
        )

        return cls(
            meeting_id=meeting_id,
            meeting_type=meeting_type,
            meeting_date=meeting_date,
            phase=phase,
            distinctive_items=tuple(distinctive),
            routine_clusters=clusters,
        )
