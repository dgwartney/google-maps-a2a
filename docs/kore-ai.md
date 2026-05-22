# Kore AI Agent Platform v1 Integration

This guide covers integrating the Google Maps A2A Server with Kore AI Agent Platform v1.

Kore AI Agent Platform v1 is **A2A Protocol v1.0 compliant** and uses JSON-RPC as its transport. This server implements A2A v1.0 natively via the official `a2a-sdk`, so no adapter or bridge is needed.

---

## Welcome Message (Kore AI Profile → Welcome Message field)

Paste the following into the **Welcome Message** field on the Agent Setup → Profile screen:

> **Welcome to the Google Maps Agent!** 🗺️
>
> I can help you with anything location-related — just ask in plain language. Here's what I can do:
>
> - 📍 **Find coordinates** for any address or landmark
> - 🔄 **Look up an address** from GPS coordinates
> - 🚗 **Get directions** by car, foot, bike, or transit
> - 🔍 **Search for places** — restaurants, hotels, pharmacies, and more
> - ℹ️ **Get place details** — hours, phone, ratings, and website
> - 📏 **Calculate distances** between multiple locations
>
> Try asking something like:
> *"How do I get from JFK to Times Square?"*
> *"Find coffee shops near Union Square San Francisco"*
> *"What are the coordinates for the Eiffel Tower?"*
>
> What would you like to know?

---

## Agent Description (Kore AI Profile → Description field)

Paste the following into the **Description** box on the Agent Setup → Profile screen. Kore AI uses this text to route incoming user requests to the correct agent.

> This agent provides Google Maps Platform capabilities including geocoding (converting addresses to coordinates), reverse geocoding (coordinates to addresses), turn-by-turn directions between locations, nearby places search, detailed place information, and distance/travel-time calculations between multiple points. Route requests to this agent when users ask about locations, addresses, navigation, directions, finding nearby businesses or places, or calculating distances and travel times.

---

## How Kore Discovers This Agent

Kore reads the agent card at the A2A v1 standard well-known URL:

```
GET https://google-maps-a2a.fly.dev/.well-known/agent-card.json
```

No authentication is required. The card describes 6 skills (geocode, reverse_geocode, directions, places_search, place_details, distance_matrix), the JSON-RPC endpoint, and the API key security scheme.

---

## Agent Configuration in Kore AI

| Setting | Value |
|---------|-------|
| **Protocol** | A2A v1.0 |
| **Agent Card URL** | `https://google-maps-a2a.fly.dev/.well-known/agent-card.json` |
| **Endpoint** | `https://google-maps-a2a.fly.dev/` |
| **Auth header name** | `X-API-Key` |
| **Auth header value** | `<your API_KEY secret>` |
| **Protocol version header** | `A2A-Version: 1.0` |

Store the `API_KEY` value in Kore AI's credential store and reference it in the agent definition. Do not hardcode it in the configuration.

---

## JSON-RPC Request Format

All skill calls use `POST /` with the `SendMessage` method. The skill input is encoded as a `data` part in the message:

```json
{
  "jsonrpc": "2.0",
  "id": "<unique-id>",
  "method": "SendMessage",
  "params": {
    "message": {
      "messageId": "<uuid>",
      "role": "ROLE_USER",
      "parts": [
        {
          "data": {
            "type": "<skill-id>",
            "input": {
              "format": "<input-format>",
              "content": <string or object>
            }
          },
          "mediaType": "application/json"
        }
      ]
    }
  }
}
```

---

## Skill Examples (all 6)

### geocode

```json
{
  "type": "geocode",
  "input": {"format": "text", "content": "{{user_address}}"}
}
```

### reverse_geocode

```json
{
  "type": "reverse_geocode",
  "input": {"format": "application/json", "content": {"lat": {{latitude}}, "lng": {{longitude}}}}
}
```

### directions

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

Supported `mode` values: `driving`, `walking`, `transit`, `bicycling`

### places_search

```json
{"type": "places_search", "input": {"format": "text", "content": "{{search_query}}"}}
```

With location context:

```json
{
  "type": "places_search",
  "input": {
    "format": "application/json",
    "content": {"query": "{{search_query}}", "location": {"lat": {{lat}}, "lng": {{lng}}}, "radius": 1000}
  }
}
```

### place_details

```json
{
  "type": "place_details",
  "input": {"format": "application/json", "content": {"place_id": "{{place_id}}"}}
}
```

### distance_matrix

```json
{
  "type": "distance_matrix",
  "input": {
    "format": "application/json",
    "content": {
      "origins": ["{{origin}}"],
      "destinations": ["{{destination}}"],
      "mode": "driving"
    }
  }
}
```

---

## Response Structure

The result is always in `result.message.parts[0]`:

**Success** — `parts[0].data` contains the Google Maps API result:

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

**Error** — `parts[0].text` contains the error description:

```json
{
  "result": {
    "message": {
      "parts": [{"text": "Error: Geocoding failed: ZERO_RESULTS"}]
    }
  }
}
```

### Key result paths by skill

| Skill | Result path |
|-------|------------|
| `geocode` | `result.message.parts[0].data.results[0].geometry.location` → `{lat, lng}` |
| `geocode` | `result.message.parts[0].data.results[0].formatted_address` |
| `reverse_geocode` | `result.message.parts[0].data.results[0].formatted_address` |
| `directions` | `result.message.parts[0].data.routes[0].legs[0].distance.text` |
| `places_search` | `result.message.parts[0].data.results[]` → array of places |
| `place_details` | `result.message.parts[0].data.result` → full place object |
| `distance_matrix` | `result.message.parts[0].data.rows[0].elements[0].distance.text` |

---

## IP Allowlisting

For production, restrict this server to only accept calls from Kore AI's egress IPs. This prevents misuse even if the `API_KEY` is compromised.

**Find Kore AI's outbound IP ranges:**
- Check https://docs.kore.ai (search "outbound IP" or "egress IP")
- Contact Kore AI support or your account team for Agent Platform v1 egress IPs

**Apply the allowlist:**

```bash
flyctl secrets set ALLOWED_IPS=<kore-ip-1>,<kore-ip-2>
```

See [security.md](security.md) for full details on the IP allowlist feature.

---

## End-to-End Verification

Before configuring Kore, verify the server responds correctly:

```bash
curl -X POST https://google-maps-a2a.fly.dev/ \
  -H "X-API-Key: <your-API_KEY>" \
  -H "Content-Type: application/json" \
  -H "A2A-Version: 1.0" \
  -d '{
    "jsonrpc": "2.0",
    "id": "test-1",
    "method": "SendMessage",
    "params": {
      "message": {
        "messageId": "m1",
        "role": "ROLE_USER",
        "parts": [{
          "data": {"type": "geocode", "input": {"format": "text", "content": "Times Square, New York"}},
          "mediaType": "application/json"
        }]
      }
    }
  }'
```

Expected: `result.message.parts[0].data.results[0].geometry.location` contains `lat` and `lng` for Times Square.

---

## Skill Utterances

Sample phrases that should route to each skill. Use these when configuring intent training or utterance examples in Kore AI.

### geocode — Address to coordinates

- What are the coordinates for 1600 Amphitheatre Parkway Mountain View CA?
- Find the latitude and longitude of the Eiffel Tower
- Geocode 350 Fifth Avenue New York NY
- Where is the White House located on a map?
- Get the GPS coordinates for O'Hare International Airport
- Convert this address to coordinates: 221B Baker Street London
- What is the map location of Times Square?
- Look up the coordinates for the Sydney Opera House

### reverse_geocode — Coordinates to address

- What address is at latitude 37.42 longitude -122.08?
- What is at these coordinates: 40.7580, -73.9855?
- Reverse geocode 51.5074, -0.1278
- What street is located at 48.8584, 2.2945?
- Find the address for GPS coordinates 34.0522, -118.2437
- What location corresponds to these coordinates: 35.6762, 139.6503?
- Give me the address at 51.5007, -0.1246
- What place is at lat 37.7749 long -122.4194?

### directions — Navigation and routing

- How do I get from San Francisco to Los Angeles by car?
- Give me directions from JFK Airport to Times Square
- What is the fastest route from Chicago to Milwaukee?
- Navigate from the Golden Gate Bridge to Fisherman's Wharf
- How do I walk from Central Park to the Metropolitan Museum?
- Get me transit directions from Boston South Station to Cambridge
- What is the best driving route from Dallas to Houston?
- Give me step-by-step directions from my current location to Denver International Airport
- How long does it take to drive from Seattle to Portland?
- Show me the cycling route from Golden Gate Park to Caltrain station

### places_search — Finding nearby places

- Find coffee shops near Union Square San Francisco
- What Italian restaurants are close to Times Square?
- Search for gas stations near 94043
- Find pharmacies within a mile of downtown Chicago
- What hotels are near LAX airport?
- Show me ATMs close to my location
- Find grocery stores near 350 Fifth Avenue New York
- Are there any parks near the Eiffel Tower?
- Search for urgent care clinics in Austin Texas
- What gyms are open near downtown Seattle?

### place_details — Details about a specific place

- Tell me more about the Googleplex
- What are the opening hours for the Louvre Museum?
- What is the phone number for Times Square Hotel?
- Get details about place ID ChIJ2eUgeAK6j4ARbn5u_wAGqWA
- What is the website for the Empire State Building?
- What is the rating of the Golden Gate Bridge visitor center?
- Give me full information about this restaurant
- What is the address and contact info for Space Needle?

### distance_matrix — Distances and travel times between points

- How far is San Francisco from Los Angeles?
- What is the driving distance between New York and Boston?
- How long does it take to drive from Chicago to Detroit?
- Compare travel times from Denver to Boulder, Fort Collins, and Colorado Springs
- How far are each of our offices from the airport?
- Calculate driving distance from Seattle to Portland and Vancouver
- What is the travel time by transit from Midtown to JFK and LaGuardia?
- How many miles is it from Miami to Orlando?
- Give me distances from the warehouse to all three delivery locations

---

## Demonstration Script

**Scenario:** Planning a business trip to Mountain View, CA to visit a client at the Googleplex.
This demo walks through all 6 skills in a natural, connected flow.

**Audience:** Kore AI Agent Platform v1 users evaluating or onboarding to the Google Maps A2A agent.
**Duration:** ~10 minutes
**Prerequisites:** Agent connected and showing **Connected** status on the Profile screen.

---

### Opening (Presenter talk track)

> "Today I'll show you the Google Maps A2A agent running inside Kore AI Agent Platform. This agent gives your AI workflows real-time access to Google Maps — geocoding, directions, place search, and more. I'm going to walk through a realistic scenario: planning a business trip to visit a client at Google's headquarters in Mountain View, California. Watch how the agent handles each step and notice how it's being dispatched automatically — you don't have to tell it which skill to use."

---

### Scene 1 — Geocode: Locating the destination

**What to type into the agent:**
> "What are the GPS coordinates for the Googleplex, 1600 Amphitheatre Parkway, Mountain View, CA?"

**Talk track while it runs:**
> "I've asked the agent to find the coordinates for our client's office. The agent is routing this to the **geocode** skill, calling the Google Maps Geocoding API, and returning structured data. Notice I just typed a natural sentence — I didn't specify a skill or an API."

**What to highlight in the response:**
- `results[0].geometry.location` — shows `lat: 37.42` and `lng: -122.08`
- `results[0].formatted_address` — confirms the full validated address

**Key point for audience:**
> "These coordinates can now be passed to any downstream agent or tool in your workflow — for example, to plot the location on a map or trigger a geo-fenced notification."

---

### Scene 2 — Directions: Getting there from the airport

**What to type:**
> "How do I drive from San Francisco International Airport to 1600 Amphitheatre Parkway, Mountain View, CA?"

**Talk track:**
> "Now I need to know how to get there from the airport. The agent recognizes this as a navigation request and routes it to the **directions** skill. It's calling the Google Maps Directions API and returning the full route."

**What to highlight in the response:**
- `routes[0].legs[0].distance.text` — e.g. "22.3 mi"
- `routes[0].legs[0].duration.text` — e.g. "28 mins"
- First few steps in `steps[]` — human-readable turn-by-turn instructions

**Key point for audience:**
> "You can also ask for walking or transit directions. The agent supports driving, walking, bicycling, and transit modes — just say it in the request."

---

### Scene 3 — Places Search: Finding lunch nearby

**What to type:**
> "Find highly rated restaurants near 1600 Amphitheatre Parkway Mountain View?"

**Talk track:**
> "Our meeting runs through lunch, so let's find somewhere nearby to eat. This routes to the **places_search** skill. The agent is querying the Google Places API and returning a list of matching businesses with names, addresses, and ratings."

**What to highlight in the response:**
- `results[0].name` and `results[0].rating` — top result with rating
- `results[0].formatted_address` — address of the place
- Total number of results returned

**Key point for audience:**
> "You can also pass a location and radius in the request for more precise searches — for example, 'within 500 meters of our office'. The agent also supports GeoJSON output if you need to feed results into a mapping component."

---

### Scene 4 — Place Details: Checking the restaurant

**What to type:**
> "Get the details, phone number, and opening hours for that first restaurant."

*Use the `place_id` returned in Scene 3, or type:*
> "Get full details for place ID [place_id from previous result]"

**Talk track:**
> "Let's get more detail on that top result. I'm passing the place ID from the previous response to the **place_details** skill. This pulls the full record from Google Places — hours, phone, website, and more."

**What to highlight in the response:**
- `result.name` — confirmed restaurant name
- `result.formatted_phone_number` — contact number
- `result.opening_hours.weekday_text[]` — operating hours
- `result.website` — booking or menu link
- `result.rating` and `result.user_ratings_total`

**Key point for audience:**
> "This is a great example of chaining skills together. The place ID came from the search in Scene 3 and flowed directly into this detail lookup — exactly the kind of multi-step reasoning your orchestrating agent can do automatically."

---

### Scene 5 — Distance Matrix: Comparing hotel options

**What to type:**
> "I'm choosing between three hotels. How far is each one from the Googleplex by car? Hotels: The Ameswell Mountain View, Hotel Nia Autograph Collection, and Residence Inn by Marriott Palo Alto."

**Talk track:**
> "I have three hotel options and I want to compare commute times to the client site. One request to the **distance_matrix** skill returns all three distances and durations simultaneously. This would take three separate Directions calls otherwise."

**What to highlight in the response:**
- `rows[0].elements[]` — one entry per destination
- Each element's `distance.text` and `duration.text`
- Side-by-side comparison of all three options

**Key point for audience:**
> "The distance matrix is perfect for logistics decisions — comparing multiple suppliers, delivery routes, or service territories. All in one API call."

---

### Scene 6 — Reverse Geocode: Decoding a location pin

**What to type:**
> "A colleague sent me a map pin at 37.3861, -122.0839 — what address is that?"

**Talk track:**
> "Finally, a colleague dropped a pin on a map and sent me the raw coordinates. I need the actual address. The **reverse_geocode** skill converts those coordinates back into a human-readable address."

**What to highlight in the response:**
- `results[0].formatted_address` — the full street address
- `results[0].address_components[]` — structured breakdown (street, city, state, zip)

**Key point for audience:**
> "This is useful any time your workflow receives GPS coordinates from a mobile app, IoT device, or field team and needs to translate them into something actionable."

---

### Closing (Presenter talk track)

> "In about ten minutes we've covered all six Google Maps skills — geocoding, directions, place search, place details, distance matrix, and reverse geocoding — all through natural language, all routed automatically by the Kore AI platform. No API keys in the conversation, no skill selection, no structured forms.
>
> The agent is running on fly.io, compliant with A2A Protocol v1.0, and the agent card at `/.well-known/agent-card.json` publishes all of this capability so any A2A-compatible orchestrator can discover and use it without additional configuration.
>
> Questions?"

---

### Demo Troubleshooting

| Issue | Check |
|-------|-------|
| Agent shows **Disconnected** | Verify the agent card URL returns HTTP 200: `curl https://google-maps-a2a.fly.dev/.well-known/agent-card.json` |
| Response contains an error message | The `A2A-Version: 1.0` header may be missing, or the API key may have expired — check fly.io secrets with `flyctl secrets list` |
| Places search returns no results | Try a broader query; some location/radius combinations return zero results from Google's API |
| Directions returns `ZERO_RESULTS` | Verify origin and destination are valid addresses or well-known place names |
