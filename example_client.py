"""Example A2A client for the Google Maps A2A Server.

Demonstrates the A2A Protocol v1.0 JSON-RPC interface. All queries are sent as
plain-text natural language — Gemini 2.0 Flash routes each query to the right
Google Maps tool and returns a conversational plain-text answer.

Run with:
    uv sync
    uv run python example_client.py

Set A2A_API_KEY and A2A_BASE_URL below or via environment variables.
"""
import asyncio
import os
import uuid

import httpx

BASE_URL = os.getenv("A2A_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("A2A_API_KEY", "your_api_key_here")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
    "A2A-Version": "1.0",
}


def separator():
    print("-" * 60)


async def send_query(client: httpx.AsyncClient, query: str) -> str:
    """Send a plain-text query via A2A SendMessage and return the text response."""
    payload = {
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
    response = await client.post(BASE_URL + "/", headers=HEADERS, json=payload)
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        return f"JSON-RPC error: {body['error']}"
    parts = body.get("result", {}).get("message", {}).get("parts", [])
    return parts[0].get("text", "(no text in response)") if parts else "(empty response)"


async def discover_capabilities(client: httpx.AsyncClient) -> None:
    """Fetch and display the agent card (A2A capability discovery)."""
    print("=== Agent Card (capability discovery) ===")
    response = await client.get(BASE_URL + "/.well-known/agent-card.json")
    response.raise_for_status()
    card = response.json()
    print(f"Agent:   {card.get('name')} v{card.get('version')}")
    print(f"Skills:  {[s['id'] for s in card.get('skills', [])]}")
    print(f"Input:   {card.get('defaultInputModes')}")
    print(f"Output:  {card.get('defaultOutputModes')}")
    separator()


async def demo_geocode(client: httpx.AsyncClient) -> None:
    query = "What are the GPS coordinates for the Eiffel Tower in Paris?"
    print(f"=== Geocode ===\nQuery: {query}")
    answer = await send_query(client, query)
    print(f"Answer: {answer}")
    separator()


async def demo_reverse_geocode(client: httpx.AsyncClient) -> None:
    query = "What address is at latitude 37.4224864 longitude -122.0855962?"
    print(f"=== Reverse Geocode ===\nQuery: {query}")
    answer = await send_query(client, query)
    print(f"Answer: {answer}")
    separator()


async def demo_directions(client: httpx.AsyncClient) -> None:
    query = "How do I drive from San Francisco, CA to Mountain View, CA?"
    print(f"=== Directions ===\nQuery: {query}")
    answer = await send_query(client, query)
    print(f"Answer: {answer}")
    separator()


async def demo_places_search(client: httpx.AsyncClient) -> None:
    query = "Find coffee shops near Union Square in San Francisco"
    print(f"=== Places Search ===\nQuery: {query}")
    answer = await send_query(client, query)
    print(f"Answer: {answer}")
    separator()


async def demo_distance_matrix(client: httpx.AsyncClient) -> None:
    query = "What are the driving distances from San Francisco to both Oakland and San Jose?"
    print(f"=== Distance Matrix ===\nQuery: {query}")
    answer = await send_query(client, query)
    print(f"Answer: {answer}")
    separator()


async def main() -> None:
    async with httpx.AsyncClient(timeout=60.0) as client:
        await discover_capabilities(client)
        await demo_geocode(client)
        await demo_reverse_geocode(client)
        await demo_directions(client)
        await demo_places_search(client)
        await demo_distance_matrix(client)


if __name__ == "__main__":
    asyncio.run(main())
