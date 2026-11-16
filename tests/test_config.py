"""What the API reads from its environment."""

import pytest

from api.core.config import get_settings
from db import build_url


@pytest.mark.parametrize("scheme", ["postgres", "postgresql", "postgresql+psycopg"])
def test_hosted_database_urls_use_psycopg3(monkeypatch: pytest.MonkeyPatch, scheme: str) -> None:
    """Neon and Railway give postgresql://, which would load the absent psycopg2."""
    monkeypatch.setenv("DATABASE_URL", f"{scheme}://u:p@h/db?sslmode=require")
    assert build_url() == "postgresql+psycopg://u:p@h/db?sslmode=require"


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
