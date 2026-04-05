# Projectr Analytics — System Architecture

## What We're Building

An AI-powered real estate market intelligence platform. It pulls fragmented public data from government sources, normalizes it to a common geography, synthesizes it into a per-neighborhood Market Health Score, and surfaces it through an interactive Google Maps dashboard with a Gemini-powered natural language query layer.

The target user is a real estate analyst or developer who currently spends half a day manually downloading spreadsheets from six different government websites. This platform collapses that into seconds and adds an AI interpreter on top.

---

## System Overview

```
Public APIs (FRED, Census, HUD, Permit APIs)
        |
        v
[Data Pipeline — Python on Cloud Run]
        |
        v
[BigQuery — Normalized Data Warehouse]
        |
        v
[Backend API — FastAPI on Cloud Run]
        |               |
        v               v
[React Frontend]    [Gemini API]
[Firebase Hosting]  (NL queries + insight cards)
        |
        v
[Google Maps JS API — Choropleth overlays, submarket boundaries]
```

---

## Components

### 1. Data Pipeline (Python — Google Cloud Run)

The pipeline is a Python script that runs on demand (or on a schedule) and handles the full ETL flow:

- **Extract**: Hits the public APIs (FRED, Census ACS, HUD, city permit portals) and downloads raw data
- **Transform**: Normalizes all data to a common geography (census tract or ZIP code), aligns on the same time periods, handles missing values and unit normalization
- **Score**: Computes the Market Health Score for each geographic unit (see scoring model below)
- **Load**: Writes the clean, scored dataset into BigQuery

The pipeline is stateless and idempotent — run it once per data refresh cycle. For the hackathon, run it once per city and cache. Do not try to make this real-time; that's a scope trap.

Runs on **Google Cloud Run** — serverless, no infrastructure to manage, and it counts as Google Cloud usage for the judging rubric.

### 2. BigQuery (Google Cloud — Data Warehouse)

All normalized neighborhood data lives here. Schema per row:

| Field | Type | Description |
|---|---|---|
| `geo_id` | STRING | Census tract or ZIP FIPS code |
| `city` | STRING | City name |
| `neighborhood_name` | STRING | Human-readable name if available |
| `median_rent` | FLOAT | Median gross rent (Census ACS) |
| `rent_yoy_change` | FLOAT | % change year-over-year |
| `vacancy_rate` | FLOAT | Rental vacancy rate |
| `vacancy_delta_6mo` | FLOAT | Change in vacancy over 6 months |
| `job_growth_rate` | FLOAT | MSA-level job growth (FRED) |
| `unemployment_rate` | FLOAT | MSA-level unemployment (FRED) |
| `median_income` | FLOAT | Median household income |
| `income_yoy_change` | FLOAT | % change year-over-year |
| `permit_count_12mo` | INTEGER | Building permits filed in last 12 months |
| `permit_yoy_change` | FLOAT | % change in permit activity YoY |
| `health_score` | FLOAT | Composite 0–100 score (see model below) |
| `last_updated` | TIMESTAMP | When this row was last refreshed |

BigQuery is the authoritative data store. The backend API queries it; nothing else writes to it except the pipeline.

### 3. Backend API (FastAPI — Google Cloud Run)

A thin Python API layer that sits between BigQuery and the frontend. Responsibilities:

- **`GET /neighborhoods?city=<city>`** — Returns all neighborhoods for a city with their full metric set and health scores. Used to render the initial map state.
- **`GET /neighborhood/<geo_id>`** — Returns full detail for a single neighborhood including time-series data for sparklines.
- **`POST /query`** — Accepts a natural language question from the user. Packages relevant data as structured context, calls Gemini, parses the response, and returns highlighted geo_ids + explanation text.
- **`GET /insights?city=<city>`** — Triggers Gemini to generate 3–4 insight cards for the city based on current data signals.

Also runs on **Cloud Run**. Stateless, scales to zero when not in use.

### 4. Gemini API Integration

Gemini is called from the backend in two contexts:

**Natural Language Query (called from `POST /query`)**

The backend builds a structured context object from BigQuery data summarizing all neighborhoods (name, health score, key metrics), then calls Gemini with a prompt like:

```
You are a senior real estate market analyst. The user is exploring a market dashboard 
for [city]. Here is a structured summary of all neighborhoods and their current metrics:

[JSON data]

The user has asked: "[user question]"

Return:
1. A list of the most relevant geo_ids that answer the question, ranked
2. A 2-3 sentence explanation of why these neighborhoods are most relevant
3. Any important caveats or nuance the user should know

Respond only with what the data supports. Do not speculate.
```

Gemini returns a structured response. The backend parses it and returns `{ geo_ids: [...], explanation: "..." }` to the frontend, which highlights the zones and displays the explanation.

**Insight Cards (called from `GET /insights`)**

The backend passes a structured city data summary and prompts Gemini to act as an analyst writing a market briefing. It returns 3–4 specific, data-grounded observations. Examples of the output type:

- "Permit filings in the Warehouse District are up 67% YoY — development capital is moving here before rent data reflects it."
- "Vacancy in the Medical District has risen 4 points over 6 months. New supply may be outpacing absorption."

### 5. Frontend (React — Firebase Hosting)

The main user interface. Key components:

**Map Canvas** — Google Maps JavaScript API with a custom dark basemap style. Neighborhoods rendered as GeoJSON polygons with choropleth fill color mapped to health score (or whichever layer is active). Smooth transitions between data layers.

**Data Layers Toggle** — Switch between overlays: Health Score, Rent, Vacancy, Job Growth, Permit Activity. Each layer tells a different part of the story.

**Neighborhood Side Panel** — Slides in on click. Displays: health score gauge, key metrics table, 3-year rent sparkline, auto-generated insight sentences.

**Natural Language Search Bar** — Fixed in the corner. User types a question, it calls `POST /query`, the map highlights returned zones and shows the explanation in the side panel.

**Comparison Mode** — User pins two neighborhoods. Side-by-side card with every metric compared in parallel, with directional indicators. Gemini-generated summary below explaining which looks stronger and why.

**Insight Cards** — Below the map. 3–4 auto-generated analyst notes for the current city. Refreshed when city selection changes.

**City Picker** — Dropdown to select the city. Currently scoped to one city for the hackathon; architecture supports adding more by running the pipeline for additional cities.

Hosted on **Firebase Hosting** — fast CDN, trivial to deploy, Google infrastructure.

### 6. Google Maps Platform

Used for:
- Base map rendering with custom dark/desaturated style
- GeoJSON polygon overlay rendering (choropleth neighborhoods)
- Heatmap layer (permit density or raw rent levels)
- Marker clusters for individual permit filings

The GeoJSON boundary files for census tracts are available from the Census TIGER/Line shapefiles and can be converted to GeoJSON with standard tooling (ogr2ogr or mapshaper).

---

## Market Health Score Model

The health score synthesizes multiple signals into a single 0–100 number per neighborhood. Current weighting:

| Signal | Weight | Source | Rationale |
|---|---|---|---|
| Rent growth trajectory (YoY) | 25% | Census ACS | Direct demand signal |
| Rental vacancy trend | 20% | Census ACS | Supply-demand balance |
| Permit activity (YoY change) | 20% | City permits | Leading indicator — where capital is moving |
| Job growth rate | 20% | FRED | Fundamental demand driver |
| Income growth | 15% | Census ACS | Affordability and gentrification signal |

Each signal is normalized to a 0–100 sub-score before weighting. The formula is intentionally transparent and adjustable. The weighting can be tuned based on what story you want the map to tell or what a specific user cares about.

This score is one of the platform's core analytical contributions — it forces a synthesis position rather than just displaying raw data.

---

## Google Technologies Used

| Technology | Role | Integration Depth |
|---|---|---|
| Google Maps Platform | Core map rendering, overlays, GeoJSON polygons | Deep — central to the entire UI |
| Gemini API | NL query interpretation, insight card generation | Deep — powers the two key differentiating features |
| Google Cloud Run | Hosts both the data pipeline and backend API | Core infrastructure |
| BigQuery | Normalized data warehouse | Core data layer |
| Firebase Hosting | Frontend deployment and CDN | Deployment layer |

Five technologies, all used meaningfully rather than as checkboxes.

---

## Deployment Architecture

```
Developer machine
    |-- git push --> GitHub
                        |
                        v
                  Cloud Run (pipeline) -- runs on demand
                  Cloud Run (API)      -- always-on, scales to zero
                  Firebase Hosting     -- static frontend assets
                        |
                        v
                  BigQuery             -- data at rest
                  Gemini API           -- called per-request
```

---

## Scope Constraints (Hackathon)

- **One city** at launch. Pick one, run the pipeline, cache the results. Do not attempt real-time ingestion.
- **Census tract or ZIP level** geography. Street-level granularity is not worth the added complexity.
- **No user authentication** unless explicitly needed. Public read-only dashboard is sufficient.
- **No real-time data refresh** in the UI. Data is fresh as of the last pipeline run. Show the `last_updated` timestamp in the footer.
- **Gemini calls are synchronous** for the hackathon. Do not build a queuing layer; call and wait.
