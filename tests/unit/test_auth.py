"""Tests for admin authentication."""

from werkzeug.security import check_password_hash, generate_password_hash


def test_password_hash_roundtrip():
    """Verify werkzeug password hashing works as expected."""
    pw = "test-password-123"
    hashed = generate_password_hash(pw)
    assert check_password_hash(hashed, pw)
    assert not check_password_hash(hashed, "wrong-password")


def test_login_required_decorator():
    """Verify the login_required decorator exists and is callable."""
    from docket.web.auth import login_required

    @login_required
    def dummy_view():
        return "ok"

    assert callable(dummy_view)
    assert dummy_view.__name__ == "dummy_view"
