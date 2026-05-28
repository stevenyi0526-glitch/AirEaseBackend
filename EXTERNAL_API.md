# AirEase × Ski Finder — External Integration Guide

Welcome, partner. This document describes the two ways your product can hand
users over to AirEase for flight discovery and booking.

Base URL: `https://airease.ai`

---

## Your API Key

```
skf_e-4c1eSMAoP_K2g9bg0j0K6vDBq-HmVWKfuw9QEFBn8
```

> **How it works.** This is a shared secret. AirEase's backend already stores
> the matching value in its server-side `.env` (so it can validate incoming
> requests). You should store the same value in **your** application's
> `.env` and send it in the `X-API-Key` HTTP header whenever you call the
> REST `/search` endpoint.
>
> ```env
> # skifinder/.env
> AIREASE_API_KEY=skf_e-4c1eSMAoP_K2g9bg0j0K6vDBq-HmVWKfuw9QEFBn8
> ```
>
> Treat it like any other API secret — **never** ship it inside frontend
> JavaScript. If you only need to embed AirEase from the browser, use the
> **deep-link mode** below — it requires no key at all.
>
> To rotate the key, contact steven.yi@airease.ai.

---

## 1. Deep-link mode (recommended for end-user navigation, no key required)

Send the user's browser to:

```
https://airease.ai/external/ski
    ?arrival=<IATA>
   [&resort=<NAME>]
   [&date=YYYY-MM-DD]
   [&cabin=economy|business|first]
   [&adults=<1-9>]            # default 1
   [&children=<0-8>]          # default 0
```

AirEase will:

1. Read the parameters.
2. Request the browser's geolocation (with the user's permission) and resolve
   their nearest IATA airport.
3. Redirect to the standard flight results page, pre-filled with departure,
   arrival, date and cabin.

Examples:

```html
<a href="https://airease.ai/external/ski?resort=Niseko&arrival=HND&adults=2&children=1">
  Book flights to Niseko for a family of 3 on AirEase
</a>

<a href="https://airease.ai/external/ski?arrival=YVR&date=2026-12-20&cabin=business&adults=2">
  Whistler — Dec 20, business class, 2 adults
</a>
```

If the user denies geolocation we still navigate to the flight results page;
they will be prompted to pick a departure manually.

---

## 2. REST mode (server-to-server, requires API key)

Use this when your application already knows the user's departure airport
and you want JSON results to render inside your own UI.

All examples below assume your `AIREASE_API_KEY` env var is loaded.

### 2.1 List supported resorts (public, no key)

```bash
curl "https://airease.ai/v1/external/ski/resorts"
```

Returns:

```json
{
  "count": 20,
  "resorts": [
    {"resort": "Whistler Blackcomb", "airport_code": "YVR", "airport_name": "Vancouver International Airport"},
    {"resort": "Niseko",             "airport_code": "HND", "airport_name": "Tokyo Haneda Airport"}
  ]
}
```

### 2.2 Build a deep-link URL (public, no key)

```bash
curl "https://airease.ai/v1/external/ski/redirect-url?resort=Niseko&date=2026-12-20&cabin=business&adults=2&children=1"
```

Query parameters (all optional except one of `resort`/`arrival`):

| Name | Notes |
|---|---|
| `resort` or `arrival` | One required. `arrival` is an IATA code; `resort` is a name from `/resorts`. |
| `date` | YYYY-MM-DD, defaults to today + 30 days. |
| `cabin` | `economy` (default) \| `business` \| `first` |
| `adults` | 1–9, default 1 |
| `children` | 0–8, default 0 |

Returns:

```json
{
  "url": "https://airease.ai/external/ski?arrival=HND&date=2026-12-20&cabin=business&resort=Niseko",
  "arrival_code": "HND"
}
```

### 2.3 Search flights (REQUIRES `X-API-Key`)

```bash
curl -H "X-API-Key: $AIREASE_API_KEY" \
  "https://airease.ai/v1/external/ski/search?resort=Niseko&departure_code=HKG&date=2026-12-20&cabin=business&adults=2"
```

Query parameters:

| Name | Required | Notes |
|---|---|---|
| `resort` | one of | Resort name from `/resorts`. |
| `arrival_code` | one of | IATA airport code; takes precedence over `resort`. |
| `departure_code` | yes | IATA airport code of the departure. (Use deep-link mode if you need browser geolocation.) |
| `date` | no | YYYY-MM-DD. Defaults to today + 30 days. |
| `cabin` | no | `economy` (default) \| `business` \| `first` |
| `adults` | no | 1–9, default 1 |
| `children` | no | 0–8, default 0 |
| `currency` | no | ISO code, default `USD` |

Headers:

| Name | Required | Notes |
|---|---|---|
| `X-API-Key` | yes | Your `AIREASE_API_KEY` value. |

The response payload is identical to the public `GET /v1/flights/search`
endpoint — full `FlightSearchResponse` with scoring, pricing, and AirEase
ranking applied.

### 2.4 Error codes

| Code | Meaning |
|---|---|
| 400 | Missing `resort`/`arrival_code` or missing `departure_code` |
| 401 | Missing or invalid `X-API-Key` |
| 404 | Unknown resort name |
| 500 | Upstream search failure |

---

## Verified Endpoints (last run: 2026-05-15)

| Endpoint | Auth | Status |
|---|---|---|
| `GET /v1/external/ski/resorts` | public | ✅ 200 — 20 resorts |
| `GET /v1/external/ski/redirect-url` | public | ✅ 200 — returns deep-link |
| `GET /v1/external/ski/search` (no key) | rejected | ✅ 401 |
| `GET /v1/external/ski/search` (valid key) | accepted | ✅ 200 — returns flights |
| `GET /v1/external/ski/search` (wrong key) | rejected | ✅ 401 |
| `GET /external/ski?arrival=YVR` (frontend) | n/a | ✅ redirects after geo |

---

## Quotas & support

For production keys, custom branding, or rate-limit increases please contact
**steven.yi@airease.ai**.
