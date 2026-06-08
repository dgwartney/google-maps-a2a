# Google Maps A2A Server — Usage Guide

## Table of Contents

- [Environment Variables](#environment-variables)
- [Endpoints](#endpoints)
- [A2A Protocol v1 — Making Requests](#a2a-protocol-v1--making-requests)
- [Skills](#skills)
- [Error Handling](#error-handling)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `A2A_API_KEY` | Yes | — | Key callers must send as `X-API-Key` header |
| `MAPS_A2A_MAPS_KEY` | Yes | — | Google Cloud API key for Maps Platform calls |
| `MAPS_A2A_GEMINI_KEY` | Yes | — | Gemini API key for natural language routing (ADK) |
| `LOG_LEVEL` | No | `INFO` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `ALLOWED_IPS` | No | (empty) | Comma-separated caller IPs to allow; empty = no restriction |
| `BASE_URL` | No | `https://google-maps-a2a.fly.dev` | Public base URL used in the agent card |

Copy `.env.example` to `.env` and fill in the required values before running locally.

---

## Endpoints

### Public (no authentication)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check — returns `{"status":"ok"}` |
| `/.well-known/agent-card.json` | GET | **A2A v1 capability discovery** — lists all 6 skills and auth scheme |

### Authenticated (require `X-API-Key` header)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | POST | **JSON-RPC 2.0** — all agent operations via `SendMessage` method |

---

## A2A Protocol v1 — Making Requests

This server implements [A2A Protocol v1.0](https://github.com/a2aproject/A2A) using **JSON-RPC 2.0 over HTTP**.

### How it works

All requests are plain-text natural language queries. The server routes each query through **Gemini 2.0 Flash** (via Google ADK), which interprets the intent, calls the appropriate Google Maps API tool, and returns a conversational plain-text answer.

You do not need to specify a skill type — Gemini selects the right tool based on the query text.

### Required headers

```
X-API-Key: <your API key>
Content-Type: application/json
```

### Request format

All operations use `POST /` with the `SendMessage` method and a plain-text message part:

```json
{
  "jsonrpc": "2.0",
  "id": "<unique-request-id>",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "<uuid>",
      "role": "ROLE_USER",
      "parts": [
        {"text": "<your natural language query>"}
      ]
    }
  }
}
```

### Response format

The agent's answer is in `result.message.parts[0].text`:

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "result": {
    "message": {
      "role": "ROLE_AGENT",
      "parts": [
        {"text": "<conversational answer from Gemini>"}
      ]
    }
  }
}
```

### Example — geocode via curl

```bash
curl -X POST https://google-maps-a2a.fly.dev/ \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{"text": "What are the GPS coordinates for 1600 Amphitheatre Parkway, Mountain View, CA?"}]
      }
    }
  }'
```

Example response:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "result": {
    "message": {
      "role": "ROLE_AGENT",
      "parts": [{"text": "The GPS coordinates for 1600 Amphitheatre Parkway, Mountain View, CA are approximately 37.4224° N, 122.0855° W (latitude: 37.4224764, longitude: -122.0855862)."}]
    }
  }
}
```

---

## Skills

All 6 skills are invoked by sending a natural language query. Below are example queries and what each skill handles.

### geocode — Address → coordinates

Converts an address or place name to GPS coordinates (lat/lng).

Example queries:
- `"What are the coordinates for the Eiffel Tower?"`
- `"Convert 350 Fifth Avenue New York NY to GPS coordinates"`
- `"Find the latitude and longitude of O'Hare International Airport"`

---

### reverse_geocode — Coordinates → address

Converts GPS coordinates to a human-readable address.

Example queries:
- `"What address is at latitude 37.42 longitude -122.08?"`
- `"What street is located at coordinates 40.7580, -73.9855?"`
- `"What place is at GPS coordinates 48.8584, 2.2945?"`

---

### directions — Route planning

Gets driving, walking, transit, or bicycling directions between two locations.

Example queries:
- `"How do I drive from San Francisco to Los Angeles?"`
- `"Give me step-by-step walking directions from Central Park to the Met Museum"`
- `"What is the transit route from downtown Chicago to O'Hare?"`
- `"How long does it take to drive from Seattle to Portland?"`

---

### places_search — Search for places

Searches for businesses, points of interest, and places using Google Places.

Example queries:
- `"Find Italian restaurants near Times Square New York"`
- `"What hotels are close to LAX airport?"`
- `"Search for pharmacies within a mile of downtown Chicago"`
- `"Are there any parks near the Eiffel Tower?"`

---

### place_details — Details for a specific place

Gets detailed information about a place: hours, phone number, website, rating, etc.

Example queries:
- `"What are the opening hours and phone number for the Louvre Museum?"`
- `"Tell me about the Googleplex — address, hours, and rating"`
- `"What is the website and rating for the Empire State Building?"`

---

### distance_matrix — Travel distances and times

Calculates distances and travel times between multiple origins and destinations.

Example queries:
- `"How far is New York from Boston by car?"`
- `"Compare driving times from Denver to Boulder, Fort Collins, and Colorado Springs"`
- `"What is the travel distance and time from Miami to Orlando?"`
- `"Calculate driving distances from San Francisco to both Oakland and San Jose"`

---

## Error Handling

### HTTP-level errors

| Status | Meaning |
|--------|---------|
| `200` | Request processed (check `result` vs `error` field in JSON-RPC response) |
| `401` | Invalid `X-API-Key` |
| `403` | Missing `X-API-Key` or IP not in allowlist |

### JSON-RPC errors (HTTP 200, `error` field present)

| Code | Meaning |
|------|---------|
| `-32601` | Method not found |
| `-32602` | Invalid params |

### Application errors (HTTP 200, `result.message.parts[0].text`)

All responses — including errors — return HTTP 200 with a JSON-RPC result. When a query fails (e.g., a place isn't found, an address is invalid, or a Google Maps API error occurs), the `text` part contains an error description from Gemini.

Always read `result.message.parts[0].text` to get the answer or error message.

### Rate limiting (429)

Gemini API rate limits are handled automatically with exponential backoff (up to 3 retries: 5s, 10s, 20s). If all retries are exhausted, a JSON-RPC error is returned.
