# Projectr Analytics — Data Sources

This document covers every public data source used in the platform: what it provides, how to access it, the geography level it operates at, update frequency, and how it feeds into the pipeline.

**Rule of thumb**: Pull once per city, normalize to census tract or ZIP, write to BigQuery. Do not build live ingestion for the hackathon.

---

## 1. U.S. Census Bureau — American Community Survey (ACS)

**What it provides**: The richest neighborhood-level demographic and housing data available publicly. This is your primary source for rent, vacancy, income, and population metrics.

**Why it matters for the health score**: Median rent and vacancy rate are the two most direct signals of neighborhood housing market conditions. Income growth is the gentrification signal.

**API base URL**: `https://api.census.gov/data`

**Auth**: Free API key required. Register at [api.census.gov/data/key_signup.html](https://api.census.gov/data/key_signup.html). The key is a query parameter: `&key=YOUR_KEY`.

**Which dataset to use**: ACS 5-Year Estimates (`acs/acs5`). The 5-year provides the finest geographic granularity (down to census tract). 1-year estimates only go to the county level.

**Geography level**: Census tract (most granular available). Also available at ZIP Code Tabulation Area (ZCTA) level.

**Update frequency**: Annual. The most recent full release is typically the prior calendar year.

**Key variables and table IDs**:

| Variable | Table | Description |
|---|---|---|
| Median gross rent | `B25064_001E` | Median gross rent (all bedrooms) |
| Rental vacancy rate | `B25004_002E` / `B25004_001E` | For-rent vacant / total vacant units |
| Median household income | `B19013_001E` | Median household income in past 12 months |
| Total population | `B01003_001E` | Total population |
| Gross rent as % of income | `B25070` table | Distribution of rent burden |

**Example API call** (median rent by census tract in Virginia, state FIPS 51):

```
https://api.census.gov/data/2022/acs/acs5?get=B25064_001E,NAME&for=tract:*&in=state:51&key=YOUR_KEY
```

**Getting year-over-year change**: Pull the same variables for two consecutive years (e.g., 2021 and 2022) and compute the delta in the pipeline. The Census API returns one year per call.

**Geography crosswalk**: Census tracts are identified by an 11-digit FIPS code: `state(2) + county(3) + tract(6)`. Use this as your `geo_id`.

**GeoJSON boundaries**: Download TIGER/Line shapefiles from [census.gov/geographies/mapping-files](https://www.census.gov/geographies/mapping-files.html). Convert to GeoJSON with `ogr2ogr` or upload to mapshaper.org for a web-based conversion. You need these for the map polygon overlays.

---

## 2. FRED — Federal Reserve Economic Data

**What it provides**: Macroeconomic indicators at the metro/MSA level. This is your source for job growth and unemployment, which operate at a higher geographic level than census tracts.

**Why it matters for the health score**: Job growth is the fundamental driver of housing demand. A metro adding jobs will see housing pressure downstream. Unemployment trends signal economic health.

**API base URL**: `https://api.stlouisfed.org/fred`

**Auth**: Free API key required. Register at [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html).

**Geography level**: Metropolitan Statistical Area (MSA). FRED does not have sub-city granularity. Apply the MSA-level metric uniformly to all census tracts within that MSA — it's a macro signal, not a neighborhood signal.

**Update frequency**: Monthly for employment data; quarterly for some series.

**Key series to pull**:

| Series ID Pattern | Description | Example |
|---|---|---|
| `[MSA_CODE]UR` | Unemployment rate | `ROAUR` (Roanoke, VA) |
| `SMU[FIPS]000000001SA` | Total nonfarm employment | `SMU51440000000001SA` |
| `[MSA_CODE]NGSP` | GDP growth (some metros) | Varies |

**Finding MSA codes**: Use the FRED series search UI at fred.stlouisfed.org or the `/fred/series/search` endpoint. Search for your city name + "unemployment" to find the right series ID.

**Example API call** (Roanoke unemployment rate, last 24 months):

```
https://api.stlouisfed.org/fred/series/observations?series_id=ROAUR&observation_start=2022-01-01&api_key=YOUR_KEY&file_type=json
```

**In the pipeline**: Pull 24 months of data, compute YoY change and 6-month trend. Join to the census tract data on MSA FIPS code.

---

## 3. HUD — Fair Market Rents (FMR)

**What it provides**: HUD's annual estimates of what a modest rental unit costs in a given area, by bedroom count. Used as a market baseline/benchmark — useful for comparing actual rents against HUD's affordability estimate.

**Why it matters**: FMR data lets you flag markets where actual rents are significantly above or below the HUD baseline, which is a signal of affordability pressure or slack demand.

**Access**: Two options:
1. **Annual CSV download** (simplest): [huduser.gov/portal/datasets/fmr.html](https://www.huduser.gov/portal/datasets/fmr.html). Download the latest year's FMR schedule as a CSV.
2. **HUD API**: `https://www.huduser.gov/hudapi/public/fmr` — requires a free token from the HUD User portal.

**Auth for API**: Register at [huduser.gov/portal/site/huduser/signup](https://www.huduser.gov/portal/site/huduser/signup). Token passed as `Bearer` header.

**Geography level**: ZIP code and HUD Fair Market Rent Area (which roughly corresponds to MSA or county). Not census-tract level.

**Update frequency**: Annual (HUD publishes new FMRs each fall for the following fiscal year).

**Key fields in the FMR CSV**:

| Field | Description |
|---|---|
| `fips2010` | County/area FIPS code |
| `fmr_0` | Efficiency (studio) FMR |
| `fmr_1` | 1-bedroom FMR |
| `fmr_2` | 2-bedroom FMR |
| `fmr_3` | 3-bedroom FMR |
| `fmr_4` | 4-bedroom FMR |

**In the pipeline**: Join on county FIPS (first 5 digits of census tract FIPS). Use 2-bedroom FMR as the benchmark. Compute the ratio of actual median rent (from ACS) to the HUD FMR — a ratio above 1.0 means the market is above the affordability baseline.

---

## 4. City Open Data Portals — Building Permits

**What it provides**: Records of building permits filed with the city for new construction or major renovation. This is the most powerful leading indicator in the dataset — developers file permits before they break ground, so permit activity tells you where capital is moving before it shows up in rent data.

**Why it matters for the health score**: A surge in permit filings in a neighborhood is a strong forward-looking signal. It means professionals who underwrite real estate for a living are betting on that area.

**Auth**: Most city open data portals are fully public, no key required.

**Update frequency**: Near real-time (updated as permits are filed).

**Platforms most cities use**:
- **Socrata** (socrata.com) — Most common. Has a standardized API (SODA). If you see `data.cityname.gov`, it's almost certainly Socrata.
- **ArcGIS REST API** — Some cities use Esri's open data hub.
- **Custom portals** — Some larger cities have their own.

**Roanoke, VA (primary city)**:
- Portal: `data.roanokeva.gov`
- Check for a "Building Permits" or "Permits Issued" dataset
- Socrata API endpoint format: `https://data.roanokeva.gov/resource/[dataset_id].json`

**Standard fields to extract** (Socrata permit datasets typically include):

| Field | Description |
|---|---|
| `permit_date` or `issued_date` | When the permit was filed |
| `permit_type` | New construction, renovation, demolition, etc. |
| `address` | Street address of the permit |
| `latitude` / `longitude` | Coordinates (if geocoded — usually available) |
| `valuation` | Estimated construction value (not always present) |

**In the pipeline**:
1. Pull all permits from the last 24 months
2. Filter to construction-relevant types (exclude electrical/plumbing permits for existing structures if granularity allows)
3. Geocode to census tract using the lat/lng + a spatial join against your TIGER/Line tract boundaries
4. Aggregate: count of permits per tract per 12-month window, compute YoY change

**Handling cities without a permit API**: If the target city doesn't have a public permit portal, fall back to pulling permit data from the state-level open data portal (Virginia has one), or use the Census Bureau's Building Permits Survey (`census.gov/construction/bps/`) which provides permit counts at the county and place level as a coarser fallback.

---

## 5. Zillow Research Data (Optional / Supplement)

**What it provides**: Zillow's proprietary rent index and home value index, published as free CSV downloads. The Zillow Observed Rent Index (ZORI) is a useful supplement to ACS rent data because it updates monthly (vs. ACS annually) and covers more recent market conditions.

**Why it's optional**: ACS is the authoritative source for the health score. Zillow fills in the recency gap — if you want to show rent trend lines through the current month rather than stopping at last year's ACS data.

**Access**: No API, no auth. Direct CSV downloads at: `https://www.zillow.com/research/data/`

**Key datasets**:

| Dataset | Description | Geography |
|---|---|---|
| ZORI (Smoothed, All Homes, Monthly) | Observed rent index, monthly | Metro, City, ZIP |
| ZHVI (All Homes, Monthly) | Home value index | Metro, City, ZIP, Neighborhood |

**Geography level**: ZIP code is the finest granularity for ZORI. Join to census tracts via ZIP-to-tract crosswalk (available from HUD: `huduser.gov/portal/datasets/usps_crosswalk.html`).

**Update frequency**: Monthly.

**In the pipeline**: Download the ZORI ZIP-level CSV. Join to tracts via the HUD crosswalk. Use as the time-series rent source for sparklines in the UI (more recent and monthly vs. ACS's annual snapshots). Do not replace ACS in the health score formula — keep ACS for the structural metrics, use Zillow for the trend visualization layer.

---

## Geography Reference

All data gets normalized to one of two geographies:

**Census Tract** (preferred): ~4,000 people per tract. Provides genuine neighborhood granularity. All Census ACS data is available at this level. FRED and HUD data must be joined at the MSA/county level and applied uniformly.

**ZIP Code** (fallback): Coarser than census tracts, but some sources (HUD FMR, Zillow) are only available at ZIP level. Use as fallback when tract-level data isn't available.

**Key crosswalk resources**:
- TIGER/Line Tract Shapefiles: `census.gov/geographies/mapping-files/time-series/geo/tiger-line-file.html`
- HUD ZIP-to-Tract crosswalk: `huduser.gov/portal/datasets/usps_crosswalk.html`
- Census Geocoder (API): `geocoding.geo.census.gov/geocoder` — converts addresses to FIPS tract IDs

---

## API Key Checklist

Before running the pipeline, make sure the following keys are in your environment:

| Service | Where to get it | Environment variable |
|---|---|---|
| Census ACS | api.census.gov/data/key_signup.html | `CENSUS_API_KEY` |
| FRED | fred.stlouisfed.org (login → API Keys) | `FRED_API_KEY` |
| HUD User | huduser.gov/portal/site/huduser/signup | `HUD_API_TOKEN` |
| Google Maps | console.cloud.google.com | `GOOGLE_MAPS_KEY` |
| Gemini | console.cloud.google.com | `GEMINI_API_KEY` |

City permit portals are public — no key needed.
