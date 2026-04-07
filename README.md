# CampusLens

**Student Housing Market Intelligence Platform** — Google Solutions Challenge VT 2026

CampusLens identifies undersupplied student housing markets by combining university enrollment trends, building permit data, and rent indices into a spatial Housing Pressure Score. It visualizes this data on Google Maps with H3 hex choropleths and uses a Gemini-powered agent to fetch and analyze data for any US university on demand.

## Architecture

```
College Scorecard + IPEDS  →  FastAPI Backend (Cloud Run)  →  React Frontend (Firebase)
Census BPS + ACS           →  Housing Pressure Score       →  Google Maps + H3 Hexes
ApartmentList / HUD FMR    →  Gemini Agent (function-calling)  →  Market Summaries
```

## Status

🚧 In development — see `CampusLens_Project_Report.docx` for the full technical plan.
