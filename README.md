# Google Maps A2A Server

An [Agent2Agent (A2A) protocol](https://github.com/google/A2A)-compliant server that provides Google Maps capabilities to other agents and AI systems via a standardized HTTP API.

Supports: geocoding, reverse geocoding, directions, places search, place details, and distance matrix — all accessible as A2A tasks.

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env and fill in API_KEY and GOOGLE_MAPS_API_KEY

# Run locally
uv run uvicorn main:app --reload
```

The server starts on http://localhost:8000. Interactive API docs are available at http://localhost:8000/docs.

## Documentation

| Document | Contents |
|----------|----------|
| [docs/usage.md](docs/usage.md) | API reference, all endpoints, environment variables, task types, request/response examples |
| [docs/a2a-implementation.md](docs/a2a-implementation.md) | A2A protocol compliance details and non-standard extensions |
| [docs/deployment.md](docs/deployment.md) | fly.io deployment guide, secrets management, costs |
| [docs/google-maps-setup.md](docs/google-maps-setup.md) | Google Cloud Console setup, enabling APIs, API key creation and restriction |
| [docs/security.md](docs/security.md) | API key authentication, IP allowlist, CORS, HTTPS |
| [docs/kore-ai.md](docs/kore-ai.md) | Kore AI Agent Platform v1 integration guide |

## Running Tests

```bash
uv sync --group dev
uv run pytest test_server.py -v --cov=main --cov-report=term-missing
```

## License

MIT — see [LICENSE](LICENSE) for details.
