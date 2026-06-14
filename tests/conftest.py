"""Pytest conftest — shared fixtures and test markers."""

from __future__ import annotations

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom pytest markers."""
    config.addinivalue_line("markers", "chaos: marks tests as chaos/fault injection tests")
    config.addinivalue_line("markers", "slow: marks tests that take significant time")
