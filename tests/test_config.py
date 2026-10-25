"""What the API reads from its environment."""

import pytest

from api.core.config import get_settings


def test_cors_origins_tolerate_spaces_and_a_trailing_comma(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Untrimmed, "a, b" made " b" an origin no browser ever sends, so b was blocked."""
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test,")
    get_settings.cache_clear()
    try:
        assert get_settings().cors_origins == ["http://a.test", "http://b.test"]
    finally:
        get_settings.cache_clear()
