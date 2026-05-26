"""
Integration tests — real Gemini LLM, mocked Google Maps HTTP.

These tests build a fresh server stack (agent + executor + Starlette app) with
the real MAPS_A2A_GEMINI_KEY set explicitly before any google-genai client is
created. This avoids the stale-client problem that arises when test_server.py
imports main with a fake key first.

The core assertion in every test is that `mock_client.get.called` is True —
proving Gemini actually invoked a Maps tool rather than hallucinating.

Skipped automatically when a real MAPS_A2A_GEMINI_KEY is not available.

Run alone (recommended for CI):
    uv run pytest tests/test_integration.py -v -m integration
"""

import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.integration


def _is_placeholder(key: str) -> bool:
    return not key or "test" in key.lower() or "placeholder" in key.lower()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def require_real_gemini(real_gemini_key):
    """Skip every test in this module when a real Gemini key is unavailable.
    Also adds a small inter-test delay to stay within free-tier rate limits.
    """
    if _is_placeholder(real_gemini_key):
        pytest.skip("Real MAPS_A2A_GEMINI_KEY not available")
    yield
    time.sleep(8)  # avoid 429 RESOURCE_EXHAUSTED on free-tier Gemini keys (15 RPM limit)


@pytest.fixture(scope="module")
def integration_client(real_gemini_key):
    """Build a fresh Starlette app with the real Gemini key passed directly.

    Sets GOOGLE_API_KEY before creating GoogleMapsAgent so that the ADK
    LlmAgent picks up the correct key when it first instantiates the genai
    client — no stale cached clients from the unit-test import path.
    """
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route

    from agent import GoogleMapsAgent
    from agent_executor import GoogleMapsAgentExecutor
    from main import (
        AGENT_CARD,
        GoogleMapsService,
        SecurityMiddleware,
        config,
        get_well_known_agent_card,
        health,
    )

    # Pass the key directly into the environment before any genai object is created.
    with patch.dict(os.environ, {"GOOGLE_API_KEY": real_gemini_key}):
        svc = GoogleMapsService("fake_maps_key")  # Maps HTTP is always mocked
        agent = GoogleMapsAgent(svc)              # LlmAgent created with real key in env
        executor = GoogleMapsAgentExecutor(agent)
        handler = DefaultRequestHandler(
            agent_executor=executor,
            task_store=InMemoryTaskStore(),
            agent_card=AGENT_CARD,
        )
        routes = create_jsonrpc_routes(handler, rpc_url="/", enable_v0_3_compat=True)
        app = Starlette(
            routes=[
                Route("/health", health, methods=["GET"]),
                Route("/.well-known/agent-card.json", get_well_known_agent_card, methods=["GET"]),
                *routes,
            ],
            middleware=[Middleware(SecurityMiddleware)],
        )

        test_headers = {
            "X-API-Key": config.a2a_api_key,
            "Content-Type": "application/json",
            "A2A-Version": "1.0",
        }

        yield TestClient(app, raise_server_exceptions=True), svc, test_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def send_text(query: str) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "SendMessage",
        "params": {
            "message": {
                "messageId": str(uuid.uuid4()),
                "role": "ROLE_USER",
                "parts": [{"text": query}],
            }
        },
    }


def assert_text_response(result: dict) -> str:
    assert "error" not in result, f"JSON-RPC error: {result.get('error')}"
    msg = result.get("result", {}).get("message", {})
    parts = msg.get("parts", [])
    assert parts, "No parts in response message"
    assert "text" in parts[0], f"Expected text part; got: {list(parts[0].keys())}"
    text = parts[0]["text"]
    assert text.strip(), "Response text is empty"
    return text


def mock_http_response(data: dict) -> MagicMock:
    m = MagicMock()
    m.status_code = 200
    m.json.return_value = data
    return m


def maps_mock(svc, response_data: dict):
    """Context manager that mocks maps_service._client with response_data."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_http_response(response_data))
    return patch.object(svc, "_client", return_value=mock_client), mock_client


# ---------------------------------------------------------------------------
# Realistic Maps API fixture responses
# ---------------------------------------------------------------------------

GEOCODE_RESPONSE = {
    "status": "OK",
    "results": [{
        "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
        "geometry": {"location": {"lat": 37.4224764, "lng": -122.0842499}},
        "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
    }],
}

REVERSE_GEOCODE_RESPONSE = {
    "status": "OK",
    "results": [{
        "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
        "types": ["street_address"],
    }],
}

DIRECTIONS_RESPONSE = {
    "status": "OK",
    "routes": [{
        "summary": "US-101 S",
        "legs": [{
            "distance": {"text": "30.7 mi", "value": 49424},
            "duration": {"text": "38 mins", "value": 2280},
            "start_address": "San Francisco, CA, USA",
            "end_address": "Mountain View, CA, USA",
            "steps": [
                {"html_instructions": "Head <b>south</b> on 4th St", "distance": {"text": "453 ft"}},
                {"html_instructions": "Merge onto <b>US-101 S</b>", "distance": {"text": "26.8 mi"}},
                {"html_instructions": "Take exit <b>394</b> for Shoreline Blvd", "distance": {"text": "0.3 mi"}},
            ],
        }],
    }],
}

PLACES_RESPONSE = {
    "status": "OK",
    "results": [
        {"name": "Blue Bottle Coffee", "formatted_address": "66 Mint St, San Francisco, CA 94103", "rating": 4.4},
        {"name": "Sightglass Coffee", "formatted_address": "270 7th St, San Francisco, CA 94103", "rating": 4.5},
        {"name": "Ritual Coffee Roasters", "formatted_address": "1026 Valencia St, San Francisco, CA", "rating": 4.3},
    ],
}

PLACE_DETAILS_RESPONSE = {
    "status": "OK",
    "result": {
        "name": "Googleplex",
        "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
        "rating": 4.3,
        "formatted_phone_number": "(650) 253-0000",
        "website": "https://about.google/",
    },
}

DISTANCE_MATRIX_RESPONSE = {
    "status": "OK",
    "origin_addresses": ["San Francisco, CA, USA"],
    "destination_addresses": ["Mountain View, CA, USA"],
    "rows": [{"elements": [{
        "distance": {"text": "30.7 mi", "value": 49424},
        "duration": {"text": "38 mins", "value": 2280},
        "status": "OK",
    }]}],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestGeocodeIntegration:
    def test_gemini_calls_geocode_tool(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, GEOCODE_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "What are the exact GPS coordinates for "
                "1600 Amphitheatre Parkway, Mountain View, CA?"
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the geocode tool — possible hallucination"
        text = assert_text_response(result)
        assert any(kw in text for kw in ["37", "122", "Mountain View", "latitude", "longitude"])

    def test_gemini_calls_geocode_for_landmark(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, GEOCODE_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "Geocode: 1600 Amphitheatre Parkway, Mountain View, California."
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the geocode tool — possible hallucination"
        assert_text_response(result)


class TestReverseGeocodeIntegration:
    def test_gemini_calls_reverse_geocode_tool(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, REVERSE_GEOCODE_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "What is the street address at latitude 37.4224764, longitude -122.0842499?"
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the reverse_geocode tool — possible hallucination"
        text = assert_text_response(result)
        assert any(kw in text for kw in ["Amphitheatre", "Mountain View", "California", "CA"])


class TestDirectionsIntegration:
    def test_gemini_calls_directions_tool(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, DIRECTIONS_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "How do I drive from San Francisco, CA to Mountain View, CA?"
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the directions tool — possible hallucination"
        text = assert_text_response(result)
        assert any(kw in text for kw in ["101", "mile", "min", "Mountain View", "San Francisco"])


class TestPlacesSearchIntegration:
    def test_gemini_calls_places_tool(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, PLACES_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "Search Google Maps for coffee shops near Union Square, San Francisco "
                "and return the current results."
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the places_search tool — possible hallucination"
        text = assert_text_response(result)
        assert any(kw in text for kw in ["coffee", "Coffee", "Blue Bottle", "Sightglass", "San Francisco"])


class TestPlaceDetailsIntegration:
    def test_gemini_calls_place_details_tool(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, PLACE_DETAILS_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "Call place_details with place_id ChIJ2eUgeAK6j4ARbn5u_wAGqWA "
                "and tell me the name and formatted address from the API response."
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the place_details tool — possible hallucination"
        text = assert_text_response(result)
        assert any(kw in text for kw in ["Googleplex", "Google", "Mountain View", "Amphitheatre"])


class TestDistanceMatrixIntegration:
    def test_gemini_calls_distance_matrix_tool(self, integration_client):
        tc, svc, headers = integration_client
        ctx, mock_client = maps_mock(svc, DISTANCE_MATRIX_RESPONSE)
        with ctx:
            result = tc.post("/", json=send_text(
                "Use the distance matrix tool to calculate the current driving "
                "distance and travel time from San Francisco, CA to Mountain View, CA."
            ), headers=headers).json()

        assert mock_client.get.called, "Gemini did not call the distance_matrix tool — possible hallucination"
        text = assert_text_response(result)
        assert any(kw in text for kw in ["30", "38", "mile", "min", "Mountain View"])
