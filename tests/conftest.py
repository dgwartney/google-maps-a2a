"""Shared pytest configuration — loaded before any test module."""
import os
import pytest
from dotenv import load_dotenv

# Load .env so real keys are available before any test module clobbers env vars.
load_dotenv(override=True)  # .env values win over stale shell env vars

# Capture the real MAPS_A2A_GEMINI_KEY before test_server.py overwrites it with a fake.
_REAL_GEMINI_KEY = os.environ.get("MAPS_A2A_GEMINI_KEY", "")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: real Gemini LLM + mocked Maps HTTP — requires a valid GEMINI_API_KEY",
    )


@pytest.fixture(scope="session")
def real_gemini_key() -> str:
    """Return the real GEMINI_API_KEY captured at session start."""
    return _REAL_GEMINI_KEY
