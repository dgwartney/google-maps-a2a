# Google Maps A2A Server — Usage Guide

## Table of Contents

- [Environment Variables](#environment-variables)
- [Endpoints](#endpoints)
- [Single-step vs Two-step Flow](#single-step-vs-two-step-flow)
- [Authentication](#authentication)
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
| `/` | GET | Server info and version |
| `/health` | GET | Health check — returns `{"status":"ok"}` |
| `/agent-card` | GET | Capability discovery (lists all task types and auth scheme) |
| `/docs` | GET | Interactive Swagger UI |

### Authenticated (require `X-API-Key` header)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/tasks` | POST | Create a task (status: `created`) |
| `/tasks/{task_id}` | GET | Fetch a task and its result |
| `/tasks/{task_id}/execute` | PUT | Execute a previously created task |
| `/tasks/run` | POST | **Create + execute in a single request** |

---

## Single-step vs Two-step Flow

### Single-step: `POST /tasks/run` (recommended for simple integrations)

Creates and executes the task synchronously, returning the completed result in one call.

```bash
curl -X POST http://localhost:8000/tasks/run \
  -H "X-API-Key: your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "geocode",
    "input": {"format": "text", "content": "Times Square, New York"}
  }'
```

Response: a completed `Task` object with `status: "completed"` and result in `output.content`.

### Two-step: `POST /tasks` → `PUT /tasks/{id}/execute` (standard A2A protocol)

Allows task creation and execution to be decoupled. Use when the caller follows the A2A specification strictly.

```bash
# Step 1 — create
curl -X POST http://localhost:8000/tasks \
  -H "X-API-Key: your_api_key_here" \
  -H "Content-Type: application/json" \
  -d '{"type":"geocode","input":{"format":"text","content":"Times Square, New York"}}'

# Step 2 — execute (use the id from step 1 response)
curl -X PUT http://localhost:8000/tasks/<task_id>/execute \
  -H "X-API-Key: your_api_key_here"
```

---

## Authentication

All endpoints except `/`, `/health`, `/agent-card`, and `/docs` require:

```
X-API-Key: <your API_KEY value>
```

Missing key → `403 Forbidden`
Wrong key → `401 Unauthorized`

---

## Task Types

All examples below use the single-step `/tasks/run` endpoint.

### geocode — Address → coordinates

Input formats: `text`, `application/json`
Output formats: `application/json`, `application/geo+json`

```json
{"type":"geocode","input":{"format":"text","content":"1600 Amphitheatre Pkwy, Mountain View, CA"}}
```

```json
{"type":"geocode","input":{"format":"application/json","content":{"address":"1600 Amphitheatre Pkwy"}}}
```

Request GeoJSON output by including `output` in the body:

```json
{
  "type": "geocode",
  "input": {"format":"text","content":"Times Square, New York"},
  "output": {"format":"application/geo+json","content":""}
}
```

---

### reverse_geocode — Coordinates → address

Input format: `application/json` (requires `lat` and `lng`)
Output formats: `application/json`, `text`

```json
{"type":"reverse_geocode","input":{"format":"application/json","content":{"lat":37.4224764,"lng":-122.0842499}}}
```

---

### directions — Route planning

Input format: `application/json` (requires `origin` and `destination`; optional `mode`: `driving` | `walking` | `transit` | `bicycling`)
Output formats: `application/json`, `text`

```json
{
  "type": "directions",
  "input": {
    "format": "application/json",
    "content": {"origin":"San Francisco, CA","destination":"Los Angeles, CA","mode":"driving"}
  }
}
```

---

### places_search — Search for POIs

Input formats: `text` (search query), `application/json` (query + optional location/radius)
Output formats: `application/json`, `application/geo+json`

```json
{"type":"places_search","input":{"format":"text","content":"coffee shops near Union Square San Francisco"}}
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

---

### place_details — Full info for a place

Input format: `application/json` (requires `place_id`)
Output format: `application/json`

```json
{"type":"place_details","input":{"format":"application/json","content":{"place_id":"ChIJ2eUgeAK6j4ARbn5u_wAGqWA"}}}
```

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

---

## Error Handling

| HTTP status | Meaning |
|-------------|---------|
| `200` | Success |
| `400` | Bad request (invalid input or Google Maps API error) |
| `401` | Invalid `X-API-Key` |
| `403` | Missing `X-API-Key` or IP not in allowlist |
| `404` | Task not found |
| `422` | Request body validation failed (Pydantic) |
| `500` | Internal server error |

When a task execution fails (e.g., Google Maps returns an error), the task status is set to `"failed"` and the error message is in `output.content`. The HTTP response is still `200`.

```json
{
  "id": "...",
  "type": "geocode",
  "status": "failed",
  "output": {
    "format": "text",
    "content": "Error executing task: Geocoding failed: ZERO_RESULTS"
  }
}
```
