# Google Maps A2A Server

An [A2A Protocol v1.0](https://github.com/a2aproject/A2A) compliant agent providing Google Maps Platform capabilities via JSON-RPC 2.0.

Built on the official [a2a-sdk](https://pypi.org/project/a2a-sdk/). Supports geocoding, reverse geocoding, directions, places search, place details, and distance matrix — all accessible as A2A skills.

## Quick Start

```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env: fill in API_KEY and GOOGLE_MAPS_API_KEY

# Run locally
uv run uvicorn main:app --reload
```

The server starts on http://localhost:8000.

**Agent card discovery (A2A v1 standard):**
```bash
curl http://localhost:8000/.well-known/agent-card.json
```

## Documentation

| Document | Contents |
|----------|----------|
| [docs/usage.md](docs/usage.md) | API reference, JSON-RPC format, all 6 task types with examples |
| [docs/a2a-implementation.md](docs/a2a-implementation.md) | A2A Protocol v1.0 implementation details |
| [docs/deployment.md](docs/deployment.md) | fly.io deployment guide, secrets management, costs |
| [docs/google-maps-setup.md](docs/google-maps-setup.md) | Google Cloud API key setup and enabling required APIs |
| [docs/security.md](docs/security.md) | API key authentication, IP allowlist, CORS, HTTPS |
| [docs/kore-ai.md](docs/kore-ai.md) | Kore AI Agent Platform v1 integration guide |

## Running Tests

```bash
uv sync --group dev
uv run pytest tests/test_server.py -v --cov=main --cov-report=term-missing
```

## License

MIT — see [LICENSE](LICENSE) for details.
