"""Adapter registry — maps adapter_class strings to adapter classes."""

from __future__ import annotations

from docket.adapters.civicclerk import CivicClerkAdapter
from docket.adapters.civicplus import CivicPlusAdapter
from docket.adapters.generic_cms import GenericCMSAdapter
from docket.adapters.granicus import GranicusAdapter

ADAPTER_REGISTRY: dict[str, type] = {
    "GranicusAdapter": GranicusAdapter,
    "CivicClerkAdapter": CivicClerkAdapter,
    "CivicPlusAdapter": CivicPlusAdapter,
    "GenericCMSAdapter": GenericCMSAdapter,
}


def get_adapter(adapter_class: str, municipality_slug: str, config: dict):
    """Instantiate an adapter by its class name."""
    cls = ADAPTER_REGISTRY.get(adapter_class)
    if cls is None:
        raise ValueError(
            f"Unknown adapter class: {adapter_class}. "
            f"Available: {list(ADAPTER_REGISTRY.keys())}"
        )
    return cls(municipality_slug=municipality_slug, config=config)
