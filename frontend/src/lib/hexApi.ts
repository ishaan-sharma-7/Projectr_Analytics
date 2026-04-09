const API_BASE = "http://localhost:8000";

export interface HexFeatureProperties {
  hex_number?: number;
  h3_index: string;
  pressure_score: number;
  raw_pressure_score?: number;
  label: "high" | "medium" | "low";
  distance_km: number;
  distance_to_campus_miles: number;
  permit_density: number;
  unit_density: number;
  bus_stop_count: number;
  campus_feature_count?: number;
  dormitory_count?: number;
  off_campus_housing_count?: number;
  development_marker_count?: number;
  already_developed_for_housing?: boolean;
  campus_share?: number;
  non_buildable_marker_count?: number;
  water_marker_count?: number;
  wetland_marker_count?: number;
  golf_marker_count?: number;
  forest_marker_count?: number;
  field_marker_count?: number;
  buildable_for_housing?: boolean;
  buildability_score?: number;
  on_campus_constrained?: boolean;
  development_status?:
    | "Hard non-buildable"
    | "On-campus constrained"
    | "Already developed (infill/redevelopment only)"
    | "Potentially buildable"
    | "Likely off-campus"
    | "Likely non-buildable (water/land-use constraints)";
  coverage_pct?: {
    water: number;
    wetland: number;
    campus: number;
    residential_built: number;
    commercial_built: number;
    parking_infrastructure: number;
    open_recreation: number;
  };
  classification_reason_codes?: string[];
  dominant_land_use?: string;
  classification_confidence?: "high" | "medium" | "low";
  debug_trace?: {
    sampling?: Record<string, number>;
    coverage_pct?: Record<string, number>;
    coverage_hits?: Record<string, number>;
    marker_counts?: Record<string, number>;
    thresholds?: Record<string, number>;
    decision_flags?: Record<string, boolean>;
    pressure_components?: Record<string, number>;
    buildability_components?: Record<string, number>;
    land_mix?: Record<string, number>;
    hex_number?: number;
  };
  transit_label: "Transit Hub" | "Walkable" | "Isolated";
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
  metadata?: {
    university: string;
    base_score: number;
    hex_count: number;
    requested_radius_miles?: number;
    effective_radius_miles?: number;
    probe_radius_miles?: number;
    auto_radius?: boolean;
    hex_resolution?: number;
    bus_stops_fetched?: number;
    campus_markers_fetched?: number;
    residential_markers_fetched?: number;
    non_buildable_markers_fetched?: number;
    development_markers_fetched?: number;
    commercial_markers_fetched?: number;
    parking_markers_fetched?: number;
    national_constraint_points_fetched?: number;
    classification_model_version?: string;
    data_layer_versions?: Record<string, string>;
    source_completeness?: Record<string, boolean>;
    development_status_counts?: Record<string, number>;
    debug_hex_enabled?: boolean;
    debug_log_path?: string;
  };
}

export async function fetchHexGrid(
  name: string,
  radiusMiles = 1.5,
  hexResolution = 9,
  autoRadius = true,
  debugHex = false
): Promise<HexGeoJSON> {
  const res = await fetch(
    `${API_BASE}/hex/${encodeURIComponent(name)}?radius_miles=${radiusMiles}&hex_resolution=${hexResolution}&auto_radius=${autoRadius}&debug_hex=${debugHex}`
  );
  if (!res.ok) throw new Error("Hex grid fetch failed");
  return res.json();
}

export type HexStreamEvent =
  | {
      type: "metadata";
      metadata: HexGeoJSON["metadata"];
      total_features: number;
    }
  | {
      type: "chunk";
      start: number;
      count: number;
      features: HexGeoJSON["features"];
    }
  | { type: "done" };

export async function* streamHexGrid(
  name: string,
  radiusMiles = 1.5,
  hexResolution = 9,
  autoRadius = true,
  debugHex = false
): AsyncGenerator<HexStreamEvent> {
  const res = await fetch(
    `${API_BASE}/hex/stream/${encodeURIComponent(name)}?radius_miles=${radiusMiles}&hex_resolution=${hexResolution}&auto_radius=${autoRadius}&debug_hex=${debugHex}`
  );
  if (!res.ok || !res.body) throw new Error("Hex stream fetch failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      try {
        yield JSON.parse(trimmed) as HexStreamEvent;
      } catch {
        // skip malformed lines
      }
    }
  }
}
