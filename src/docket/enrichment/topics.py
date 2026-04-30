"""Topic classification for agenda items.

Assigns one or more topic tags to agenda items based on keyword matching
against the title and description text. Topics are designed for the
"Browse by topic" UI feature.

This is keyword-based classification. When AI features are enabled,
this can be upgraded to LLM-based classification for better accuracy.
"""

from __future__ import annotations

# Topic definitions: (topic_slug, display_name, keywords)
# Keywords are matched case-insensitively against combined title + description.
# Order matters — first match wins for primary topic.
TOPIC_DEFINITIONS: list[tuple[str, str, list[str]]] = [
    ("zoning", "Zoning & Land Use", [
        "rezon", "zoning", "planning approval", "planned unit development",
        "land use", "subdivision", "plat", "variance", "certificate of occupancy",
        "building permit", "annexation",
    ]),
    ("public_safety", "Public Safety", [
        "police", "fire department", "public safety", "law enforcement",
        "surveillance", "emergency", "nuisance", "demolition", "demolish",
        "abatement", "inoperable motor vehicle", "code enforcement",
        "animal shelter", "stray",
    ]),
    ("public_works", "Public Works", [
        "resurfacing", "drainage", "sidewalk", "road", "street",
        "infrastructure", "water", "sewer", "paving", "traffic signal",
        "street sweeper", "sanitation", "garbage", "recycling",
    ]),
    ("budget", "Budget & Finance", [
        "budget", "appropriat", "transfer funds", "fiscal year",
        "general fund", "expense account", "payment to", "purchase order",
        "lump sum bid",
    ]),
    ("grants", "Grants & Federal Funding", [
        "grant", "federal funding", "hud", "cdbg", "fema",
        "department of justice", "department of transportation",
        "safe streets", "cops hiring",
    ]),
    ("contracts", "Contracts & Procurement", [
        "contract with", "agreement between", "execute and deliver",
        "amendment to the agreement", "purchase order",
        "bid of", "procurement",
    ]),
    ("legal", "Legal & Settlements", [
        "settlement", "city attorney", "lawsuit", "litigation",
        "workers' compensation", "mutual release", "general code",
    ]),
    ("parks_culture", "Parks & Culture", [
        "park", "recreation", "library", "museum", "arts",
        "folk festival", "cultural", "pool", "ballfield",
    ]),
    ("licensing", "Licensing & Permits", [
        "license", "liquor", "beer", "wine", "abc board",
        "certificate of public convenience", "noise ordinance",
        "waiver",
    ]),
    ("appointments", "Appointments & Personnel", [
        "appointing", "appointment", "employee of the month",
        "special bonus", "board member",
    ]),
    ("routine", "Routine & Procedural", [
        "roll call", "pledge of allegiance", "invocation",
        "approval of minutes", "minutes not ready",
        "adjournment", "consent agenda", "old and new business",
        "request from the public", "communications from",
        "presentations",
    ]),
]


def classify_topic(title: str, description: str | None = None) -> str | None:
    """Classify an agenda item into a topic.

    Returns the topic slug (e.g. "zoning", "budget") or None if no match.
    First matching topic wins.
    """
    text = (title or "").lower()
    if description:
        text += " " + description.lower()

    if not text.strip():
        return None

    for slug, _display_name, keywords in TOPIC_DEFINITIONS:
        for keyword in keywords:
            if keyword in text:
                return slug

    return None


def classify_topics(title: str, description: str | None = None) -> list[str]:
    """Classify an agenda item into all matching topics.

    Returns a list of topic slugs. May return multiple matches
    (e.g., a grant for road work matches both "grants" and "public_works").
    """
    text = (title or "").lower()
    if description:
        text += " " + description.lower()

    if not text.strip():
        return []

    matched = []
    for slug, _display_name, keywords in TOPIC_DEFINITIONS:
        for keyword in keywords:
            if keyword in text:
                matched.append(slug)
                break

    return matched


def get_topic_display_name(slug: str) -> str | None:
    """Get the display name for a topic slug."""
    for topic_slug, display_name, _keywords in TOPIC_DEFINITIONS:
        if topic_slug == slug:
            return display_name
    return None


def all_topics() -> list[dict]:
    """Return all topic definitions for UI rendering."""
    return [
        {"slug": slug, "name": display_name}
        for slug, display_name, _keywords in TOPIC_DEFINITIONS
    ]
