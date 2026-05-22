import logging
import os
import re
import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional, Union

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.middleware.base import BaseHTTPMiddleware

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    api_key: str = ""
    google_maps_api_key: str = ""
    log_level: str = "INFO"
    allowed_ips: str = ""

    @field_validator("google_maps_api_key")
    @classmethod
    def google_maps_key_must_be_set(cls, v: str) -> str:
        if not v:
            raise ValueError("GOOGLE_MAPS_API_KEY must be set before starting the server")
        return v

    @field_validator("log_level")
    @classmethod
    def log_level_must_be_valid(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        v = v.upper()
        if v not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return v

    @property
    def allowed_ip_set(self) -> set:
        return {ip.strip() for ip in self.allowed_ips.split(",") if ip.strip()}


# Instantiate config first so LOG_LEVEL is available for logging setup.
# pydantic-settings reads .env automatically — no manual load_dotenv() needed.
config = Config()

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

if not config.api_key:
    logger.warning("API_KEY is not set — all authenticated endpoints will reject requests")

# ---------------------------------------------------------------------------
# A2A Protocol models
# ---------------------------------------------------------------------------

SUPPORTED_TASK_TYPES = frozenset({
    "geocode",
    "reverse_geocode",
    "directions",
    "places_search",
    "place_details",
    "distance_matrix",
})


class TaskStatus(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class InputFormat(str, Enum):
    TEXT = "text"
    JSON = "application/json"
    MARKDOWN = "text/markdown"


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "application/json"
    MARKDOWN = "text/markdown"
    GEOJSON = "application/geo+json"


class TaskInput(BaseModel):
    format: InputFormat
    content: Union[str, Dict[str, Any]]

    @field_validator("content")
    @classmethod
    def content_must_not_be_empty(cls, v: Union[str, Dict[str, Any]]) -> Union[str, Dict[str, Any]]:
        if isinstance(v, str) and not v.strip():
            raise ValueError("content must not be empty")
        if isinstance(v, dict) and not v:
            raise ValueError("content dict must not be empty")
        return v


class TaskOutput(BaseModel):
    format: OutputFormat
    content: Union[str, Dict[str, Any]]


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: str
    status: TaskStatus = TaskStatus.CREATED
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    input: TaskInput
    output: Optional[TaskOutput] = None

    @field_validator("type")
    @classmethod
    def type_must_be_supported(cls, v: str) -> str:
        if v not in SUPPORTED_TASK_TYPES:
            raise ValueError(f"type must be one of {sorted(SUPPORTED_TASK_TYPES)}")
        return v


# ---------------------------------------------------------------------------
# Agent Card
# ---------------------------------------------------------------------------

AGENT_CARD = {
    "schema_version": "v1",
    "name": "Google Maps A2A",
    "description": "An A2A-compliant agent that provides Google Maps capabilities",
    "version": "1.0.0",
    "contact": "https://github.com/yourusername/google-maps-a2a",
    "auth": {
        "type": "api_key",
        "header_name": "X-API-Key",
    },
    "input_formats": [
        {"format": "text", "description": "Natural language query for maps operations"},
        {"format": "application/json", "description": "Structured data for maps operations"},
    ],
    "output_formats": [
        {"format": "text", "description": "Text response with maps information"},
        {"format": "application/json", "description": "JSON response with structured maps data"},
        {"format": "application/geo+json", "description": "GeoJSON formatted location data"},
    ],
    "tasks": [
        {
            "type": "geocode",
            "description": "Convert addresses to latitude and longitude coordinates",
            "input_formats": ["text", "application/json"],
            "output_formats": ["application/json", "application/geo+json"],
        },
        {
            "type": "reverse_geocode",
            "description": "Convert coordinates to addresses",
            "input_formats": ["application/json"],
            "output_formats": ["application/json", "text"],
        },
        {
            "type": "directions",
            "description": "Get directions between locations",
            "input_formats": ["application/json"],
            "output_formats": ["application/json", "text"],
        },
        {
            "type": "places_search",
            "description": "Search for places using Google Places API",
            "input_formats": ["text", "application/json"],
            "output_formats": ["application/json", "application/geo+json"],
        },
        {
            "type": "place_details",
            "description": "Get detailed information about a specific place",
            "input_formats": ["application/json"],
            "output_formats": ["application/json"],
        },
        {
            "type": "distance_matrix",
            "description": "Calculate travel distance and time between points",
            "input_formats": ["application/json"],
            "output_formats": ["application/json"],
        },
    ],
}

# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------

class TaskRepository:
    """In-memory task storage."""

    def __init__(self) -> None:
        self._store: Dict[str, Task] = {}

    def save(self, task: Task) -> Task:
        self._store[task.id] = task
        return task

    def get(self, task_id: str) -> Optional[Task]:
        return self._store.get(task_id)

    def require(self, task_id: str) -> Task:
        task = self._store.get(task_id)
        if task is None:
            logger.warning("Task not found id=%s", task_id)
            raise HTTPException(status_code=404, detail="Task not found")
        return task


# ---------------------------------------------------------------------------
# Google Maps service
# ---------------------------------------------------------------------------

class GoogleMapsService:
    """Wraps all Google Maps API calls as async methods."""

    BASE_URL = "https://maps.googleapis.com/maps/api"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.BASE_URL,
            params={"key": self._api_key},
        )

    async def execute(self, task: Task) -> TaskOutput:
        handlers = {
            "geocode": self.geocode,
            "reverse_geocode": self.reverse_geocode,
            "directions": self.directions,
            "places_search": self.places_search,
            "place_details": self.place_details,
            "distance_matrix": self.distance_matrix,
        }
        handler = handlers[task.type]
        async with self._client() as client:
            logger.debug("Calling Google Maps API type=%s id=%s", task.type, task.id)
            return await handler(task, client)

    async def geocode(self, task: Task, client: httpx.AsyncClient) -> TaskOutput:
        if task.input.format == InputFormat.TEXT:
            address = task.input.content
        else:
            address = task.input.content.get("address", "")

        response = await client.get("/geocode/json", params={"address": address})
        data = response.json()

        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise HTTPException(status_code=400, detail=f"Geocoding failed: {data.get('status')}")

        if task.output and task.output.format == OutputFormat.GEOJSON:
            result = data.get("results", [])[0]
            location = result.get("geometry", {}).get("location", {})
            geojson = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [location.get("lng"), location.get("lat")],
                },
                "properties": {
                    "formatted_address": result.get("formatted_address"),
                    "place_id": result.get("place_id"),
                },
            }
            return TaskOutput(format=OutputFormat.GEOJSON, content=geojson)

        return TaskOutput(format=OutputFormat.JSON, content=data)

    async def reverse_geocode(self, task: Task, client: httpx.AsyncClient) -> TaskOutput:
        if task.input.format != InputFormat.JSON:
            raise HTTPException(status_code=400, detail="Reverse geocoding requires JSON input")

        lat = task.input.content.get("lat")
        lng = task.input.content.get("lng")

        if lat is None or lng is None:
            raise HTTPException(status_code=400, detail="Latitude and longitude required")

        response = await client.get("/geocode/json", params={"latlng": f"{lat},{lng}"})
        data = response.json()

        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise HTTPException(status_code=400, detail=f"Reverse geocoding failed: {data.get('status')}")

        if task.output and task.output.format == OutputFormat.TEXT:
            result = data.get("results", [])[0]
            return TaskOutput(
                format=OutputFormat.TEXT,
                content=result.get("formatted_address", "Address not found"),
            )

        return TaskOutput(format=OutputFormat.JSON, content=data)

    async def directions(self, task: Task, client: httpx.AsyncClient) -> TaskOutput:
        if task.input.format != InputFormat.JSON:
            raise HTTPException(status_code=400, detail="Directions requires JSON input")

        origin = task.input.content.get("origin")
        destination = task.input.content.get("destination")
        mode = task.input.content.get("mode", "driving")

        if not origin or not destination:
            raise HTTPException(status_code=400, detail="Origin and destination required")

        response = await client.get(
            "/directions/json",
            params={"origin": origin, "destination": destination, "mode": mode},
        )
        data = response.json()

        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise HTTPException(status_code=400, detail=f"Directions failed: {data.get('status')}")

        if task.output and task.output.format == OutputFormat.TEXT:
            steps = []
            for route in data.get("routes", []):
                for leg in route.get("legs", []):
                    for i, step in enumerate(leg.get("steps", [])):
                        clean = re.sub(r"<[^>]+>", " ", step.get("html_instructions", ""))
                        clean = re.sub(r"\s+", " ", clean).strip()
                        steps.append(f"{i + 1}. {clean}")
            return TaskOutput(format=OutputFormat.TEXT, content="\n".join(steps))

        return TaskOutput(format=OutputFormat.JSON, content=data)

    async def places_search(self, task: Task, client: httpx.AsyncClient) -> TaskOutput:
        if task.input.format == InputFormat.TEXT:
            params: Dict[str, Any] = {"query": task.input.content}
        else:
            query = task.input.content.get("query")
            location = task.input.content.get("location")
            radius = task.input.content.get("radius", 5000)
            params = {"query": query}
            if location:
                params["location"] = f"{location.get('lat')},{location.get('lng')}"
                params["radius"] = radius

        response = await client.get("/place/textsearch/json", params=params)
        data = response.json()

        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise HTTPException(status_code=400, detail=f"Places search failed: {data.get('status')}")

        if task.output and task.output.format == OutputFormat.GEOJSON:
            features = []
            for place in data.get("results", []):
                loc = place.get("geometry", {}).get("location", {})
                features.append({
                    "type": "Feature",
                    "geometry": {
                        "type": "Point",
                        "coordinates": [loc.get("lng"), loc.get("lat")],
                    },
                    "properties": {
                        "name": place.get("name"),
                        "address": place.get("formatted_address"),
                        "rating": place.get("rating"),
                        "place_id": place.get("place_id"),
                    },
                })
            return TaskOutput(
                format=OutputFormat.GEOJSON,
                content={"type": "FeatureCollection", "features": features},
            )

        return TaskOutput(format=OutputFormat.JSON, content=data)

    async def place_details(self, task: Task, client: httpx.AsyncClient) -> TaskOutput:
        if task.input.format != InputFormat.JSON:
            raise HTTPException(status_code=400, detail="Place details requires JSON input")

        place_id = task.input.content.get("place_id")
        if not place_id:
            raise HTTPException(status_code=400, detail="Place ID required")

        response = await client.get("/place/details/json", params={"place_id": place_id})
        data = response.json()

        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise HTTPException(status_code=400, detail=f"Place details failed: {data.get('status')}")

        return TaskOutput(format=OutputFormat.JSON, content=data)

    async def distance_matrix(self, task: Task, client: httpx.AsyncClient) -> TaskOutput:
        if task.input.format != InputFormat.JSON:
            raise HTTPException(status_code=400, detail="Distance matrix requires JSON input")

        origins = task.input.content.get("origins", [])
        destinations = task.input.content.get("destinations", [])
        mode = task.input.content.get("mode", "driving")

        if not origins or not destinations:
            raise HTTPException(status_code=400, detail="Origins and destinations required")

        response = await client.get(
            "/distancematrix/json",
            params={
                "origins": "|".join(origins),
                "destinations": "|".join(destinations),
                "mode": mode,
            },
        )
        data = response.json()

        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise HTTPException(status_code=400, detail=f"Distance matrix failed: {data.get('status')}")

        return TaskOutput(format=OutputFormat.JSON, content=data)


# ---------------------------------------------------------------------------
# IP allowlist middleware
# ---------------------------------------------------------------------------

class IPAllowlistMiddleware(BaseHTTPMiddleware):
    """Restricts inbound requests to a set of allowed IP addresses.

    Controlled by the ALLOWED_IPS environment variable (comma-separated).
    If ALLOWED_IPS is empty or unset, all IPs are allowed.
    """

    def __init__(self, app: Any, allowed_ips: set) -> None:
        super().__init__(app)
        self._allowed_ips = allowed_ips

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        if self._allowed_ips and request.client.host not in self._allowed_ips:
            logger.warning("Request rejected: IP %s not in allowlist", request.client.host)
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        return await call_next(request)


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

task_repo = TaskRepository()
maps_service = GoogleMapsService(config.google_maps_api_key)

logger.info("Google Maps A2A Server starting log_level=%s", config.log_level)

# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------

app = FastAPI(title="Google Maps A2A Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if config.allowed_ip_set:
    app.add_middleware(IPAllowlistMiddleware, allowed_ips=config.allowed_ip_set)
    logger.info("IP allowlist active: %s", config.allowed_ip_set)

# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

api_key_header = APIKeyHeader(name="X-API-Key")


async def verify_api_key(api_key: str = Depends(api_key_header)) -> str:
    if api_key != config.api_key:
        logger.warning("Authentication failed: invalid API key")
        raise HTTPException(status_code=401, detail="Invalid API key")
    return api_key


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def root() -> Dict[str, str]:
    return {"message": "Google Maps A2A Server", "version": "1.0.0"}


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/agent-card")
async def get_agent_card() -> Dict[str, Any]:
    return AGENT_CARD


@app.get("/.well-known/agent.json")
async def get_well_known_agent() -> Dict[str, Any]:
    """A2A protocol standard discovery endpoint."""
    return AGENT_CARD


@app.post("/tasks", response_model=Task, dependencies=[Depends(verify_api_key)])
async def create_task(task: Task) -> Task:
    logger.info("Task created id=%s type=%s", task.id, task.type)
    return task_repo.save(task)


@app.get("/tasks/{task_id}", response_model=Task, dependencies=[Depends(verify_api_key)])
async def get_task(task_id: str) -> Task:
    return task_repo.require(task_id)


@app.put("/tasks/{task_id}/execute", response_model=Task, dependencies=[Depends(verify_api_key)])
async def execute_task(task_id: str) -> Task:
    task = task_repo.require(task_id)
    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now().isoformat()
    logger.info("Task executing id=%s type=%s", task.id, task.type)
    try:
        task.output = await maps_service.execute(task)
        task.status = TaskStatus.COMPLETED
        logger.info("Task completed id=%s", task.id)
    except Exception as e:
        logger.error("Task failed id=%s", task.id, exc_info=True)
        task.status = TaskStatus.FAILED
        task.output = TaskOutput(
            format=OutputFormat.TEXT,
            content=f"Error executing task: {e.detail if isinstance(e, HTTPException) else str(e)}",
        )
    task.updated_at = datetime.now().isoformat()
    task_repo.save(task)
    return task


@app.post("/tasks/run", response_model=Task, dependencies=[Depends(verify_api_key)])
async def run_task(task: Task) -> Task:
    """Create and execute a task in a single request (primary Kore AI integration endpoint)."""
    task.status = TaskStatus.IN_PROGRESS
    task.updated_at = datetime.now().isoformat()
    logger.info("Task run (single-step) id=%s type=%s", task.id, task.type)
    try:
        task.output = await maps_service.execute(task)
        task.status = TaskStatus.COMPLETED
        logger.info("Task run completed id=%s", task.id)
    except Exception as e:
        logger.error("Task run failed id=%s", task.id, exc_info=True)
        task.status = TaskStatus.FAILED
        task.output = TaskOutput(
            format=OutputFormat.TEXT,
            content=f"Error executing task: {e.detail if isinstance(e, HTTPException) else str(e)}",
        )
    task.updated_at = datetime.now().isoformat()
    task_repo.save(task)
    return task


if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
