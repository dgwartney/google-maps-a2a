"""
Unit tests for the Google Maps A2A v1 server.

Tests run against the local Starlette app via httpx.AsyncClient (not mock TestClient)
since the a2a-sdk uses async Starlette routes. All Google Maps HTTP calls are mocked.
"""
import json
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient

# Set environment variables BEFORE importing main
os.environ["API_KEY"] = "test_api_key"
os.environ["GOOGLE_MAPS_API_KEY"] = "test_google_maps_api_key"
os.environ["LOG_LEVEL"] = "DEBUG"

from main import (  # noqa: E402
    Config,
    GoogleMapsAgentExecutor,
    GoogleMapsService,
    AGENT_CARD,
    AGENT_CARD_DICT,
    SUPPORTED_TASK_TYPES,
    app,
    config,
    maps_service,
)

TEST_API_KEY = "test_api_key"
A2A_VERSION = "1.0"

client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def headers(include_auth: bool = True, include_version: bool = True) -> dict:
    h = {"Content-Type": "application/json"}
    if include_auth:
        h["X-API-Key"] = TEST_API_KEY
    if include_version:
        h["A2A-Version"] = A2A_VERSION
    return h


def jsonrpc(method: str, params: dict, req_id: str = "1") -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}


def send_message_payload(task_type: str, fmt: str, content: object) -> dict:
    return jsonrpc("SendMessage", {
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "parts": [{
                "data": {"type": task_type, "input": {"format": fmt, "content": content}},
                "mediaType": "application/json",
            }],
        }
    })


def make_mock_response(status: str = "OK", extra: dict | None = None) -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    data: dict = {"status": status}
    if status == "OK":
        data.update(extra or {
            "results": [{
                "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
                "geometry": {"location": {"lat": 37.4224864, "lng": -122.0855962}},
                "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
            }],
            "routes": [{"legs": [{"steps": [
                {"html_instructions": "<b>Head north</b> on Main St"},
                {"html_instructions": "Turn <b>right</b>"},
            ], "distance": {"text": "10 km"}, "duration": {"text": "15 mins"}}]}],
            "rows": [{"elements": [{"distance": {"text": "10 km"}, "duration": {"text": "15 mins"}, "status": "OK"}]}],
            "destination_addresses": ["Mountain View, CA, USA"],
            "origin_addresses": ["San Francisco, CA, USA"],
            "result": {"name": "Googleplex", "formatted_address": "1600 Amphitheatre Pkwy", "rating": 4.5},
        })
    mock.json.return_value = data
    return mock


def assert_message_response(result: dict, check_data: bool = True) -> dict:
    """Assert JSON-RPC success with a message response; return the data dict from the first part."""
    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert "result" in result
    r = result["result"]
    assert "message" in r, f"Expected 'message' in result, got: {list(r.keys())}"
    parts = r["message"].get("parts", [])
    assert parts, "Response message has no parts"
    if check_data:
        assert "data" in parts[0], f"Expected data part, got: {list(parts[0].keys())}"
        return parts[0]["data"]
    return parts[0]


# ---------------------------------------------------------------------------
# Mock fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_maps_ok():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=make_mock_response())
    with patch.object(maps_service, "_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_maps_error():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=make_mock_response(status="ZERO_RESULTS"))
    with patch.object(maps_service, "_client", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# 1. Infrastructure
# ---------------------------------------------------------------------------

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_well_known_agent_card():
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    assert card["name"] == "Google Maps A2A"
    assert card["version"] == "2.0.0"
    skill_ids = {s["id"] for s in card["skills"]}
    assert skill_ids == SUPPORTED_TASK_TYPES
    assert card["capabilities"]["streaming"] is False
    assert len(card["supportedInterfaces"]) == 1
    assert card["supportedInterfaces"][0]["protocolBinding"] == "jsonrpc"


def test_agent_card_has_api_key_security_scheme():
    r = client.get("/.well-known/agent-card.json")
    card = r.json()
    assert "apiKey" in card["securitySchemes"]
    scheme = card["securitySchemes"]["apiKey"]["apiKeySecurityScheme"]
    assert scheme["name"] == "X-API-Key"
    assert scheme["location"] == "header"


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------

def test_missing_api_key_returns_403():
    r = client.post("/", json=send_message_payload("geocode", "text", "test"),
                    headers={"Content-Type": "application/json", "A2A-Version": "1.0"})
    assert r.status_code == 403


def test_wrong_api_key_returns_401():
    h = headers()
    h["X-API-Key"] = "wrong-key"
    r = client.post("/", json=send_message_payload("geocode", "text", "test"), headers=h)
    assert r.status_code == 401


def test_version_header_missing_returns_version_error(mock_maps_ok):
    h = headers(include_version=False)
    r = client.post("/", json=send_message_payload("geocode", "text", "test"), headers=h)
    # SDK returns JSON-RPC error for missing/wrong version
    assert r.status_code == 200
    assert r.json().get("error", {}).get("code") is not None


# ---------------------------------------------------------------------------
# 3. JSON-RPC protocol
# ---------------------------------------------------------------------------

def test_invalid_jsonrpc_version():
    r = client.post("/", json={"jsonrpc": "1.0", "id": "1", "method": "SendMessage", "params": {}},
                    headers=headers())
    assert r.status_code == 200
    assert "error" in r.json()


def test_unknown_method():
    r = client.post("/", json=jsonrpc("UnknownMethod", {}), headers=headers())
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32601  # Method not found


def test_well_known_requires_no_auth():
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200  # No X-API-Key needed


# ---------------------------------------------------------------------------
# 4. Geocode
# ---------------------------------------------------------------------------

def test_geocode_text_input(mock_maps_ok):
    r = client.post("/", json=send_message_payload("geocode", "text", "Mountain View, CA"), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"
    assert data["results"][0]["formatted_address"]


def test_geocode_json_input(mock_maps_ok):
    r = client.post("/", json=send_message_payload("geocode", "application/json", {"address": "Mountain View"}), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_geocode_geojson_output(mock_maps_ok):
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [{"data": {
            "type": "geocode",
            "input": {"format": "text", "content": "Mountain View"},
            "output": {"format": "application/geo+json"},
        }, "mediaType": "application/json"}],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert data["type"] == "Feature"
    assert data["geometry"]["type"] == "Point"


def test_geocode_api_failure_returns_error_message(mock_maps_error):
    r = client.post("/", json=send_message_payload("geocode", "text", "Nowhere"), headers=headers())
    result = r.json()
    # On failure, executor sends a text error Message (not a data part)
    assert "result" in result
    part = result["result"]["message"]["parts"][0]
    assert "text" in part
    assert "Error" in part["text"]


# ---------------------------------------------------------------------------
# 5. Reverse geocode
# ---------------------------------------------------------------------------

def test_reverse_geocode(mock_maps_ok):
    r = client.post("/", json=send_message_payload("reverse_geocode", "application/json", {"lat": 37.42, "lng": -122.08}), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_reverse_geocode_text_output(mock_maps_ok):
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [{"data": {
            "type": "reverse_geocode",
            "input": {"format": "application/json", "content": {"lat": 37.42, "lng": -122.08}},
            "output": {"format": "text"},
        }, "mediaType": "application/json"}],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert "address" in data


def test_reverse_geocode_missing_lat_lng(mock_maps_ok):
    r = client.post("/", json=send_message_payload("reverse_geocode", "application/json", {"foo": "bar"}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_reverse_geocode_non_json_input(mock_maps_ok):
    r = client.post("/", json=send_message_payload("reverse_geocode", "text", "37.42,-122.08"), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_reverse_geocode_api_failure(mock_maps_error):
    r = client.post("/", json=send_message_payload("reverse_geocode", "application/json", {"lat": 0, "lng": 0}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part


# ---------------------------------------------------------------------------
# 6. Directions
# ---------------------------------------------------------------------------

def test_directions_json(mock_maps_ok):
    r = client.post("/", json=send_message_payload("directions", "application/json",
        {"origin": "San Francisco", "destination": "Mountain View", "mode": "driving"}), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_directions_text_output(mock_maps_ok):
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [{"data": {
            "type": "directions",
            "input": {"format": "application/json", "content": {"origin": "SF", "destination": "LA", "mode": "driving"}},
            "output": {"format": "text"},
        }, "mediaType": "application/json"}],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert "directions" in data


def test_directions_missing_origin(mock_maps_ok):
    r = client.post("/", json=send_message_payload("directions", "application/json", {"destination": "LA"}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_directions_missing_destination(mock_maps_ok):
    r = client.post("/", json=send_message_payload("directions", "application/json", {"origin": "SF"}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_directions_non_json_input(mock_maps_ok):
    r = client.post("/", json=send_message_payload("directions", "text", "SF to LA"), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_directions_api_failure(mock_maps_error):
    r = client.post("/", json=send_message_payload("directions", "application/json",
        {"origin": "Nowhere", "destination": "Somewhere", "mode": "driving"}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part


# ---------------------------------------------------------------------------
# 7. Places search
# ---------------------------------------------------------------------------

def test_places_search_text(mock_maps_ok):
    r = client.post("/", json=send_message_payload("places_search", "text", "coffee near Union Square"), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_places_search_json_with_location(mock_maps_ok):
    r = client.post("/", json=send_message_payload("places_search", "application/json",
        {"query": "pizza", "location": {"lat": 37.77, "lng": -122.41}, "radius": 1000}), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_places_search_geojson_output(mock_maps_ok):
    mock_maps_ok.get.return_value = make_mock_response("OK", {
        "results": [{"name": "Cafe", "formatted_address": "1 Main St",
                     "geometry": {"location": {"lat": 37.42, "lng": -122.08}},
                     "rating": 4.5, "place_id": "abc123"}]
    })
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [{"data": {
            "type": "places_search",
            "input": {"format": "text", "content": "restaurants"},
            "output": {"format": "application/geo+json"},
        }, "mediaType": "application/json"}],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert data["type"] == "FeatureCollection"


def test_places_search_api_failure(mock_maps_error):
    r = client.post("/", json=send_message_payload("places_search", "text", "nowhere"), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part


# ---------------------------------------------------------------------------
# 8. Place details
# ---------------------------------------------------------------------------

def test_place_details(mock_maps_ok):
    r = client.post("/", json=send_message_payload("place_details", "application/json", {"place_id": "abc"}), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_place_details_missing_place_id(mock_maps_ok):
    r = client.post("/", json=send_message_payload("place_details", "application/json", {"foo": "bar"}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_place_details_non_json_input(mock_maps_ok):
    r = client.post("/", json=send_message_payload("place_details", "text", "somewhere"), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_place_details_api_failure(mock_maps_error):
    r = client.post("/", json=send_message_payload("place_details", "application/json", {"place_id": "invalid"}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part


# ---------------------------------------------------------------------------
# 9. Distance matrix
# ---------------------------------------------------------------------------

def test_distance_matrix(mock_maps_ok):
    r = client.post("/", json=send_message_payload("distance_matrix", "application/json",
        {"origins": ["SF"], "destinations": ["Mountain View"], "mode": "driving"}), headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_distance_matrix_missing_origins(mock_maps_ok):
    r = client.post("/", json=send_message_payload("distance_matrix", "application/json", {"destinations": ["LA"]}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_distance_matrix_missing_destinations(mock_maps_ok):
    r = client.post("/", json=send_message_payload("distance_matrix", "application/json", {"origins": ["SF"]}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_distance_matrix_non_json_input(mock_maps_ok):
    r = client.post("/", json=send_message_payload("distance_matrix", "text", "SF to LA"), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_distance_matrix_api_failure(mock_maps_error):
    r = client.post("/", json=send_message_payload("distance_matrix", "application/json",
        {"origins": ["Nowhere"], "destinations": ["Somewhere"]}), headers=headers())
    part = r.json()["result"]["message"]["parts"][0]
    assert "text" in part


# ---------------------------------------------------------------------------
# 10. Input parsing
# ---------------------------------------------------------------------------

def test_unsupported_task_type_returns_error(mock_maps_ok):
    r = client.post("/", json=send_message_payload("fly_me_to_the_moon", "text", "test"), headers=headers())
    result = r.json()
    # Should return error message (not JSON-RPC error, but agent error in message)
    assert "result" in result
    part = result["result"]["message"]["parts"][0]
    assert "text" in part and "Error" in part["text"]


def test_text_part_parsed_as_geocode(mock_maps_ok):
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [{"text": '{"type":"geocode","input":{"format":"text","content":"Times Square"}}'}],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


# ---------------------------------------------------------------------------
# 11. Config validators
# ---------------------------------------------------------------------------

def test_config_rejects_empty_google_maps_key():
    with pytest.raises(Exception):
        Config(google_maps_api_key="", api_key="key", log_level="INFO", allowed_ips="")


def test_config_rejects_invalid_log_level():
    with pytest.raises(Exception):
        Config(google_maps_api_key="somekey", api_key="key", log_level="VERBOSE", allowed_ips="")


# ---------------------------------------------------------------------------
# 12. GoogleMapsService unit tests
# ---------------------------------------------------------------------------

def test_google_maps_service_client_returns_async_client():
    svc = GoogleMapsService("fake_key")
    result = svc._client()
    assert isinstance(result, httpx.AsyncClient)


async def test_google_maps_service_geocode(mock_maps_ok):
    result = await maps_service.execute("geocode", "text", "Mountain View, CA")
    assert result["status"] == "OK"


async def test_google_maps_service_unknown_type():
    with pytest.raises(ValueError, match="Unknown task type"):
        await maps_service.execute("nonexistent", "text", "test")


# ---------------------------------------------------------------------------
# 13. Coverage gap tests
# ---------------------------------------------------------------------------

def test_plain_text_input_treated_as_geocode(mock_maps_ok):
    """Plain-text parts (not JSON) fall back to geocode."""
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [{"text": "1600 Amphitheatre Parkway Mountain View CA"}],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_data_part_without_task_type_falls_back_to_text(mock_maps_ok):
    """Data part with no 'type' field falls back to text parsing, then geocode."""
    payload = jsonrpc("SendMessage", {"message": {
        "messageId": "m", "role": "ROLE_USER",
        "parts": [
            {"data": {"no_type_here": True}, "mediaType": "application/json"},
            {"text": '{"type":"geocode","input":{"format":"text","content":"Times Square"}}'},
        ],
    }})
    r = client.post("/", json=payload, headers=headers())
    data = assert_message_response(r.json())
    assert data["status"] == "OK"


def test_cancel_task(mock_maps_ok):
    """CancelTask returns a valid JSON-RPC response."""
    payload = jsonrpc("CancelTask", {"id": str(uuid.uuid4())})
    r = client.post("/", json=payload, headers=headers())
    result = r.json()
    # SDK may return error (task not found) or success; either is a valid JSON-RPC response
    assert "jsonrpc" in result
    assert result.get("id") == "1"


def test_ip_allowlist_blocks_request():
    """IP allowlist middleware returns 403 for unlisted IPs."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route
    from starlette.testclient import TestClient as SC
    from main import SecurityMiddleware, health, get_well_known_agent_card, jsonrpc_routes
    import main as m

    original = m.config.allowed_ips
    m.config.__dict__["allowed_ips"] = "10.0.0.1"

    mini = Starlette(
        routes=[Route("/health", health, methods=["GET"]), *jsonrpc_routes],
        middleware=[Middleware(SecurityMiddleware)],
    )
    tc = SC(mini)
    r = tc.get("/health")
    assert r.status_code == 403

    m.config.__dict__["allowed_ips"] = original
