"""
Google Maps A2A Agent — A2A Protocol v1 compliant server.

Transport:   JSON-RPC 2.0 over HTTP (POST /)
Discovery:   GET /.well-known/agent-card.json
Auth:        X-API-Key header (validated by middleware)
Framework:   a2a-sdk + Starlette
"""

import hmac
import json
import logging
import re
import uuid
from typing import Any

import httpx
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types.a2a_pb2 import (
    APIKeySecurityScheme,
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Part,
    ROLE_AGENT,
    SecurityScheme,
)
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct, Value
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    api_key: str = ""
    google_maps_api_key: str = ""
    log_level: str = "INFO"
    allowed_ips: str = ""
    base_url: str = "https://google-maps-a2a.fly.dev"

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


config = Config()

logging.basicConfig(
    level=getattr(logging, config.log_level, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

if not config.api_key:  # pragma: no cover
    logger.warning("API_KEY is not set — all authenticated endpoints will reject requests")

# ---------------------------------------------------------------------------
# Google Maps Service (handlers unchanged from original)
# ---------------------------------------------------------------------------

GOOGLE_MAPS_BASE_URL = "https://maps.googleapis.com/maps/api"


class GoogleMapsService:
    """Calls Google Maps Platform APIs."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=GOOGLE_MAPS_BASE_URL,
            params={"key": self._api_key},
        )

    async def execute(self, task_type: str, fmt: str, content: Any, output_format: str | None = None) -> dict:
        """Dispatch to the appropriate handler and return the result dict."""
        handlers = {
            "geocode": self._geocode,
            "reverse_geocode": self._reverse_geocode,
            "directions": self._directions,
            "places_search": self._places_search,
            "place_details": self._place_details,
            "distance_matrix": self._distance_matrix,
        }
        handler = handlers.get(task_type)
        if handler is None:
            raise ValueError(f"Unknown task type: {task_type}")
        async with self._client() as client:
            logger.debug("Calling Google Maps API type=%s", task_type)
            return await handler(fmt, content, output_format, client)

    async def _geocode(self, fmt: str, content: Any, output_format: str | None, client: httpx.AsyncClient) -> dict:
        address = content if fmt == "text" else content.get("address", "")
        response = await client.get("/geocode/json", params={"address": address})
        data = response.json()
        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise ValueError(f"Geocoding failed: {data.get('status')}")
        if output_format == "application/geo+json":
            result = data["results"][0]
            location = result["geometry"]["location"]
            return {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [location["lng"], location["lat"]]},
                "properties": {
                    "formatted_address": result["formatted_address"],
                    "place_id": result["place_id"],
                },
            }
        return data

    async def _reverse_geocode(self, fmt: str, content: Any, output_format: str | None, client: httpx.AsyncClient) -> dict:
        if fmt != "application/json":
            raise ValueError("Reverse geocoding requires JSON input")
        lat, lng = content.get("lat"), content.get("lng")
        if lat is None or lng is None:
            raise ValueError("Latitude and longitude required")
        response = await client.get("/geocode/json", params={"latlng": f"{lat},{lng}"})
        data = response.json()
        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise ValueError(f"Reverse geocoding failed: {data.get('status')}")
        if output_format == "text":
            return {"address": data["results"][0]["formatted_address"]}
        return data

    async def _directions(self, fmt: str, content: Any, output_format: str | None, client: httpx.AsyncClient) -> dict:
        if fmt != "application/json":
            raise ValueError("Directions requires JSON input")
        origin, destination = content.get("origin"), content.get("destination")
        if not origin or not destination:
            raise ValueError("Origin and destination required")
        mode = content.get("mode", "driving")
        response = await client.get("/directions/json", params={"origin": origin, "destination": destination, "mode": mode})
        data = response.json()
        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise ValueError(f"Directions failed: {data.get('status')}")
        if output_format == "text":
            steps = []
            for route in data.get("routes", []):
                for leg in route.get("legs", []):
                    for i, step in enumerate(leg.get("steps", [])):
                        clean = re.sub(r"<[^>]+>", " ", step.get("html_instructions", ""))
                        clean = re.sub(r"\s+", " ", clean).strip()
                        steps.append(f"{i + 1}. {clean}")
            return {"directions": "\n".join(steps)}
        return data

    async def _places_search(self, fmt: str, content: Any, output_format: str | None, client: httpx.AsyncClient) -> dict:
        if fmt == "text":
            params: dict = {"query": content}
        else:
            query = content.get("query")
            location = content.get("location")
            radius = content.get("radius", 5000)
            params = {"query": query}
            if location:
                params["location"] = f"{location.get('lat')},{location.get('lng')}"
                params["radius"] = radius
        response = await client.get("/place/textsearch/json", params=params)
        data = response.json()
        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise ValueError(f"Places search failed: {data.get('status')}")
        if output_format == "application/geo+json":
            features = []
            for place in data.get("results", []):
                loc = place.get("geometry", {}).get("location", {})
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [loc.get("lng"), loc.get("lat")]},
                    "properties": {
                        "name": place.get("name"),
                        "address": place.get("formatted_address"),
                        "rating": place.get("rating"),
                        "place_id": place.get("place_id"),
                    },
                })
            return {"type": "FeatureCollection", "features": features}
        return data

    async def _place_details(self, fmt: str, content: Any, output_format: str | None, client: httpx.AsyncClient) -> dict:
        if fmt != "application/json":
            raise ValueError("Place details requires JSON input")
        place_id = content.get("place_id")
        if not place_id:
            raise ValueError("Place ID required")
        response = await client.get("/place/details/json", params={"place_id": place_id})
        data = response.json()
        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise ValueError(f"Place details failed: {data.get('status')}")
        return data

    async def _distance_matrix(self, fmt: str, content: Any, output_format: str | None, client: httpx.AsyncClient) -> dict:
        if fmt != "application/json":
            raise ValueError("Distance matrix requires JSON input")
        origins = content.get("origins", [])
        destinations = content.get("destinations", [])
        if not origins or not destinations:
            raise ValueError("Origins and destinations required")
        mode = content.get("mode", "driving")
        response = await client.get("/distancematrix/json", params={
            "origins": "|".join(origins),
            "destinations": "|".join(destinations),
            "mode": mode,
        })
        data = response.json()
        if response.status_code != 200 or data.get("status") != "OK":
            logger.warning("Google Maps API error status=%s", data.get("status"))
            raise ValueError(f"Distance matrix failed: {data.get('status')}")
        return data


maps_service = GoogleMapsService(config.google_maps_api_key)

# ---------------------------------------------------------------------------
# A2A Agent Card
# ---------------------------------------------------------------------------

SKILL_DEFINITIONS = [
    AgentSkill(
        id="geocode",
        name="Geocode",
        description="Convert an address to latitude/longitude coordinates. Returns JSON or GeoJSON.",
        tags=["maps", "geocoding", "coordinates"],
        examples=[
            "What are the coordinates for the Eiffel Tower?",
            "Convert 350 Fifth Avenue New York NY to GPS coordinates",
            "Where is O'Hare International Airport on a map?",
            "Find the latitude and longitude of the Sydney Opera House",
        ],
        input_modes=["application/json", "text/plain"],
        output_modes=["application/json", "application/geo+json"],
    ),
    AgentSkill(
        id="reverse_geocode",
        name="Reverse Geocode",
        description="Convert latitude/longitude coordinates to a human-readable address.",
        tags=["maps", "geocoding", "address"],
        examples=[
            "What address is at latitude 37.42 longitude -122.08?",
            "What street is located at coordinates 40.7580, -73.9855?",
            "What place is at GPS coordinates 48.8584, 2.2945?",
        ],
        input_modes=["application/json"],
        output_modes=["application/json", "text/plain"],
    ),
    AgentSkill(
        id="directions",
        name="Directions",
        description="Get driving, walking, or transit directions between two locations.",
        tags=["maps", "directions", "navigation", "routing"],
        examples=[
            "How do I get from San Francisco to Los Angeles by car?",
            "Give me step-by-step directions from Chicago to Milwaukee",
            "What is the walking route from Central Park to the Metropolitan Museum?",
            "How long does it take to drive from Seattle to Portland?",
        ],
        input_modes=["application/json"],
        output_modes=["application/json", "text/plain"],
    ),
    AgentSkill(
        id="places_search",
        name="Places Search",
        description="Search for places, businesses, and points of interest using Google Places.",
        tags=["maps", "places", "search", "poi"],
        examples=[
            "Find Italian restaurants near Times Square New York",
            "What hotels are close to LAX airport?",
            "Search for pharmacies within a mile of downtown Chicago",
            "Are there any parks near the Eiffel Tower?",
        ],
        input_modes=["application/json", "text/plain"],
        output_modes=["application/json", "application/geo+json"],
    ),
    AgentSkill(
        id="place_details",
        name="Place Details",
        description="Get detailed information about a specific place by its Google place_id.",
        tags=["maps", "places", "details"],
        examples=[
            "What are the opening hours and phone number for the Louvre Museum?",
            "Get full details about the Googleplex",
            "What is the rating and website for the Empire State Building?",
        ],
        input_modes=["application/json"],
        output_modes=["application/json"],
    ),
    AgentSkill(
        id="distance_matrix",
        name="Distance Matrix",
        description="Calculate distances and travel times between multiple origins and destinations.",
        tags=["maps", "distance", "travel-time", "matrix"],
        examples=[
            "How far is New York from Boston by car?",
            "Compare driving times from Denver to Boulder, Fort Collins, and Colorado Springs",
            "What is the travel distance and time from Miami to Orlando?",
            "Calculate distances from our warehouse to all three delivery locations",
        ],
        input_modes=["application/json"],
        output_modes=["application/json"],
    ),
]

AGENT_CARD = AgentCard(
    name="Google Maps A2A",
    description=(
        "An A2A Protocol v1 compliant agent providing Google Maps Platform capabilities: "
        "geocoding, reverse geocoding, directions, places search, place details, and distance matrix."
    ),
    version="2.0.0",
    documentation_url="https://github.com/yourusername/google-maps-a2a",
    capabilities=AgentCapabilities(streaming=False, push_notifications=False),
    default_input_modes=["application/json"],
    default_output_modes=["application/json"],
    supported_interfaces=[
        AgentInterface(
            url=f"{config.base_url.rstrip('/')}/",
            protocol_binding="jsonrpc",
            protocol_version="1.0",
        )
    ],
    skills=SKILL_DEFINITIONS,
)

# Security scheme (informational — actual enforcement is via middleware)
AGENT_CARD.security_schemes["apiKey"].CopyFrom(
    SecurityScheme(
        api_key_security_scheme=APIKeySecurityScheme(
            name="X-API-Key",
            location="header",
            description="API key passed in X-API-Key HTTP header",
        )
    )
)

# ---------------------------------------------------------------------------
# Input parsing helpers
# ---------------------------------------------------------------------------

def _make_data_part(result: dict) -> Part:
    """Wrap a dict result as a protobuf Value data Part."""
    v = Value()
    v.struct_value.CopyFrom(json_format.ParseDict(result, Struct()))
    return Part(data=v, media_type="application/json")


def _parse_message_input(context: RequestContext) -> tuple[str, str, Any, str | None]:
    """
    Parse the incoming A2A message and return (task_type, fmt, content, output_format).

    Accepts two formats from Kore AI:
    1. Data part — a JSON object: {"type": "geocode", "input": {"format": "...", "content": ...}, "output": {"format": "..."}}
    2. Text part — plain text passed as the content of a "geocode" skill based on skill_id hint
    """
    message = context.message
    if not message or not message.parts:
        raise ValueError("Message has no parts")

    # Try data part first (structured input from Kore AI tool call)
    for part in message.parts:
        if part.HasField("data"):
            try:
                payload = json_format.MessageToDict(part.data)
                task_type = payload.get("type") or payload.get("task_type")
                inp = payload.get("input", {})
                fmt = inp.get("format", "text")
                content = inp.get("content", payload.get("content", ""))
                output_format = payload.get("output", {}).get("format") if "output" in payload else None
                if task_type:
                    return task_type, fmt, content, output_format
            except Exception:
                pass

    # Fall back to text part
    text = context.get_user_input().strip()
    if text:
        # Try parsing text as JSON
        try:
            payload = json.loads(text)
            task_type = payload.get("type") or payload.get("task_type")
            inp = payload.get("input", {})
            fmt = inp.get("format", "text")
            content = inp.get("content", payload.get("content", ""))
            output_format = payload.get("output", {}).get("format") if "output" in payload else None
            if task_type:
                return task_type, fmt, content, output_format
        except json.JSONDecodeError:
            pass
        # Plain text — use as geocode content
        return "geocode", "text", text, None

    raise ValueError("Could not parse task type and input from message")


# ---------------------------------------------------------------------------
# A2A Agent Executor
# ---------------------------------------------------------------------------

SUPPORTED_TASK_TYPES = frozenset({
    "geocode", "reverse_geocode", "directions",
    "places_search", "place_details", "distance_matrix",
})


class GoogleMapsAgentExecutor(AgentExecutor):
    """Executes Google Maps tasks using the A2A v1 immediate Message response pattern.

    Google Maps calls are synchronous and complete in a single round-trip, so we use
    the A2A immediate response workflow: enqueue a single Message rather than going
    through the Task lifecycle (submit → working → completed). This avoids the
    requirement to enqueue a Task proto before sending TaskStatusUpdateEvent.
    """

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        from a2a.types.a2a_pb2 import Message as A2AMessage

        try:
            task_type, fmt, content, output_format = _parse_message_input(context)

            if task_type not in SUPPORTED_TASK_TYPES:
                raise ValueError(
                    f"Unsupported task type: '{task_type}'. "
                    f"Must be one of: {sorted(SUPPORTED_TASK_TYPES)}"
                )

            logger.info("Executing Google Maps task type=%s", task_type)
            result = await maps_service.execute(task_type, fmt, content, output_format)
            logger.info("Google Maps task completed type=%s", task_type)

            response = A2AMessage(
                message_id=str(uuid.uuid4()),
                role=ROLE_AGENT,
                task_id=context.task_id or "",
                context_id=context.context_id or "",
                parts=[_make_data_part(result)],
            )

        except Exception as e:
            logger.error("Google Maps task failed: %s", e, exc_info=True)
            response = A2AMessage(
                message_id=str(uuid.uuid4()),
                role=ROLE_AGENT,
                task_id=context.task_id or "",
                context_id=context.context_id or "",
                parts=[Part(text=f"Error: {e.detail if isinstance(e, Exception) and hasattr(e, 'detail') else str(e)}")],
            )

        await event_queue.enqueue_event(response)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        logger.info("Cancel requested task_id=%s", context.task_id)
        # Immediate-response agents have nothing to cancel; acknowledge gracefully.
        from a2a.types.a2a_pb2 import Message as A2AMessage
        response = A2AMessage(
            message_id=str(uuid.uuid4()),
            role=ROLE_AGENT,
            task_id=context.task_id or "",
            context_id=context.context_id or "",
            parts=[Part(text="Task cancelled.")],
        )
        await event_queue.enqueue_event(response)


# ---------------------------------------------------------------------------
# Authentication and IP middleware
# ---------------------------------------------------------------------------

_UNAUTHENTICATED_PATHS = frozenset({
    "/.well-known/agent-card.json",
    "/health",
    "/",  # OPTIONS preflight
})


class SecurityMiddleware(BaseHTTPMiddleware):
    """Validates X-API-Key and optionally enforces IP allowlist."""

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # IP allowlist (if configured)
        if config.allowed_ip_set and request.client.host not in config.allowed_ip_set:
            logger.warning("Request rejected: IP %s not in allowlist", request.client.host)
            return JSONResponse({"detail": "Forbidden"}, status_code=403)

        # Skip auth for public endpoints
        if request.url.path in _UNAUTHENTICATED_PATHS and request.method in ("GET", "OPTIONS"):
            return await call_next(request)

        # API key validation for all other requests
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            logger.warning("Authentication failed: missing X-API-Key header")
            return JSONResponse({"detail": "Missing API key"}, status_code=403)
        if not hmac.compare_digest(api_key, config.api_key):
            logger.warning("Authentication failed: invalid API key")
            return JSONResponse({"detail": "Invalid API key"}, status_code=401)

        return await call_next(request)


# ---------------------------------------------------------------------------
# Request handler and routes
# ---------------------------------------------------------------------------

task_store = InMemoryTaskStore()

request_handler = DefaultRequestHandler(
    agent_executor=GoogleMapsAgentExecutor(),
    task_store=task_store,
    agent_card=AGENT_CARD,
)

jsonrpc_routes = create_jsonrpc_routes(request_handler, rpc_url="/")

AGENT_CARD_DICT = json_format.MessageToDict(AGENT_CARD)


async def get_well_known_agent_card(request: Request) -> JSONResponse:
    """A2A v1 standard discovery endpoint."""
    return JSONResponse(AGENT_CARD_DICT)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

logger.info("Google Maps A2A Server starting log_level=%s", config.log_level)

app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/.well-known/agent-card.json", get_well_known_agent_card, methods=["GET"]),
        *jsonrpc_routes,
    ],
    middleware=[
        Middleware(SecurityMiddleware),
    ],
)

if __name__ == "__main__":  # pragma: no cover
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
