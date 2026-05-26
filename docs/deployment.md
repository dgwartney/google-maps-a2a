# Deploying to fly.io

## Prerequisites

- [flyctl](https://fly.io/docs/hands-on/install-flyctl/) installed: `brew install flyctl`
- Authenticated: `flyctl auth login`
- [uv](https://docs.astral.sh/uv/) installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Project dependencies resolved: `uv sync`

Verify you are logged in:

```bash
flyctl auth whoami
```

---

## First-time Setup

### 1. Create the fly.io app

```bash
flyctl launch --no-deploy --name google-maps-a2a
```

The `--no-deploy` flag lets you review `fly.toml` before the first deployment. The file is already committed in this repository; accept the existing configuration when prompted.

### 2. Set secrets

Secrets are encrypted at rest in fly.io's vault and injected as environment variables at runtime. They are never stored in `fly.toml` or git.

```bash
flyctl secrets set A2A_API_KEY=<choose-a-strong-random-key>
flyctl secrets set MAPS_A2A_MAPS_KEY=<your-google-maps-api-key>
flyctl secrets set MAPS_A2A_GEMINI_KEY=<your-gemini-api-key>
```

Choose a strong value for `A2A_API_KEY` — a UUID or a 32+ character random string. This key must be sent by every caller in the `X-API-Key` header.

See [google-maps-setup.md](google-maps-setup.md) to obtain `MAPS_A2A_MAPS_KEY`. Get `MAPS_A2A_GEMINI_KEY` from [Google AI Studio](https://aistudio.google.com/app/apikey).

### 3. Deploy

```bash
flyctl deploy
```

### 4. Verify

```bash
flyctl status

# Health check (no auth required)
curl https://google-maps-a2a.fly.dev/health
# Expected: {"status":"ok"}

# A2A v1 capability discovery — standard well-known URL (no auth required)
curl https://google-maps-a2a.fly.dev/.well-known/agent-card.json

# Test via JSON-RPC SendMessage (replace <A2A_API_KEY> with your chosen key)
curl -X POST https://google-maps-a2a.fly.dev/ \
  -H "X-API-Key: <A2A_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc":"2.0","id":"1","method":"SendMessage",
    "params":{"message":{"messageId":"m1","role":"ROLE_USER","parts":[
      {"text":"What are the GPS coordinates for Times Square, New York?"}
    ]}}
  }'
# Expected: result.message.parts[0].text contains a conversational answer with lat/lng
```

---

## Secrets Management

```bash
# View which secrets are set (names only — values are never shown)
flyctl secrets list

# Rotate a secret (machine restarts automatically)
flyctl secrets set A2A_API_KEY=<new-value>

# Remove a secret
flyctl secrets unset ALLOWED_IPS
```

---

## Configuration (`fly.toml`)

The committed `fly.toml` sets:

| Setting | Value | Notes |
|---------|-------|-------|
| `LOG_LEVEL` | `INFO` | Non-sensitive; safe to commit. Change to `DEBUG` for troubleshooting. |
| `auto_stop_machines` | `"stop"` | Stops idle machines (scale-to-zero). |
| `min_machines_running` | `0` | Allows scale to zero. Set to `1` for always-on (higher cost). |
| Health check path | `/health` | fly.io polls this every 30 s with a 5 s timeout. |

To change `LOG_LEVEL` without redeploying: update `fly.toml` and run `flyctl deploy`, or set it as a secret (`flyctl secrets set LOG_LEVEL=DEBUG`). Secrets override `[env]` values.

---

## Scale-to-zero vs Always-on

| `min_machines_running` | Behaviour | Approximate cost |
|-----------------------|-----------|-----------------|
| `0` (default) | Machine stops when idle; cold start ~1-2 s on next request | ~$1.94/month active time |
| `1` | One machine always running; no cold starts | ~$1.94/month continuous |

Kore AI's tool calls will experience the cold start on first call if using `min_machines_running = 0`. If latency is critical, set `min_machines_running = 1` in `fly.toml`.

---

## Debugging

```bash
# Live logs
flyctl logs

# SSH into running machine
flyctl ssh console

# Check machine status and restarts
flyctl status --all
```

---

## Optional: Static Egress IP

A static egress IPv4 is required if you want to restrict the Google Maps API key to only accept calls from your fly.io machine (see [google-maps-setup.md](google-maps-setup.md)).

```bash
fly ips allocate-egress --app google-maps-a2a -r iad   # ~$3.60/month per IPv4
fly ips list                                             # confirm the allocated IP
```

---

## fly.io Documentation

| Topic | URL |
|-------|-----|
| FastAPI on fly.io | https://fly.io/docs/python/frameworks/fastapi/ |
| fly.toml reference | https://fly.io/docs/reference/configuration/ |
| flyctl launch | https://fly.io/docs/flyctl/launch/ |
| Secrets management | https://fly.io/docs/apps/secrets/ |
| Health checks | https://fly.io/docs/reference/health-checks/ |
| Static egress IPs | https://fly.io/docs/networking/egress-ips/ |
| Autostop/autostart | https://fly.io/docs/launch/autostop-autostart/ |
| Pricing | https://fly.io/docs/about/pricing/ |
