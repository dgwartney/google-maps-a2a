"""Google Maps ADK agent using Gemini tool-calling."""
import logging
from typing import Any

from google.adk.agents import LlmAgent

logger = logging.getLogger(__name__)


class GoogleMapsAgent:
    """ADK agent with 6 Google Maps skills powered by Gemini 2.0 Flash.

    Tools are async inner functions capturing maps_service via closure.
    This is required because ADK infers tool schemas from function signatures
    and does not support instance methods (self would appear in the schema).
    """

    SYSTEM_PROMPT = (
        "You are a helpful Google Maps assistant. Use the available tools to help users with:\n"
        "- Finding GPS coordinates for addresses (geocode)\n"
        "- Identifying places from coordinates (reverse_geocode)\n"
        "- Getting directions between locations (directions)\n"
        "- Searching for nearby places and businesses (places_search)\n"
        "- Getting details about specific places (place_details)\n"
        "- Calculating distances between multiple locations (distance_matrix)\n\n"
        "Always use the appropriate tool to get accurate, real-time information. "
        "Then provide a clear, conversational response with the key details the user needs."
    )

    def __init__(self, maps_service: Any) -> None:
        self._maps_service = maps_service
        self.agent: LlmAgent = self._build_agent()
        logger.info("GoogleMapsAgent initialised with model=gemini-2.5-flash")

    def _build_agent(self) -> LlmAgent:
        """Creates the LlmAgent with 6 Google Maps tools bound to maps_service."""
        service = self._maps_service  # captured by tool closures below

        async def geocode(address: str) -> dict:
            """Convert an address or place name to GPS coordinates (lat/lng).

            Args:
                address: The address or place name to geocode.
            """
            return await service.execute("geocode", "text", address)

        async def reverse_geocode(lat: float, lng: float) -> dict:
            """Convert GPS coordinates to a human-readable address.

            Args:
                lat: Latitude coordinate.
                lng: Longitude coordinate.
            """
            return await service.execute(
                "reverse_geocode",
                "application/json",
                {"lat": lat, "lng": lng},
            )

        async def directions(
            origin: str, destination: str, mode: str = "driving"
        ) -> dict:
            """Get turn-by-turn directions between two locations.

            Args:
                origin: Starting location (address or place name).
                destination: Destination (address or place name).
                mode: Travel mode — driving, walking, transit, or bicycling.
            """
            return await service.execute(
                "directions",
                "application/json",
                {"origin": origin, "destination": destination, "mode": mode},
            )

        async def places_search(query: str, near: str = "") -> dict:
            """Search for places, businesses, or points of interest.

            Args:
                query: What to search for (e.g. 'coffee shops', 'Italian restaurants').
                near: Optional location to search near (e.g. 'Times Square, New York').
            """
            content = f"{query} near {near}" if near else query
            return await service.execute("places_search", "text", content)

        async def place_details(place_id: str) -> dict:
            """Get detailed information about a specific place including hours, phone, and rating.

            Args:
                place_id: Google Maps place_id for the location.
            """
            return await service.execute(
                "place_details",
                "application/json",
                {"place_id": place_id},
            )

        async def distance_matrix(
            origins: list[str], destinations: list[str], mode: str = "driving"
        ) -> dict:
            """Calculate travel distances and times between multiple origins and destinations.

            Args:
                origins: List of starting location strings.
                destinations: List of destination location strings.
                mode: Travel mode — driving, walking, transit, or bicycling.
            """
            return await service.execute(
                "distance_matrix",
                "application/json",
                {"origins": origins, "destinations": destinations, "mode": mode},
            )

        return LlmAgent(
            model="gemini-2.5-flash",
            name="google_maps_agent",
            description="Google Maps assistant — locations, directions, places, distances",
            instruction=self.SYSTEM_PROMPT,
            tools=[
                geocode,
                reverse_geocode,
                directions,
                places_search,
                place_details,
                distance_matrix,
            ],
        )
