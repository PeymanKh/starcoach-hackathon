import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    """The run rate limit counts requests in Django's cache: every test starts at zero."""
    cache.clear()
