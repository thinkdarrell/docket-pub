"""Tests for the authors registry loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from docket.blog.authors import AuthorsRegistry, load_authors_registry


@pytest.fixture
def authors_yaml(tmp_path: Path) -> Path:
    f = tmp_path / "blog_authors.yaml"
    f.write_text(
        "darrell:\n"
        "  display_name: Darrell Nance\n"
        "  bio: Civic data nerd.\n"
        "  avatar: darrell.jpg\n"
        "  links:\n"
        "    bluesky: https://bsky.app/profile/x\n"
    )
    return f


def test_load_registry(authors_yaml: Path):
    reg = load_authors_registry(authors_yaml)
    a = reg.get("darrell")
    assert a is not None
    assert a.display_name == "Darrell Nance"
    assert a.avatar_url == "/static/blog/authors/darrell.jpg"


def test_resolve_known_key(authors_yaml: Path):
    reg = load_authors_registry(authors_yaml)
    resolved = reg.resolve_keys(["darrell"])
    assert len(resolved) == 1
    assert resolved[0].key == "darrell"


def test_resolve_unknown_key_raises(authors_yaml: Path):
    reg = load_authors_registry(authors_yaml)
    with pytest.raises(ValueError, match="unknown author key 'ghost'"):
        reg.resolve_keys(["ghost"])
