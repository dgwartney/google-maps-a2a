"""
Deployment smoke tests for the Google Maps A2A v1 Server running on fly.io.

Runs against the live deployed instance — no mocks. Requires a real Google Maps
API key to be configured on the server.

Configuration (via environment variables or .env):
    A2A_URL      Base URL of the deployed server (default: https://google-maps-a2a.fly.dev)
    A2A_API_KEY  API key for authenticated endpoints

Run:
    uv run pytest test_deployment.py -v
    uv run pytest test_deployment.py -v -k "geocode"
"""

import os
import uuid

import httpx
import pytest
from dotenv import load_dotenv

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
# Helpers
# ---------------------------------------------------------------------------

def jsonrpc(method: str, params: dict) -> dict:
    return {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": method, "params": params}


def send_message(task_type: str, fmt: str, content: object, output_format: str | None = None) -> dict:
    data_payload: dict = {
        "type": task_type,
        "input": {"format": fmt, "content": content},
    }
    if output_format:
        data_payload["output"] = {"format": output_format}
    return jsonrpc("SendMessage", {"message": {
        "messageId": str(uuid.uuid4()),
        "role": "ROLE_USER",
        "parts": [{"data": data_payload, "mediaType": "application/json"}],
    }})


def assert_message_result(result: dict) -> dict:
    assert "error" not in result, f"Unexpected JSON-RPC error: {result.get('error')}"
    msg = result.get("result", {}).get("message", {})
    parts = msg.get("parts", [])
    assert parts, "No parts in response message"
    assert "data" in parts[0], f"Expected data part; got: {list(parts[0].keys())}"
    return parts[0]["data"]


def post(payload: dict, extra_headers: dict | None = None) -> dict:
    h = {**AUTH_HEADERS, **(extra_headers or {})}
    return client.post("/", json=payload, headers=h).json()


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

    def test_agent_card_no_auth_required(self):
        r = client.get("/.well-known/agent-card.json")
        assert r.status_code == 200  # No X-API-Key needed

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
        r = client.post("/", json=send_message("geocode", "text", "test"),
                        headers={"Content-Type": "application/json", "A2A-Version": "1.0"})
        assert r.status_code == 403

    def test_wrong_key_returns_401(self):
        r = client.post("/", json=send_message("geocode", "text", "test"),
                        headers={**AUTH_HEADERS, "X-API-Key": "wrong-key"})
        assert r.status_code == 401

    def test_valid_key_accepted(self):
        r = client.post("/", json=send_message("geocode", "text", "San Francisco"), headers=AUTH_HEADERS)
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
        r = client.post("/", json=send_message("geocode", "text", "test"), headers=h)
        assert r.status_code == 200
        assert "error" in r.json()


# ---------------------------------------------------------------------------
# 4. Geocode
# ---------------------------------------------------------------------------

class TestGeocode:
    def test_text_input_returns_coordinates(self):
        data = assert_message_result(post(send_message("geocode", "text", "1600 Amphitheatre Parkway, Mountain View, CA")))
        assert data["status"] == "OK"
        loc = data["results"][0]["geometry"]["location"]
        assert abs(loc["lat"] - 37.42) < 0.5
        assert abs(loc["lng"] - (-122.08)) < 0.5

    def test_json_input(self):
        data = assert_message_result(post(send_message("geocode", "application/json", {"address": "Times Square, NY"})))
        assert data["status"] == "OK"

    def test_geojson_output(self):
        data = assert_message_result(post(send_message("geocode", "text", "Golden Gate Bridge", output_format="application/geo+json")))
        assert data["type"] == "Feature"
        assert data["geometry"]["type"] == "Point"
        assert len(data["geometry"]["coordinates"]) == 2


# ---------------------------------------------------------------------------
# 5. Reverse geocode
# ---------------------------------------------------------------------------

class TestReverseGeocode:
    def test_returns_address(self):
        data = assert_message_result(post(send_message("reverse_geocode", "application/json", {"lat": 37.4224864, "lng": -122.0855962})))
        assert data["status"] == "OK"
        assert data["results"][0]["formatted_address"]

    def test_text_output_format(self):
        data = assert_message_result(post(send_message("reverse_geocode", "application/json",
            {"lat": 40.7579747, "lng": -73.9855426}, output_format="text")))
        assert "address" in data
        assert isinstance(data["address"], str)


# ---------------------------------------------------------------------------
# 6. Directions
# ---------------------------------------------------------------------------

class TestDirections:
    def test_driving_directions(self):
        data = assert_message_result(post(send_message("directions", "application/json",
            {"origin": "San Francisco, CA", "destination": "Mountain View, CA", "mode": "driving"})))
        assert data["status"] == "OK"
        assert len(data["routes"]) > 0

    def test_text_output_has_steps(self):
        data = assert_message_result(post(send_message("directions", "application/json",
            {"origin": "San Francisco, CA", "destination": "Mountain View, CA", "mode": "driving"},
            output_format="text")))
        assert "directions" in data
        assert "1." in data["directions"]


# ---------------------------------------------------------------------------
# 7. Places search
# ---------------------------------------------------------------------------

class TestPlacesSearch:
    def test_text_query_returns_results(self):
        data = assert_message_result(post(send_message("places_search", "text", "coffee shops near Union Square San Francisco")))
        assert data["status"] == "OK"
        assert len(data["results"]) > 0

    def test_json_input_with_location(self):
        data = assert_message_result(post(send_message("places_search", "application/json",
            {"query": "pizza", "location": {"lat": 37.7749, "lng": -122.4194}, "radius": 1000})))
        assert data["status"] == "OK"

    def test_geojson_output(self):
        data = assert_message_result(post(send_message("places_search", "text", "parks in San Francisco", output_format="application/geo+json")))
        assert data["type"] == "FeatureCollection"
        assert isinstance(data["features"], list)


# ---------------------------------------------------------------------------
# 8. Place details
# ---------------------------------------------------------------------------

class TestPlaceDetails:
    GOOGLEPLEX = "ChIJ2eUgeAK6j4ARbn5u_wAGqWA"

    def test_returns_place_details(self):
        data = assert_message_result(post(send_message("place_details", "application/json", {"place_id": self.GOOGLEPLEX})))
        assert data["status"] == "OK"
        assert "result" in data
        assert "formatted_address" in data["result"]

    def test_mountain_view_in_address(self):
        data = assert_message_result(post(send_message("place_details", "application/json", {"place_id": self.GOOGLEPLEX})))
        assert "Mountain View" in data["result"]["formatted_address"]


# ---------------------------------------------------------------------------
# 9. Distance matrix
# ---------------------------------------------------------------------------

class TestDistanceMatrix:
    def test_single_pair(self):
        data = assert_message_result(post(send_message("distance_matrix", "application/json",
            {"origins": ["San Francisco, CA"], "destinations": ["Mountain View, CA"], "mode": "driving"})))
        assert data["status"] == "OK"
        el = data["rows"][0]["elements"][0]
        assert el["status"] == "OK"
        assert "distance" in el and "duration" in el

    def test_multiple_destinations(self):
        data = assert_message_result(post(send_message("distance_matrix", "application/json",
            {"origins": ["San Francisco, CA"], "destinations": ["Mountain View, CA", "San Jose, CA", "Oakland, CA"], "mode": "driving"})))
        assert len(data["rows"][0]["elements"]) == 3
