"""
Unit tests for the Google Maps A2A v1 server.

Tests run against the local Starlette app via Starlette TestClient.
All Google Maps HTTP calls and ADK/Gemini calls are mocked.
Input is text/plain; responses are text/plain messages.
"""
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.testclient import TestClient

pytestmark = pytest.mark.local

# Set environment variables BEFORE importing main
os.environ["A2A_API_KEY"] = "test_api_key"
os.environ["MAPS_A2A_MAPS_KEY"] = "test_maps_a2a_maps_key"
os.environ["MAPS_A2A_GEMINI_KEY"] = "test_maps_a2a_gemini_key"
os.environ["LOG_LEVEL"] = "DEBUG"

from agent import GoogleMapsAgent  # noqa: E402
from agent_executor import GoogleMapsAgentExecutor  # noqa: E402
from main import (  # noqa: E402
    Config,
    GoogleMapsService,
    AGENT_CARD,
    AGENT_CARD_DICT,
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


def send_text_payload(query: str) -> dict:
    return jsonrpc("SendMessage", {
        "message": {
            "messageId": str(uuid.uuid4()),
            "role": "ROLE_USER",
            "parts": [{"text": query}],
        }
    })


def make_mock_maps_response(status: str = "OK") -> MagicMock:
    mock = MagicMock()
    mock.status_code = 200
    data: dict = {"status": status}
    if status == "OK":
        data.update({
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


def assert_text_message(result: dict) -> str:
    """Assert JSON-RPC success with a message containing a text part; return the text."""
    assert "error" not in result, f"Unexpected error: {result.get('error')}"
    assert "result" in result
    r = result["result"]
    assert "message" in r, f"Expected 'message' in result, got: {list(r.keys())}"
    parts = r["message"].get("parts", [])
    assert parts, "Response message has no parts"
    assert "text" in parts[0], f"Expected text part, got: {list(parts[0].keys())}"
    return parts[0]["text"]


# ---------------------------------------------------------------------------
# ADK mock fixture
# ---------------------------------------------------------------------------

ADK_RESPONSE = "The coordinates are 37.4224864, -122.0855962 (Mountain View, CA)."


class FakeADKEvent:
    def __init__(self, text: str = ADK_RESPONSE) -> None:
        self.content = MagicMock()
        self.content.parts = [MagicMock(text=text)]

    def is_final_response(self) -> bool:
        return True


async def _fake_run_async(*args, **kwargs):
    yield FakeADKEvent()


@pytest.fixture
def mock_adk():
    """Mock the ADK Runner so tests don't make real Gemini calls."""
    from agent_executor import GoogleMapsAgentExecutor
    from main import request_handler

    executor = request_handler.agent_executor
    fake_session = MagicMock()
    fake_session.id = "test-session-id"

    with (
        patch.object(executor._runner, "run_async", side_effect=_fake_run_async),
        patch.object(executor._runner.session_service, "get_session", new=AsyncMock(return_value=None)),
        patch.object(executor._runner.session_service, "create_session", new=AsyncMock(return_value=fake_session)),
    ):
        yield executor


@pytest.fixture
def mock_maps_ok(mock_adk):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=make_mock_maps_response())
    with patch.object(maps_service, "_client", return_value=mock_client):
        yield mock_client


@pytest.fixture
def mock_maps_error(mock_adk):
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=make_mock_maps_response(status="ZERO_RESULTS"))
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
    assert skill_ids == {
        "geocode", "reverse_geocode", "directions",
        "places_search", "place_details", "distance_matrix",
    }
    assert card["capabilities"]["streaming"] is False
    assert card["supportedInterfaces"][0]["protocolBinding"] == "jsonrpc"


def test_agent_card_text_plain_only():
    card = client.get("/.well-known/agent-card.json").json()
    for skill in card["skills"]:
        assert skill.get("inputModes") == ["text/plain"], (
            f"Skill '{skill['id']}' should have only text/plain input"
        )
        assert skill.get("outputModes") == ["text/plain"], (
            f"Skill '{skill['id']}' should have only text/plain output"
        )


def test_agent_card_has_api_key_security_scheme():
    card = client.get("/.well-known/agent-card.json").json()
    assert "apiKey" in card["securitySchemes"]
    scheme = card["securitySchemes"]["apiKey"]["apiKeySecurityScheme"]
    assert scheme["name"] == "X-API-Key"
    assert scheme["location"] == "header"


# ---------------------------------------------------------------------------
# 2. Authentication
# ---------------------------------------------------------------------------

def test_missing_api_key_returns_403():
    r = client.post("/", json=send_text_payload("test"),
                    headers={"Content-Type": "application/json", "A2A-Version": "1.0"})
    assert r.status_code == 403


def test_wrong_api_key_returns_401():
    h = headers()
    h["X-API-Key"] = "wrong-key"
    r = client.post("/", json=send_text_payload("test"), headers=h)
    assert r.status_code == 401


def test_version_header_missing_returns_version_error(mock_maps_ok):
    h = headers(include_version=False)
    r = client.post("/", json=send_text_payload("test"), headers=h)
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
    assert r.json()["error"]["code"] == -32601


def test_well_known_requires_no_auth():
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 4–9. Skill execution (ADK + Maps mocked)
# ---------------------------------------------------------------------------

def test_geocode(mock_maps_ok):
    r = client.post("/", json=send_text_payload("What are the coordinates of Mountain View, CA?"), headers=headers())
    text = assert_text_message(r.json())
    assert len(text) > 0


def test_reverse_geocode(mock_maps_ok):
    r = client.post("/", json=send_text_payload("What address is at 37.42, -122.08?"), headers=headers())
    assert_text_message(r.json())


def test_directions(mock_maps_ok):
    r = client.post("/", json=send_text_payload("How do I drive from San Francisco to Mountain View?"), headers=headers())
    assert_text_message(r.json())


def test_places_search(mock_maps_ok):
    r = client.post("/", json=send_text_payload("Find coffee shops near Union Square San Francisco"), headers=headers())
    assert_text_message(r.json())


def test_place_details(mock_maps_ok):
    r = client.post("/", json=send_text_payload("Tell me about the Googleplex"), headers=headers())
    assert_text_message(r.json())


def test_distance_matrix(mock_maps_ok):
    r = client.post("/", json=send_text_payload("How far is it from San Francisco to Mountain View by car?"), headers=headers())
    assert_text_message(r.json())


# ---------------------------------------------------------------------------
# 10. CancelTask
# ---------------------------------------------------------------------------

def test_cancel_task(mock_maps_ok):
    payload = jsonrpc("CancelTask", {"id": str(uuid.uuid4())})
    r = client.post("/", json=payload, headers=headers())
    result = r.json()
    assert "jsonrpc" in result
    assert result.get("id") == "1"


# ---------------------------------------------------------------------------
# 11. Config validators
# ---------------------------------------------------------------------------

def test_config_rejects_empty_maps_key():
    with pytest.raises(Exception):
        Config(maps_a2a_maps_key="", maps_a2a_gemini_key="key", log_level="INFO", allowed_ips="")


def test_config_rejects_empty_gemini_key():
    with pytest.raises(Exception):
        Config(maps_a2a_maps_key="key", maps_a2a_gemini_key="", log_level="INFO", allowed_ips="")


def test_config_rejects_invalid_log_level():
    with pytest.raises(Exception):
        Config(google_maps_api_key="key", gemini_api_key="key", log_level="VERBOSE", allowed_ips="")


# ---------------------------------------------------------------------------
# 12. GoogleMapsService unit tests
# ---------------------------------------------------------------------------

def test_google_maps_service_client_returns_async_client():
    svc = GoogleMapsService("fake_key")
    result = svc._client()
    assert isinstance(result, httpx.AsyncClient)


async def test_service_geocode_text(mock_maps_ok):
    result = await maps_service.execute("geocode", "text", "Mountain View, CA")
    assert result["status"] == "OK"


async def test_service_geocode_json(mock_maps_ok):
    result = await maps_service.execute("geocode", "application/json", {"address": "Mountain View"})
    assert result["status"] == "OK"


async def test_service_geocode_geojson(mock_maps_ok):
    result = await maps_service.execute("geocode", "text", "Mountain View", output_format="application/geo+json")
    assert result["type"] == "Feature"


async def test_service_reverse_geocode(mock_maps_ok):
    result = await maps_service.execute("reverse_geocode", "application/json", {"lat": 37.42, "lng": -122.08})
    assert result["status"] == "OK"


async def test_service_reverse_geocode_text_output(mock_maps_ok):
    result = await maps_service.execute("reverse_geocode", "application/json", {"lat": 37.42, "lng": -122.08}, output_format="text")
    assert "address" in result


async def test_service_directions(mock_maps_ok):
    result = await maps_service.execute("directions", "application/json",
                                        {"origin": "SF", "destination": "LA", "mode": "driving"})
    assert result["status"] == "OK"


async def test_service_places_search(mock_maps_ok):
    result = await maps_service.execute("places_search", "text", "coffee")
    assert result["status"] == "OK"


async def test_service_place_details(mock_maps_ok):
    result = await maps_service.execute("place_details", "application/json", {"place_id": "abc"})
    assert result["status"] == "OK"


async def test_service_distance_matrix(mock_maps_ok):
    result = await maps_service.execute("distance_matrix", "application/json",
                                        {"origins": ["SF"], "destinations": ["LA"], "mode": "driving"})
    assert result["status"] == "OK"


async def test_service_unknown_type():
    with pytest.raises(ValueError, match="Unknown task type"):
        await maps_service.execute("nonexistent", "text", "test")


async def test_service_api_error(mock_maps_error):
    with pytest.raises(Exception):
        await maps_service.execute("geocode", "text", "Nowhere")


# ---------------------------------------------------------------------------
# 13. GoogleMapsAgent unit tests
# ---------------------------------------------------------------------------

def test_agent_builds_successfully():
    agent = GoogleMapsAgent(maps_service)
    assert agent.agent is not None
    assert agent.agent.name == "google_maps_agent"
    assert len(agent.agent.tools) == 6


# ---------------------------------------------------------------------------
# 14. GoogleMapsAgentExecutor unit tests
# ---------------------------------------------------------------------------

def test_executor_has_runner():
    from main import request_handler
    executor = request_handler.agent_executor
    assert executor._runner is not None


async def test_executor_cancel_raises():
    from main import request_handler
    mock_ctx = MagicMock()
    mock_ctx.task_id = "test"
    with pytest.raises(NotImplementedError):
        await request_handler.agent_executor.cancel(mock_ctx, None)


# ---------------------------------------------------------------------------
# 15. IP allowlist
# ---------------------------------------------------------------------------

def test_ip_allowlist_blocks_request():
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route
    from starlette.testclient import TestClient as SC
    from main import SecurityMiddleware, health, jsonrpc_routes
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
