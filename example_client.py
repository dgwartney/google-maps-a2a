"""Example A2A client for the Google Maps A2A Server.

Run with:
    uv sync
    uv run python example_client.py

Set API_KEY and BASE_URL below or via environment variables.
"""
import asyncio
import os
import uuid
from datetime import datetime

import httpx

BASE_URL = os.getenv("A2A_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "your_api_key_here")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json",
}


def separator():
    print("-" * 60)


async def single_step_geocode(client: httpx.AsyncClient) -> None:
    """Demonstrate the single-step /tasks/run endpoint (primary Kore AI path)."""
    print("=== Single-step geocode via POST /tasks/run ===")
    response = await client.post(
        f"{BASE_URL}/tasks/run",
        headers=HEADERS,
        json={
            "type": "geocode",
            "input": {
                "format": "text",
                "content": "1600 Amphitheatre Parkway, Mountain View, CA",
            },
        },
    )

    if response.status_code != 200:
        print(f"Error: {response.status_code} {response.text}")
        return

    result = response.json()
    print(f"Status: {result['status']}")
    if result.get("output") and result["output"]["format"] == "application/json":
        data = result["output"]["content"]
        if data.get("results"):
            loc = data["results"][0]["geometry"]["location"]
            addr = data["results"][0]["formatted_address"]
            print(f"Address: {addr}")
            print(f"Coordinates: {loc['lat']}, {loc['lng']}")
    separator()


async def two_step_directions(client: httpx.AsyncClient) -> None:
    """Demonstrate the two-step A2A flow (standard protocol path)."""
    print("=== Two-step directions via POST /tasks → PUT /tasks/{id}/execute ===")

    task_id = str(uuid.uuid4())
    task_data = {
        "id": task_id,
        "type": "directions",
        "status": "created",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "input": {
            "format": "application/json",
            "content": {
                "origin": "San Francisco, CA",
                "destination": "Mountain View, CA",
                "mode": "driving",
            },
        },
    }

    # Step 1: create
    response = await client.post(f"{BASE_URL}/tasks", headers=HEADERS, json=task_data)
    if response.status_code != 200:
        print(f"Error creating task: {response.status_code} {response.text}")
        return
    print(f"Task created: {task_id}")

    # Step 2: execute
    response = await client.put(f"{BASE_URL}/tasks/{task_id}/execute", headers=HEADERS)
    if response.status_code != 200:
        print(f"Error executing task: {response.status_code} {response.text}")
        return

    result = response.json()
    print(f"Status: {result['status']}")
    if result.get("output") and result["output"]["format"] == "application/json":
        routes = result["output"]["content"].get("routes", [])
        if routes:
            leg = routes[0]["legs"][0]
            print(f"Distance: {leg.get('distance', {}).get('text', 'N/A')}")
            print(f"Duration: {leg.get('duration', {}).get('text', 'N/A')}")
    separator()


async def main() -> None:
    async with httpx.AsyncClient() as client:
        # Discover capabilities
        print("=== Agent Card (capability discovery) ===")
        response = await client.get(f"{BASE_URL}/agent-card")
        card = response.json()
        print(f"Agent: {card['name']} v{card['version']}")
        print(f"Task types: {[t['type'] for t in card['tasks']]}")
        separator()

        await single_step_geocode(client)
        await two_step_directions(client)


if __name__ == "__main__":
    asyncio.run(main())
