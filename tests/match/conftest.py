import pytest

from hive.engine.rules import Rules


@pytest.fixture(scope="function")
def rules() -> Rules:
    """Build the default rules."""
    return Rules()
