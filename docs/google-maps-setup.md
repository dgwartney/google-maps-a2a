# Google Maps API Setup

This server uses four Google Maps Platform APIs. Follow these steps to create a project, enable billing, enable each API, and create an API key.

---

## Step 1 — Create or select a Google Cloud project

Go to: https://console.cloud.google.com/projectcreate

Documentation: https://developers.google.com/maps/get-started#create-project

---

## Step 2 — Enable billing

Go to: https://console.cloud.google.com/billing

Google Maps Platform APIs require a billing account. A **$200/month free credit** applies automatically — most light-usage deployments fall within this credit and incur no charges.

Documentation: https://developers.google.com/maps/get-started#enable-billing

---

## Step 3 — Enable each required API

Navigate to **APIs & Services → Library** in the Cloud Console, or use the direct links below.

| API | Enable link | Used by task type(s) |
|-----|------------|---------------------|
| Geocoding API | https://console.cloud.google.com/apis/library/geocoding-backend.googleapis.com | `geocode`, `reverse_geocode` |
| Places API | https://console.cloud.google.com/apis/library/places-backend.googleapis.com | `places_search`, `place_details` |
| Directions API | https://console.cloud.google.com/apis/library/directions-backend.googleapis.com | `directions` |
| Distance Matrix API | https://console.cloud.google.com/apis/library/distance-matrix-backend.googleapis.com | `distance_matrix` |

### Reference documentation

- Geocoding API: https://developers.google.com/maps/documentation/geocoding/overview
- Places Text Search: https://developers.google.com/maps/documentation/places/web-service/search-text
- Place Details: https://developers.google.com/maps/documentation/places/web-service/details
- Directions API: https://developers.google.com/maps/documentation/directions/overview
- Distance Matrix API: https://developers.google.com/maps/documentation/distance-matrix/overview

---

## Step 4 — Create an API key

1. Go to **APIs & Services → Credentials**: https://console.cloud.google.com/apis/credentials
2. Click **Create Credentials → API key**
3. Copy the key value — this is your `GOOGLE_MAPS_API_KEY`

Documentation: https://developers.google.com/maps/documentation/geocoding/get-api-key

---

## Step 5 — Restrict the API key to specific APIs (always recommended)

In the API key settings:

1. Under **API restrictions**, select **Restrict key**
2. Check only the 4 APIs from Step 3
3. Save

This prevents the key from being used for any other Google service if it is ever leaked.

---

## Step 6 (Optional) — Restrict the API key to fly.io's outbound IP

This adds a second layer of protection: the key can only be used from your specific fly.io machine.

**Requirement:** a static egress IPv4 allocated for your fly.io app. See [deployment.md](deployment.md) for how to allocate one (`fly ips allocate-egress`). Cost: ~$3.60/month.

Once you have the IP:

1. In the API key settings, under **Application restrictions**, select **IP addresses**
2. Add the fly.io outbound IPv4
3. Save

Documentation: https://cloud.google.com/docs/authentication/api-keys#adding_application_restrictions

---

## Pricing

| API | Billing reference |
|-----|-------------------|
| Geocoding | https://developers.google.com/maps/documentation/geocoding/usage-and-billing |
| Places | https://developers.google.com/maps/documentation/places/web-service/usage-and-billing |
| Directions | https://developers.google.com/maps/documentation/directions/usage-and-billing |
| Distance Matrix | https://developers.google.com/maps/documentation/distance-matrix/usage-and-billing |
| Overview | https://mapsplatform.google.com/pricing/ |

---

## Security best practices

https://developers.google.com/maps/api-security-best-practices
