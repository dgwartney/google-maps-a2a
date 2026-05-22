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

## Agent Card

The agent card is served at the A2A v1 standard well-known URL:

```
GET /.well-known/agent-card.json
```

No authentication required. The card is generated from the protobuf `AgentCard` type and serialized to JSON:

```json
{
  "name": "Google Maps A2A",
  "description": "An A2A Protocol v1 compliant agent providing Google Maps Platform capabilities",
  "version": "2.0.0",
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
  "defaultInputModes": ["application/json"],
  "defaultOutputModes": ["application/json"],
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
      "description": "Convert an address to latitude/longitude coordinates",
      "tags": ["maps", "geocoding", "coordinates"],
      "inputModes": ["application/json", "text/plain"],
      "outputModes": ["application/json", "application/geo+json"]
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

| Method | Description |
|--------|-------------|
| `SendMessage` | Send a message and receive an immediate response |
| `GetTask` | Retrieve a task by ID |
| `ListTasks` | List tasks |
| `CancelTask` | Cancel a task |

All methods require the `A2A-Version: 1.0` header.

---

## Message and Response Format

### Input (skill invocation)

The `SendMessage` params contain a `Message` with `parts[]`. Each part has a `data` field (protobuf Value/Struct) containing the skill input:

```json
{
  "message": {
    "messageId": "<uuid>",
    "role": "ROLE_USER",
    "parts": [{
      "data": {
        "type": "<skill-id>",
        "input": {"format": "<fmt>", "content": <value>},
        "output": {"format": "<fmt>"}
      },
      "mediaType": "application/json"
    }]
  }
}
```

### Output (immediate Message response)

Google Maps calls complete synchronously, so this server uses the A2A v1 **immediate Message response** pattern. The `SendMessageResponse` contains a `message` (not a `task`):

```json
{
  "result": {
    "message": {
      "role": "ROLE_AGENT",
      "parts": [{"data": { ...Google Maps result... }, "mediaType": "application/json"}]
    }
  }
}
```

On error, the part contains `text` instead of `data`.

---

## Authentication

The server uses API key authentication declared in `securitySchemes`. The `X-API-Key` header is validated by Starlette middleware before requests reach the A2A handler. Missing or invalid keys return HTTP 403/401 before any JSON-RPC processing occurs.

---

## Skills

All 6 Google Maps capabilities are declared as A2A v1 `AgentSkill` objects with:
- `id` — used in the `type` field of the input data
- `name`, `description`, `tags`, `examples`
- `inputModes`, `outputModes`

See [usage.md](usage.md) for request/response examples for each skill.

---

## Implementation Notes

### Immediate response pattern

All Google Maps API calls complete in a single round-trip (~100–500ms). The A2A v1 spec supports two patterns:

- **Immediate response**: Enqueue a `Message` object — returns synchronously in the `SendMessage` response
- **Long-running task**: Enqueue a `Task` object, then send `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent`

This server uses the **immediate response** pattern because all Google Maps calls complete synchronously. A2A clients receive a `message` in the `SendMessageResponse` rather than a `task`.

### SDK

Built on [a2a-sdk](https://pypi.org/project/a2a-sdk/) v1.0.3+. The `GoogleMapsAgentExecutor` implements `AgentExecutor.execute()` and `AgentExecutor.cancel()`. The `DefaultRequestHandler` and `create_jsonrpc_routes()` wire up the JSON-RPC dispatch layer.

---

## Future Improvements

1. Add streaming support (`SendStreamingMessage`) for progressive result delivery
2. Implement persistent task storage (database-backed `TaskStore`) for multi-machine deployments
3. Add push notification support for webhook-based result delivery
4. Support `GetExtendedAgentCard` for authenticated capability discovery
