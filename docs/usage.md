# Google Maps A2A Server — Usage Guide

## Table of Contents

- [Environment Variables](#environment-variables)
- [Endpoints](#endpoints)
- [A2A Protocol v1 — Making Requests](#a2a-protocol-v1--making-requests)
- [Task Types](#task-types)
- [Error Handling](#error-handling)

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | Key callers must send as `X-API-Key` header |
| `GOOGLE_MAPS_API_KEY` | Yes | — | Google Cloud API key (server-side only) |
| `LOG_LEVEL` | No | `INFO` | Log verbosity: `DEBUG` \| `INFO` \| `WARNING` \| `ERROR` |
| `ALLOWED_IPS` | No | (empty) | Comma-separated caller IPs to allow; empty = no restriction |

Copy `.env.example` to `.env` and fill in the required values before running locally.

---

## Endpoints

### Public (no authentication)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check — returns `{"status":"ok"}` |
| `/.well-known/agent-card.json` | GET | **A2A v1 capability discovery** — lists all 6 skills and auth scheme |

### Authenticated (require `X-API-Key` + `A2A-Version: 1.0` headers)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | POST | **JSON-RPC 2.0** — all agent operations via `SendMessage` method |

---

## A2A Protocol v1 — Making Requests

This server implements [A2A Protocol v1.0](https://github.com/a2aproject/A2A) using **JSON-RPC 2.0 over HTTP**.

### Required headers

```
X-API-Key: <your API key>
Content-Type: application/json
A2A-Version: 1.0
```

### Request format

All operations use `POST /` with the `SendMessage` method:

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
        {
          "data": {
            "type": "<task-type>",
            "input": {
              "format": "<input-format>",
              "content": "<string or object>"
            }
          },
          "mediaType": "application/json"
        }
      ]
    }
  }
}
```

### Response format

On success, the result is in `result.message.parts[0].data`:

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "result": {
    "message": {
      "role": "ROLE_AGENT",
      "parts": [
        {
          "data": { ...Google Maps API result... },
          "mediaType": "application/json"
        }
      ]
    }
  }
}
```

On error, the result message part is a text string:

```json
{
  "result": {
    "message": {
      "parts": [{ "text": "Error: Geocoding failed: ZERO_RESULTS" }]
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
        "parts": [{
          "data": {
            "type": "geocode",
            "input": {"format": "text", "content": "1600 Amphitheatre Parkway, Mountain View, CA"}
          },
          "mediaType": "application/json"
        }]
      }
    }
  }'
```

---

## Task Types

All 6 task types use the same JSON-RPC `SendMessage` envelope. Only the `data` payload changes.

### geocode — Address → coordinates

Input formats: `text`, `application/json`
Output formats: `application/json` (default), `application/geo+json`

```json
{"type": "geocode", "input": {"format": "text", "content": "Times Square, New York"}}
```

```json
{"type": "geocode", "input": {"format": "application/json", "content": {"address": "Times Square"}}}
```

Request GeoJSON output by adding an `output` field:

```json
{
  "type": "geocode",
  "input": {"format": "text", "content": "Times Square, New York"},
  "output": {"format": "application/geo+json"}
}
```

Result path: `result.message.parts[0].data.results[0].geometry.location` → `{lat, lng}`

---

### reverse_geocode — Coordinates → address

Input format: `application/json` (requires `lat` and `lng`)
Output formats: `application/json` (default), `text`

```json
{
  "type": "reverse_geocode",
  "input": {"format": "application/json", "content": {"lat": 37.4224864, "lng": -122.0855962}}
}
```

Result path: `result.message.parts[0].data.results[0].formatted_address`

---

### directions — Route planning

Input format: `application/json` (requires `origin` and `destination`; optional `mode`: `driving` | `walking` | `transit` | `bicycling`)
Output formats: `application/json` (default), `text` (numbered step list)

```json
{
  "type": "directions",
  "input": {
    "format": "application/json",
    "content": {"origin": "San Francisco, CA", "destination": "Los Angeles, CA", "mode": "driving"}
  }
}
```

Result path: `result.message.parts[0].data.routes[0].legs[0]` → distance, duration, steps

---

### places_search — Search for places

Input formats: `text` (search query), `application/json` (query + optional location/radius)
Output formats: `application/json` (default), `application/geo+json`

```json
{"type": "places_search", "input": {"format": "text", "content": "coffee shops near Union Square SF"}}
```

```json
{
  "type": "places_search",
  "input": {
    "format": "application/json",
    "content": {
      "query": "pizza",
      "location": {"lat": 37.7749, "lng": -122.4194},
      "radius": 1000
    }
  }
}
```

Result path: `result.message.parts[0].data.results[]` → array of places

---

### place_details — Full details for a place

Input format: `application/json` (requires `place_id`)
Output format: `application/json`

```json
{
  "type": "place_details",
  "input": {"format": "application/json", "content": {"place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA"}}
}
```

Result path: `result.message.parts[0].data.result` → name, address, hours, rating, etc.

---

### distance_matrix — Distances between multiple points

Input format: `application/json` (requires `origins` and `destinations` arrays; optional `mode`)
Output format: `application/json`

```json
{
  "type": "distance_matrix",
  "input": {
    "format": "application/json",
    "content": {
      "origins": ["San Francisco, CA", "Oakland, CA"],
      "destinations": ["Mountain View, CA", "San Jose, CA"],
      "mode": "driving"
    }
  }
}
```

Result path: `result.message.parts[0].data.rows[i].elements[j]` → distance, duration per pair

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
| `-32009` | A2A version not supported (include `A2A-Version: 1.0` header) |

### Application errors (HTTP 200, `result.message.parts[0].text`)

When a task fails (e.g., invalid input, Google Maps API error), the response is still HTTP 200 with a JSON-RPC success result, but the message part contains a `text` field with the error description instead of a `data` field.

Always check whether `parts[0]` has `data` (success) or `text` (error) before extracting the result.
