# Security

This document covers all configurable security features built into the server.

---

## API Key Authentication

All endpoints except `/`, `/health`, `/agent-card`, and `/docs` require an `X-API-Key` header.

### Choosing a strong key

Use a UUID or a cryptographically random string of 32+ characters. Example:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Setting the key

Set as a fly.io secret (never commit it to git):

```bash
flyctl secrets set API_KEY=<your-strong-key>
```

### Rotating the key

```bash
flyctl secrets set API_KEY=<new-key>
```

The running machine restarts automatically and begins accepting the new key immediately.

### Behaviour on failure

| Situation | HTTP response |
|-----------|--------------|
| Header missing | `403 Forbidden` |
| Wrong key value | `401 Unauthorized` |

---

## IP Allowlist

Restricts which source IP addresses can reach the server. This adds defense-in-depth: even if the `API_KEY` is leaked, requests from unlisted IPs are rejected before authentication is checked.

### Configuration

Set the `ALLOWED_IPS` environment variable to a comma-separated list of IPv4 or IPv6 addresses.

```bash
# As a fly.io secret
flyctl secrets set ALLOWED_IPS=203.0.113.10,203.0.113.11

# Local development (.env file)
ALLOWED_IPS=127.0.0.1
```

**Empty or unset `ALLOWED_IPS` = no IP restriction.** All source IPs are allowed.

### Behaviour when a request is blocked

```
HTTP 403 Forbidden
{"detail": "Forbidden"}
```

The blocked IP is logged at `WARNING` level.

### Finding a caller's outbound IP ranges

To allowlist a specific system (e.g., Kore AI Agent Platform v1):

- Check that system's documentation for published egress IP ranges
- Contact its support team if the ranges are not published
- For Kore AI: see https://docs.kore.ai (search "outbound IP" or "egress IP") or contact your account team

---

## HTTPS

fly.io terminates TLS at its edge. The container runs plain HTTP on port 8000; all external traffic is HTTPS.

`force_https = true` in `fly.toml` ensures any HTTP request is automatically redirected to HTTPS. No additional configuration is required.

---

## CORS

The server allows all origins (`allow_origins = ["*"]`) by default. This is intentional for broad API compatibility.

If your deployment is accessed directly from a browser and you want to restrict origins, update the `CORSMiddleware` configuration in `main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend.example.com"],
    ...
)
```

---

## Google Maps API Key Protection

The `GOOGLE_MAPS_API_KEY` is used server-side only. It is:

- Never returned in any API response
- Never logged
- Set as a fly.io secret (encrypted at rest, not visible in `fly.toml` or logs)

To further restrict the key, see [google-maps-setup.md](google-maps-setup.md):

- **API restriction**: limit the key to only the 4 required APIs
- **IP restriction** (optional): limit the key to your fly.io machine's outbound IP
