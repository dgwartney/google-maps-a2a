# Kore AI Agent Platform v1 Integration

This guide covers integrating the Google Maps A2A Server with Kore AI Agent Platform v1.

---

## Overview

Kore AI Agent Platform v1 calls external tools as single HTTP requests. The standard A2A protocol uses a two-step flow (create task → execute task), which does not fit this model. This server provides `POST /tasks/run` — a single-step endpoint that creates and executes a task in one request and returns the completed result immediately.

**Endpoint used by Kore:** `POST /tasks/run`

---

## Tool Configuration

Configure a Kore AI tool with these settings:

| Setting | Value |
|---------|-------|
| Method | `POST` |
| URL | `https://google-maps-a2a.fly.dev/tasks/run` |
| Header name | `X-API-Key` |
| Header value | `<your API_KEY secret>` |
| Content-Type | `application/json` |

### Storing the API key in Kore

Store the `API_KEY` value in Kore AI's credential or secrets store. Reference it in the tool definition header rather than hardcoding it. Consult Kore AI's documentation for the exact configuration path for Agent Platform v1 external tool credentials.

---

## IP Allowlisting

For production deployments, restrict the server to only accept calls from Kore AI's outbound IPs. This ensures the server cannot be called from other sources even if the API key is compromised.

**Steps:**

1. Obtain Kore AI's outbound IP ranges:
   - Check https://docs.kore.ai (search "outbound IP" or "egress IP")
   - Contact Kore AI support or your account team for Agent Platform v1 egress IPs

2. Set the IPs as a fly.io secret:
   ```bash
   flyctl secrets set ALLOWED_IPS=<kore-ip-1>,<kore-ip-2>
   ```

See [security.md](security.md) for full details on the IP allowlist feature.

---

## Request Body Examples

All requests follow this structure:

```json
{
  "type": "<task-type>",
  "input": {
    "format": "<input-format>",
    "content": "<string or object>"
  }
}
```

To request a specific output format, include `"output"`:

```json
{
  "type": "geocode",
  "input": {"format":"text","content":"Times Square"},
  "output": {"format":"application/geo+json","content":""}
}
```

### geocode — Address to coordinates

```json
{
  "type": "geocode",
  "input": {"format": "text", "content": "{{user_address}}"}
}
```

```json
{
  "type": "geocode",
  "input": {"format": "application/json", "content": {"address": "{{user_address}}"}}
}
```

### reverse_geocode — Coordinates to address

```json
{
  "type": "reverse_geocode",
  "input": {
    "format": "application/json",
    "content": {"lat": {{latitude}}, "lng": {{longitude}}}
  }
}
```

### directions — Route planning

```json
{
  "type": "directions",
  "input": {
    "format": "application/json",
    "content": {
      "origin": "{{origin}}",
      "destination": "{{destination}}",
      "mode": "driving"
    }
  }
}
```

Supported `mode` values: `driving`, `walking`, `transit`, `bicycling`.

### places_search — Find nearby places

```json
{"type":"places_search","input":{"format":"text","content":"{{search_query}}"}}
```

```json
{
  "type": "places_search",
  "input": {
    "format": "application/json",
    "content": {
      "query": "{{search_query}}",
      "location": {"lat": {{latitude}}, "lng": {{longitude}}},
      "radius": 1000
    }
  }
}
```

### place_details — Full details for a place

```json
{
  "type": "place_details",
  "input": {
    "format": "application/json",
    "content": {"place_id": "{{place_id}}"}
  }
}
```

### distance_matrix — Distances between multiple points

```json
{
  "type": "distance_matrix",
  "input": {
    "format": "application/json",
    "content": {
      "origins": ["{{origin_1}}", "{{origin_2}}"],
      "destinations": ["{{destination_1}}"],
      "mode": "driving"
    }
  }
}
```

---

## Response Structure

Every response is a `Task` object:

```json
{
  "id": "uuid",
  "type": "geocode",
  "status": "completed",
  "created_at": "ISO8601",
  "updated_at": "ISO8601",
  "input": {"format": "text", "content": "..."},
  "output": {
    "format": "application/json",
    "content": { ...Google Maps API response... }
  }
}
```

**Extract the result:** `response.output.content`

**Handle failures:** check `status == "failed"` — the error message is in `output.content` as a string.

```json
{
  "status": "failed",
  "output": {"format": "text", "content": "Error executing task: Geocoding failed: ZERO_RESULTS"}
}
```

**Output format variants:**

| Format | When used |
|--------|-----------|
| `application/json` | Default for all task types |
| `application/geo+json` | When requested for `geocode` or `places_search` |
| `text` | When requested for `reverse_geocode` or `directions` |

---

## End-to-end Verification

Run this curl command to verify the integration end to end before configuring Kore:

```bash
curl -X POST https://google-maps-a2a.fly.dev/tasks/run \
  -H "X-API-Key: <your-API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"type":"geocode","input":{"format":"text","content":"Times Square, New York"}}'
```

Expected response: `status: "completed"` with `output.content.results[0].geometry.location` containing `lat` and `lng`.
