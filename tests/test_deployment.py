"""
Deployment smoke tests for the Google Maps A2A v1 Server running on fly.io.

Runs against the live deployed instance — no mocks. Requires a real Google Maps
API key and Gemini API key to be configured on the server.

All requests use text/plain input and expect text/plain responses from the
LLM-powered agent.

Configuration (via environment variables or .env):
    A2A_URL      Base URL of the deployed server (default: https://google-maps-a2a.fly.dev)
    A2A_API_KEY  API key for authenticated endpoints

Run:
    uv run pytest tests/test_deployment.py -v
    uv run pytest tests/test_deployment.py -v -k "geocode"
"""

import os
import time
import uuid

import httpx
import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.deployment

load_dotenv()

BASE_URL = os.getenv("A2A_URL", "https://google-maps-a2a.fly.dev").rstrip("/")
API_KEY = os.getenv("A2A_API_KEY", os.getenv("API_KEY", ""))

if not API_KEY:
    pytest.skip("A2A_API_KEY not set — skipping deployment tests", allow_module_level=True)

AUTH_HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
    "A2A-Version": "1.0",
}

client = httpx.Client(base_url=BASE_URL, timeout=30.0)


# ---------------------------------------------------------------------------
# Rate-limit pacing
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def pace_requests():
    """Sleep after each test to stay within Gemini free-tier rate limits (15 RPM)."""
    yield
    time.sleep(15)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def jsonrpc(method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}


def send_text(query: str) -> dict:
    """Build a SendMessage payload with a single text/plain part."""
    return jsonrpc("SendMessage", {"message": {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"text": query}],
    }})


def assert_text_response(result: dict) -> str:
    """Assert JSON-RPC success with a message containing a text part; return the text."""
    assert "error" not in result, f"Unexpected JSON-RPC error: {result.get('error')}"
    msg = result.get("result", {}).get("message", {})
    parts = msg.get("parts", [])
    assert parts, "No parts in response message"
    assert "text" in parts[0], f"Expected text part; got: {list(parts[0].keys())}"
    text = parts[0]["text"]
    assert text.strip(), "Response text is empty"
    return text


def post(payload: dict) -> dict:
    return client.post("/", json=payload, headers=AUTH_HEADERS).json()


# ---------------------------------------------------------------------------
# 1. Infrastructure
# ---------------------------------------------------------------------------

class TestInfrastructure:
    def test_health_check(self):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_well_known_agent_card(self):
        r = client.get("/.well-known/agent-card.json")
        assert r.status_code == 200
        card = r.json()
        assert card["name"] == "Google Maps A2A"
        assert card["version"] == "2.0.0"
        skill_ids = {s["id"] for s in card["skills"]}
        assert skill_ids == {
            "geocode", "reverse_geocode", "directions",
            "places_search", "place_details", "distance_matrix",
        }
        assert card["supportedInterfaces"][0]["protocolBinding"] == "jsonrpc"

    def test_agent_card_text_plain_input_modes(self):
        card = client.get("/.well-known/agent-card.json").json()
        for skill in card["skills"]:
            assert "text/plain" in skill.get("inputModes", []), (
                f"Skill '{skill['id']}' missing text/plain input mode"
            )

    def test_agent_card_no_auth_required(self):
        r = client.get("/.well-known/agent-card.json")
        assert r.status_code == 200

    def test_agent_card_has_security_scheme(self):
        card = client.get("/.well-known/agent-card.json").json()
        assert "apiKey" in card["securitySchemes"]
        scheme = card["securitySchemes"]["apiKey"]["apiKeySecurityScheme"]
        assert scheme["name"] == "X-API-Key"


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------

class TestAuthentication:
    def test_missing_key_returns_403(self):
        r = client.post("/", json=send_text("test"),
                        headers={"Content-Type": "application/json", "A2A-Version": "1.0"})
        assert r.status_code == 403

    def test_wrong_key_returns_401(self):
        r = client.post("/", json=send_text("test"),
                        headers={**AUTH_HEADERS, "X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_valid_key_accepted(self):
        r = client.post("/", json=send_text("What are the coordinates of San Francisco?"),
                        headers=AUTH_HEADERS)
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 3. JSON-RPC protocol
# ---------------------------------------------------------------------------

class TestJSONRPC:
    def test_unknown_method_returns_error(self):
        result = post(jsonrpc("UnknownMethod", {}))
        assert result["error"]["code"] == -32601

    def test_missing_version_header_returns_error(self):
        h = {k: v for k, v in AUTH_HEADERS.items() if k != "A2A-Version"}
        r = client.post("/", json=send_text("test"), headers=h)
        assert r.status_code == 200
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# 4. Geocode
# ---------------------------------------------------------------------------

class TestGeocode:
    def test_returns_coordinates(self):
        text = assert_text_response(post(send_text(
            "What are the GPS coordinates for 1600 Amphitheatre Parkway, Mountain View, CA?"
        )))
        # Gemini returns lat/lng somewhere in the response
        assert any(kw in text for kw in ["37", "122", "Mountain View", "latitude", "longitude"])

    def test_landmark(self):
        text = assert_text_response(post(send_text(
            "What are the coordinates of the Golden Gate Bridge?"
        )))
        assert any(kw in text for kw in ["37", "122", "San Francisco", "latitude"])


# ---------------------------------------------------------------------------
# 5. Reverse geocode
# ---------------------------------------------------------------------------

class TestReverseGeocode:
    def test_returns_address(self):
        text = assert_text_response(post(send_text(
            "What is the address at latitude 37.4224864, longitude -122.0855962?"
        )))
        assert any(kw in text for kw in ["Amphitheatre", "Mountain View", "California", "CA"])

    def test_times_square(self):
        text = assert_text_response(post(send_text(
            "What address is at coordinates 40.7579747, -73.9855426?"
        )))
        assert any(kw in text for kw in ["New York", "NY", "Broadway", "Times", "Manhattan"])


# ---------------------------------------------------------------------------
# 6. Directions
# ---------------------------------------------------------------------------

class TestDirections:
    def test_driving_directions(self):
        text = assert_text_response(post(send_text(
            "How do I drive from San Francisco, CA to Mountain View, CA?"
        )))
        assert any(kw in text for kw in ["101", "280", "Highway", "miles", "minutes", "hours"])

    def test_includes_steps(self):
        text = assert_text_response(post(send_text(
            "Give me step-by-step driving directions from San Francisco to Mountain View."
        )))
        assert len(text) > 100


# ---------------------------------------------------------------------------
# 7. Places search
# ---------------------------------------------------------------------------

class TestPlacesSearch:
    def test_returns_results(self):
        text = assert_text_response(post(send_text(
            "Find coffee shops near Union Square, San Francisco."
        )))
        assert any(kw in text for kw in ["coffee", "café", "cafe", "San Francisco", "Union Square"])

    def test_restaurants(self):
        text = assert_text_response(post(send_text(
            "What pizza restaurants are near Times Square, New York?"
        )))
        assert any(kw in text for kw in ["pizza", "New York", "restaurant", "Times Square"])


# ---------------------------------------------------------------------------
# 8. Place details
# ---------------------------------------------------------------------------

class TestPlaceDetails:
    def test_googleplex(self):
        text = assert_text_response(post(send_text(
            "Tell me about the Googleplex at 1600 Amphitheatre Parkway, Mountain View."
        )))
        assert any(kw in text for kw in ["Google", "Mountain View", "Amphitheatre"])

    def test_returns_useful_info(self):
        text = assert_text_response(post(send_text(
            "What are the details for the Empire State Building in New York?"
        )))
        assert any(kw in text for kw in ["Empire State", "New York", "Fifth Avenue"])


# ---------------------------------------------------------------------------
# 9. Distance matrix
# ---------------------------------------------------------------------------

class TestDistanceMatrix:
    def test_single_pair(self):
        text = assert_text_response(post(send_text(
            "How far is it to drive from San Francisco, CA to Mountain View, CA? "
            "Give me the distance and estimated travel time."
        )))
        assert any(kw in text for kw in ["mile", "km", "minute", "hour", "min"])

    def test_multiple_destinations(self):
        text = assert_text_response(post(send_text(
            "Compare driving distances from San Francisco to Mountain View, San Jose, and Oakland."
        )))
        assert any(kw in text for kw in ["Mountain View", "San Jose", "Oakland"])
