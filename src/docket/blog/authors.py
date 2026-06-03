"""Author registry loaded from config/blog_authors.yaml."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from docket.blog.types import Author


@dataclass(frozen=True)
class AuthorsRegistry:
    by_key: dict[str, Author]

    def get(self, key: str) -> Author | None:
        return self.by_key.get(key)

    def resolve_keys(self, keys: list[str]) -> list[Author]:
        resolved = []
        for k in keys:
            a = self.by_key.get(k)
            if a is None:
                raise ValueError(f"unknown author key {k!r} (not in blog_authors.yaml)")
            resolved.append(a)
        return resolved


def load_authors_registry(path: Path) -> AuthorsRegistry:
    raw = yaml.safe_load(path.read_text()) or {}
    by_key: dict[str, Author] = {}
    for key, fields in raw.items():
        avatar = fields.get("avatar")
        avatar_url = f"/static/blog/authors/{avatar}" if avatar else None
        by_key[key] = Author(
            key=key,
            display_name=str(fields.get("display_name") or key),
            bio=str(fields.get("bio") or ""),
            avatar_url=avatar_url,
            links=dict(fields.get("links") or {}),
        )
    return AuthorsRegistry(by_key=by_key)
