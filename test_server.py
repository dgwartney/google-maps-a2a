import os
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient

# Set environment variables before importing the app
os.environ["API_KEY"] = "test_api_key"
os.environ["GOOGLE_MAPS_API_KEY"] = "test_google_maps_api_key"
os.environ["LOG_LEVEL"] = "DEBUG"

from main import (  # noqa: E402
    Config,
    GoogleMapsService,
    IPAllowlistMiddleware,
    TaskInput,
    TaskRepository,
    app,
    config,
    maps_service,
    task_repo,
    verify_api_key,
)

TEST_API_KEY = "test_api_key"

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def task_payload(
    task_type: str = "geocode",
    fmt: str = "text",
    content: object = "1600 Amphitheatre Parkway, Mountain View, CA",
    output_format: str | None = None,
) -> dict:
    payload: dict = {
        "id": str(uuid.uuid4()),
        "type": task_type,
        "status": "created",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "input": {"format": fmt, "content": content},
    }
    if output_format:
        payload["output"] = {"format": output_format, "content": ""}
    return payload


def auth_headers() -> dict:
    return {"X-API-Key": TEST_API_KEY}


# ---------------------------------------------------------------------------
# Mock factory
# ---------------------------------------------------------------------------

def make_mock_response(status: str = "OK", extra: dict | None = None) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    data: dict = {"status": status}
    if status == "OK":
        data.update(
            extra
            or {
                "results": [
                    {
                        "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
                        "geometry": {"location": {"lat": 37.4224764, "lng": -122.0842499}},
                        "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
                    }
                ],
                "routes": [
                    {
                        "legs": [
                            {
                                "steps": [
                                    {"html_instructions": "<b>Head north</b> on Main St"},
                                    {"html_instructions": "Turn <b>right</b> on 1st Ave"},
                                ]
                            }
                        ]
                    }
                ],
                "rows": [{"elements": [{"distance": {"text": "10 km"}, "duration": {"text": "15 mins"}, "status": "OK"}]}],
                "destination_addresses": ["Mountain View, CA, USA"],
                "origin_addresses": ["San Francisco, CA, USA"],
            }
        )
    mock_resp.json.return_value = data
    return mock_resp


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_auth_override():
    """Apply auth bypass by default; auth tests remove it."""
    app.dependency_overrides[verify_api_key] = lambda: TEST_API_KEY
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def real_auth():
    """Remove auth bypass so real API key checking is exercised."""
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides[verify_api_key] = lambda: TEST_API_KEY


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
# Infrastructure
# ---------------------------------------------------------------------------

def test_root():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Google Maps A2A Server"
    assert "version" in data


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# Agent card
# ---------------------------------------------------------------------------

def test_get_agent_card_structure():
    response = client.get("/agent-card")
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Google Maps A2A"
    task_types = {t["type"] for t in card["tasks"]}
    assert task_types == {
        "geocode", "reverse_geocode", "directions",
        "places_search", "place_details", "distance_matrix",
    }
    assert card["auth"]["type"] == "api_key"
    assert card["auth"]["header_name"] == "X-API-Key"


def test_well_known_agent_json():
    """A2A protocol standard discovery endpoint."""
    response = client.get("/.well-known/agent.json")
    assert response.status_code == 200
    card = response.json()
    assert card["name"] == "Google Maps A2A"
    assert {t["type"] for t in card["tasks"]} == {
        "geocode", "reverse_geocode", "directions",
        "places_search", "place_details", "distance_matrix",
    }


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def test_missing_api_key(real_auth):
    response = client.post("/tasks", json=task_payload())
    assert response.status_code == 403


def test_invalid_api_key(real_auth):
    response = client.post("/tasks", json=task_payload(), headers={"X-API-Key": "wrong"})
    assert response.status_code == 401


def test_valid_api_key_accepted(real_auth):
    response = client.post("/tasks", json=task_payload(), headers=auth_headers())
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Task CRUD
# ---------------------------------------------------------------------------

def test_create_task_valid():
    payload = task_payload()
    response = client.post("/tasks", json=payload, headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == payload["id"]
    assert data["type"] == "geocode"
    assert data["status"] == "created"


def test_create_task_invalid_type():
    payload = task_payload(task_type="fly_me_to_the_moon")
    response = client.post("/tasks", json=payload, headers=auth_headers())
    assert response.status_code == 422


def test_get_task_found():
    payload = task_payload()
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.get(f"/tasks/{payload['id']}", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["id"] == payload["id"]


def test_get_task_not_found():
    response = client.get("/tasks/does-not-exist", headers=auth_headers())
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Geocode handler
# ---------------------------------------------------------------------------

def test_geocode_text_input_json_output(mock_maps_ok):
    payload = task_payload(task_type="geocode", fmt="text", content="Times Square, New York")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["output"]["format"] == "application/json"


def test_geocode_json_input_json_output(mock_maps_ok):
    payload = task_payload(
        task_type="geocode",
        fmt="application/json",
        content={"address": "Times Square, New York"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_geocode_geojson_output(mock_maps_ok):
    payload = task_payload(
        task_type="geocode",
        fmt="text",
        content="Times Square",
        output_format="application/geo+json",
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["output"]["format"] == "application/geo+json"
    assert data["output"]["content"]["type"] == "Feature"
    assert data["output"]["content"]["geometry"]["type"] == "Point"


def test_geocode_api_failure(mock_maps_error):
    payload = task_payload(task_type="geocode", fmt="text", content="Nowhere")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Reverse geocode handler
# ---------------------------------------------------------------------------

def test_reverse_geocode_json_output(mock_maps_ok):
    payload = task_payload(
        task_type="reverse_geocode",
        fmt="application/json",
        content={"lat": 37.4224764, "lng": -122.0842499},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["output"]["format"] == "application/json"


def test_reverse_geocode_text_output(mock_maps_ok):
    payload = task_payload(
        task_type="reverse_geocode",
        fmt="application/json",
        content={"lat": 37.4224764, "lng": -122.0842499},
        output_format="text",
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["output"]["format"] == "text"
    assert isinstance(data["output"]["content"], str)


def test_reverse_geocode_missing_lat_lng(mock_maps_ok):
    payload = task_payload(
        task_type="reverse_geocode",
        fmt="application/json",
        content={"foo": "bar"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_reverse_geocode_non_json_input(mock_maps_ok):
    payload = task_payload(task_type="reverse_geocode", fmt="text", content="37.42,-122.08")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_reverse_geocode_api_failure(mock_maps_error):
    payload = task_payload(
        task_type="reverse_geocode",
        fmt="application/json",
        content={"lat": 0, "lng": 0},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Directions handler
# ---------------------------------------------------------------------------

def test_directions_json_output(mock_maps_ok):
    payload = task_payload(
        task_type="directions",
        fmt="application/json",
        content={"origin": "San Francisco, CA", "destination": "Los Angeles, CA"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


def test_directions_text_output(mock_maps_ok):
    payload = task_payload(
        task_type="directions",
        fmt="application/json",
        content={"origin": "San Francisco, CA", "destination": "Los Angeles, CA"},
        output_format="text",
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    data = response.json()
    assert data["output"]["format"] == "text"
    assert "1." in data["output"]["content"]


def test_directions_missing_origin(mock_maps_ok):
    payload = task_payload(
        task_type="directions",
        fmt="application/json",
        content={"destination": "Los Angeles, CA"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_directions_missing_destination(mock_maps_ok):
    payload = task_payload(
        task_type="directions",
        fmt="application/json",
        content={"origin": "San Francisco, CA"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_directions_non_json_input(mock_maps_ok):
    payload = task_payload(task_type="directions", fmt="text", content="SF to LA")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_directions_api_failure(mock_maps_error):
    payload = task_payload(
        task_type="directions",
        fmt="application/json",
        content={"origin": "Nowhere", "destination": "Somewhere"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Places search handler
# ---------------------------------------------------------------------------

def test_places_search_text_input_json_output(mock_maps_ok):
    payload = task_payload(task_type="places_search", fmt="text", content="pizza near Times Square")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "completed"
    assert response.json()["output"]["format"] == "application/json"


def test_places_search_json_input_with_location(mock_maps_ok):
    payload = task_payload(
        task_type="places_search",
        fmt="application/json",
        content={"query": "coffee", "location": {"lat": 37.42, "lng": -122.08}, "radius": 1000},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "completed"


def test_places_search_geojson_output(mock_maps_ok):
    payload = task_payload(
        task_type="places_search",
        fmt="text",
        content="restaurants",
        output_format="application/geo+json",
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    data = response.json()
    assert data["output"]["format"] == "application/geo+json"
    assert data["output"]["content"]["type"] == "FeatureCollection"


def test_places_search_api_failure(mock_maps_error):
    payload = task_payload(task_type="places_search", fmt="text", content="nowhere special")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Place details handler
# ---------------------------------------------------------------------------

def test_place_details_json_output(mock_maps_ok):
    payload = task_payload(
        task_type="place_details",
        fmt="application/json",
        content={"place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "completed"


def test_place_details_missing_place_id(mock_maps_ok):
    payload = task_payload(
        task_type="place_details",
        fmt="application/json",
        content={"foo": "bar"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_place_details_non_json_input(mock_maps_ok):
    payload = task_payload(task_type="place_details", fmt="text", content="some place")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_place_details_api_failure(mock_maps_error):
    mock_maps_error.get.return_value = make_mock_response(
        status="NOT_FOUND",
        extra={"result": {}},
    )
    payload = task_payload(
        task_type="place_details",
        fmt="application/json",
        content={"place_id": "invalid_id"},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Distance matrix handler
# ---------------------------------------------------------------------------

def test_distance_matrix_json_output(mock_maps_ok):
    payload = task_payload(
        task_type="distance_matrix",
        fmt="application/json",
        content={"origins": ["San Francisco, CA"], "destinations": ["Los Angeles, CA"]},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "completed"


def test_distance_matrix_missing_origins(mock_maps_ok):
    payload = task_payload(
        task_type="distance_matrix",
        fmt="application/json",
        content={"destinations": ["Los Angeles, CA"]},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_distance_matrix_missing_destinations(mock_maps_ok):
    payload = task_payload(
        task_type="distance_matrix",
        fmt="application/json",
        content={"origins": ["San Francisco, CA"]},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_distance_matrix_non_json_input(mock_maps_ok):
    payload = task_payload(task_type="distance_matrix", fmt="text", content="SF to LA")
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


def test_distance_matrix_api_failure(mock_maps_error):
    payload = task_payload(
        task_type="distance_matrix",
        fmt="application/json",
        content={"origins": ["Nowhere"], "destinations": ["Somewhere"]},
    )
    client.post("/tasks", json=payload, headers=auth_headers())
    response = client.put(f"/tasks/{payload['id']}/execute", headers=auth_headers())
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# /tasks/run combined endpoint
# ---------------------------------------------------------------------------

def test_run_task_geocode(mock_maps_ok):
    payload = task_payload(task_type="geocode", fmt="text", content="Times Square, New York")
    response = client.post("/tasks/run", json=payload, headers=auth_headers())
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["output"] is not None


def test_run_task_invalid_type():
    payload = task_payload(task_type="fly_me_to_the_moon")
    response = client.post("/tasks/run", json=payload, headers=auth_headers())
    assert response.status_code == 422


def test_run_task_returns_completed_status(mock_maps_ok):
    payload = task_payload(task_type="reverse_geocode", fmt="application/json", content={"lat": 37.42, "lng": -122.08})
    response = client.post("/tasks/run", json=payload, headers=auth_headers())
    assert response.json()["status"] == "completed"


def test_run_task_returns_failed_on_api_error(mock_maps_error):
    payload = task_payload(task_type="geocode", fmt="text", content="Nowhere")
    response = client.post("/tasks/run", json=payload, headers=auth_headers())
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


# ---------------------------------------------------------------------------
# Coverage gap: Config validators
# ---------------------------------------------------------------------------

def test_config_validator_rejects_empty_google_maps_key():
    with pytest.raises(Exception):
        Config(google_maps_api_key="", api_key="key", log_level="INFO", allowed_ips="")


def test_config_validator_rejects_invalid_log_level():
    with pytest.raises(Exception):
        Config(google_maps_api_key="somekey", api_key="key", log_level="VERBOSE", allowed_ips="")


def test_config_no_api_key_warning(caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        cfg = Config(google_maps_api_key="somekey", api_key="", log_level="INFO", allowed_ips="")
    # api_key is empty — the module-level warning is checked at import;
    # verify the config property works correctly
    assert cfg.api_key == ""


# ---------------------------------------------------------------------------
# Coverage gap: TaskInput empty content validators
# ---------------------------------------------------------------------------

def test_task_input_rejects_empty_string_content():
    with pytest.raises(Exception):
        TaskInput(format="text", content="   ")


def test_task_input_rejects_empty_dict_content():
    with pytest.raises(Exception):
        TaskInput(format="application/json", content={})


# ---------------------------------------------------------------------------
# Coverage gap: TaskRepository.get()
# ---------------------------------------------------------------------------

def test_task_repository_get_returns_none_for_missing():
    repo = TaskRepository()
    assert repo.get("nonexistent") is None


# ---------------------------------------------------------------------------
# Coverage gap: GoogleMapsService._client()
# ---------------------------------------------------------------------------

def test_google_maps_service_client_returns_async_client():
    svc = GoogleMapsService("fake_key")
    result = svc._client()
    assert isinstance(result, httpx.AsyncClient)


# ---------------------------------------------------------------------------
# Coverage gap: IPAllowlistMiddleware
# ---------------------------------------------------------------------------

def test_ip_allowlist_middleware_blocks_unlisted_ip():
    from fastapi import FastAPI
    from starlette.testclient import TestClient as StarletteClient

    mini_app = FastAPI()

    @mini_app.get("/ping")
    async def ping():
        return {"pong": True}

    mini_app.add_middleware(IPAllowlistMiddleware, allowed_ips={"10.0.0.1"})
    tc = StarletteClient(mini_app, base_url="http://testserver")
    response = tc.get("/ping")
    assert response.status_code == 403


def test_ip_allowlist_middleware_passes_listed_ip():
    from fastapi import FastAPI
    from starlette.testclient import TestClient as StarletteClient

    mini_app = FastAPI()

    @mini_app.get("/ping")
    async def ping():
        return {"pong": True}

    mini_app.add_middleware(IPAllowlistMiddleware, allowed_ips={"testclient"})
    tc = StarletteClient(mini_app, base_url="http://testserver")
    response = tc.get("/ping")
    assert response.status_code == 200


def test_ip_allowlist_middleware_allows_all_when_empty():
    from fastapi import FastAPI
    from starlette.testclient import TestClient as StarletteClient

    mini_app = FastAPI()

    @mini_app.get("/ping")
    async def ping():
        return {"pong": True}

    mini_app.add_middleware(IPAllowlistMiddleware, allowed_ips=set())
    tc = StarletteClient(mini_app, base_url="http://testserver")
    response = tc.get("/ping")
    assert response.status_code == 200
