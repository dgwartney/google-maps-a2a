# Google Maps A2A Server

An [A2A Protocol v1.0](https://github.com/a2aproject/A2A) compliant agent providing Google Maps Platform capabilities via JSON-RPC 2.0.

Built on the official [a2a-sdk](https://pypi.org/project/a2a-sdk/) and [Google ADK](https://google.github.io/adk-docs/) with Gemini 2.0 Flash. Natural language requests are routed through Gemini, which selects and calls the appropriate Maps API tool. Supports geocoding, reverse geocoding, directions, places search, place details, and distance matrix.

## Architecture

```
Caller → POST / (A2A JSON-RPC) → SecurityMiddleware → AgentExecutor
  → Google ADK Runner → Gemini 2.0 Flash (tool-calling) → GoogleMapsService
  → Google Maps Platform APIs → plain-text response → Caller
```

All six skills accept plain-text natural language input. Gemini interprets the request, calls the right Maps API tool, and returns a conversational plain-text answer.

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env: fill in A2A_API_KEY, MAPS_A2A_MAPS_KEY, and MAPS_A2A_GEMINI_KEY

# Run locally
uv run uvicorn main:app --reload
```

The server starts on http://localhost:8000.

**Agent card discovery (A2A v1 standard):**
```bash
curl http://localhost:8000/.well-known/agent-card.json
```

**Send a plain-text query:**
```bash
curl -X POST http://localhost:8000/ \
  -H "X-API-Key: <your-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "1",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{"text": "What are the coordinates for the Eiffel Tower?"}]
      }
    }
  }'
```

The response is in `result.message.parts[0].text`.

## Documentation

| Document | Contents |
|----------|----------|
| [docs/usage.md](docs/usage.md) | API reference, JSON-RPC format, all 6 skills with examples |
| [docs/a2a-implementation.md](docs/a2a-implementation.md) | A2A Protocol v1.0 implementation details and Gemini/ADK architecture |
| [docs/deployment.md](docs/deployment.md) | fly.io deployment guide, secrets management, costs |
| [docs/google-maps-setup.md](docs/google-maps-setup.md) | Google Cloud API key setup and enabling required APIs |
| [docs/security.md](docs/security.md) | API key authentication, IP allowlist, CORS, HTTPS |
| [docs/kore-ai.md](docs/kore-ai.md) | Kore AI Agent Platform integration guide |

## Running Tests

```bash
uv sync --group dev
uv run pytest tests/test_server.py -v --cov=main --cov-report=term-missing
```

## License

MIT — see [LICENSE](LICENSE) for details.
