# A2A Protocol v1 Implementation Details

This document describes how the Google Maps A2A Server implements the [A2A Protocol v1.0](https://github.com/a2aproject/A2A) specification.

## Protocol Overview

The Agent2Agent (A2A) protocol is an open standard under the Linux Foundation (contributed by Google) for enabling interoperability between AI agent systems. It defines:

1. A standard discovery mechanism (well-known agent card URL)
2. A JSON-RPC 2.0 transport binding
3. A message-based interaction model with typed parts
4. A task lifecycle for long-running operations
5. Standard security scheme declarations

This server is built on the official [a2a-sdk](https://github.com/a2aproject/a2a-python) Python library and is fully compliant with A2A v1.0.

---

## Architecture

```
Caller
  │
  ▼
POST / (JSON-RPC 2.0)
  │
  ▼
SecurityMiddleware          ← validates X-API-Key header
  │
  ▼
DefaultRequestHandler       ← a2a-sdk JSON-RPC dispatch
  │
  ▼
GoogleMapsAgentExecutor     ← AgentExecutor implementation
  │  extracts plain-text query from message parts
  ▼
Google ADK Runner           ← google-adk
  │  feeds query to Gemini 2.0 Flash with 6 tool definitions
  ▼
Gemini 2.0 Flash (LLM)      ← tool-calling
  │  selects appropriate Maps tool, calls it
  ▼
GoogleMapsService           ← Maps Platform HTTP client
  │  calls Google Maps APIs (Geocoding, Places, Directions, Distance Matrix)
  ▼
Plain-text response         ← Gemini synthesises conversational answer
  │
  ▼
A2A Message (text part)     ← returned in SendMessage response
  │
  ▼
Caller receives result.message.parts[0].text
```

### Key design choice: LLM-based routing

All requests are processed as plain-text natural language queries. Gemini 2.0 Flash interprets the user's intent, decides which Maps tool to call (or chains multiple tools), executes it via Google ADK, and generates a conversational plain-text answer. This means callers do not need to know which skill to invoke — they just ask a question.

---

## Agent Card

The agent card is served at the A2A v1 standard well-known URL:

```
GET /.well-known/agent-card.json
```

No authentication required. The card declares all 6 skills with `text/plain` input and output modes, reflecting the natural language interface:

```json
{
  "name": "Google Maps A2A",
  "description": "An A2A Protocol v1 compliant agent providing Google Maps Platform capabilities: geocoding, reverse geocoding, directions, places search, place details, and distance matrix.",
  "version": "2.0.0",
  "url": "https://google-maps-a2a.fly.dev/",
  "protocolVersion": "1.0",
  "supportedInterfaces": [
    {
      "url": "https://google-maps-a2a.fly.dev/",
      "protocolBinding": "jsonrpc",
      "protocolVersion": "1.0"
    }
  ],
  "capabilities": {
    "streaming": false,
    "pushNotifications": false
  },
  "defaultInputModes": ["text/plain"],
  "defaultOutputModes": ["text/plain"],
  "securitySchemes": {
    "apiKey": {
      "apiKeySecurityScheme": {
        "name": "X-API-Key",
        "location": "header",
        "description": "API key passed in X-API-Key HTTP header"
      }
    }
  },
  "skills": [
    {
      "id": "geocode",
      "name": "Geocode",
      "description": "Convert an address or place name to GPS coordinates.",
      "tags": ["maps", "geocoding", "coordinates"],
      "inputModes": ["text/plain"],
      "outputModes": ["text/plain"],
      "examples": [
        "What are the coordinates for the Eiffel Tower?",
        "Convert 350 Fifth Avenue New York NY to GPS coordinates"
      ]
    },
    ...
  ]
}
```

---

## Endpoint Structure

| Path | Method | Auth | Description |
|------|--------|------|-------------|
| `/.well-known/agent-card.json` | GET | No | A2A v1 capability discovery |
| `/health` | GET | No | Health check (fly.io monitoring) |
| `/` | POST | Yes | JSON-RPC 2.0 — all A2A operations |

All agent operations use a single `POST /` endpoint with JSON-RPC 2.0 method dispatch.

---

## Supported JSON-RPC Methods

| Method | Also accepted as | Description |
|--------|-----------------|-------------|
| `SendMessage` | `message/send` (v0.3 compat) | Send a plain-text query, receive an immediate response |
| `GetTask` | — | Retrieve a task by ID |
| `ListTasks` | — | List tasks |
| `CancelTask` | — | Cancel a task |

The server runs with `enable_v0_3_compat=True`, so both the A2A v1.0 method name (`SendMessage`) and the v0.3/inspector form (`message/send`) are accepted.

---

## Message and Response Format

### Input

The `SendMessage` params contain a `Message` with a single plain-text part:

```json
{
  "message": {
    "messageId": "<uuid>",
    "role": "ROLE_USER",
    "parts": [{"text": "What are the coordinates for Times Square?"}]
  }
}
```

### Output (immediate Message response)

Google ADK + Gemini processes the query synchronously. The `SendMessageResponse` contains a `message` (not a `task`) with a plain-text part:

```json
{
  "result": {
    "message": {
      "role": "ROLE_AGENT",
      "parts": [{"text": "Times Square is located at approximately 40.7580° N, 73.9855° W (latitude: 40.7580, longitude: -73.9855)."}]
    }
  }
}
```

---

## Authentication

The server uses API key authentication declared in `securitySchemes`. The `X-API-Key` header is validated by Starlette middleware before requests reach the A2A handler. Missing or invalid keys return HTTP 403/401 before any JSON-RPC processing occurs. Comparison is constant-time (`hmac.compare_digest`) to prevent timing attacks.

---

## Skills

All 6 Google Maps capabilities are declared as A2A v1 `AgentSkill` objects. Gemini selects among them at runtime based on the user's query — callers never specify a skill ID directly.

| Skill ID | Capability |
|----------|-----------|
| `geocode` | Address or place name → GPS coordinates |
| `reverse_geocode` | GPS coordinates → human-readable address |
| `directions` | Turn-by-turn routing between two locations |
| `places_search` | Search for businesses and points of interest |
| `place_details` | Hours, phone, rating, and website for a place |
| `distance_matrix` | Travel distances/times between multiple origin-destination pairs |

See [usage.md](usage.md) for example queries for each skill.

---

## Implementation Notes

### Immediate response pattern

All Google Maps API calls complete in a single round-trip. The A2A v1 spec supports two patterns:

- **Immediate response**: Enqueue a `Message` object — returns synchronously in the `SendMessage` response
- **Long-running task**: Enqueue a `Task` object, then send `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent`

This server uses the **immediate response** pattern. A2A clients receive a `message` in the `SendMessageResponse` rather than a `task`.

### SDK and components

| Component | Library |
|-----------|---------|
| A2A transport | [a2a-sdk](https://pypi.org/project/a2a-sdk/) v1.0.3+ |
| LLM agent | [google-adk](https://pypi.org/project/google-adk/) + Gemini 2.0 Flash |
| Maps HTTP | httpx async client → Google Maps Platform REST APIs |
| Task store | `InMemoryTaskStore` (single-machine; resets on restart) |
| Sessions | `InMemorySessionService` (single-machine; keyed by A2A context ID) |

`GoogleMapsAgentExecutor` implements `AgentExecutor.execute()` and `AgentExecutor.cancel()`. `DefaultRequestHandler` and `create_jsonrpc_routes()` wire up the JSON-RPC dispatch layer.

### Rate limit handling

The executor automatically retries on Gemini 429 `RESOURCE_EXHAUSTED` errors with exponential backoff: up to 3 retries at 5 s, 10 s, and 20 s intervals.

### Session state

ADK sessions are stored in memory using `InMemorySessionService`, keyed by the A2A `contextId`. Sessions persist across multiple `SendMessage` calls within the same context, allowing Gemini to maintain conversation history. **Sessions are lost on server restart** and are not shared across multiple server instances. For production multi-machine deployments, a database-backed session service would be required.

---

## Future Improvements

1. Add streaming support (`SendStreamingMessage`) for progressive result delivery
2. Implement persistent task and session storage (database-backed) for multi-machine deployments
3. Add push notification support for webhook-based result delivery
4. Support `GetExtendedAgentCard` for authenticated capability discovery
