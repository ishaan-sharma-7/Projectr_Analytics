const API_BASE = "http://localhost:8000";

export interface HexFeatureProperties {
  h3_index: string;
  pressure_score: number;
  label: "high" | "medium" | "low";
  distance_km: number;
  permit_density: number;
  unit_density: number;
  center_lat: number;
  center_lng: number;
}

export interface HexGeoJSON {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    geometry: { type: "Polygon"; coordinates: [number, number][][] };
    properties: HexFeatureProperties;
  }>;
  metadata?: { university: string; base_score: number; hex_count: number };
}

export async function fetchHexGrid(
  name: string,
  radiusMiles = 1.5
): Promise<HexGeoJSON> {
  const res = await fetch(
    `${API_BASE}/hex/${encodeURIComponent(name)}?radius_miles=${radiusMiles}`
  );
  if (!res.ok) throw new Error("Hex grid fetch failed");
  return res.json();
}
