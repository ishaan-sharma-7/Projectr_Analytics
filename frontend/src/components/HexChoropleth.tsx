import { useState } from "react";
import { Polygon, InfoWindow } from "@vis.gl/react-google-maps";
import type { HexGeoJSON, HexFeatureProperties } from "../lib/hexApi";

// Higher score = stronger developer opportunity → green end of the gradient.
function scoreToColor(score: number): string {
  if (score >= 70) return "#22c55e";
  if (score >= 55) return "#84cc16";
  if (score >= 40) return "#eab308";
  if (score >= 25) return "#f97316";
  return "#ef4444";
}

// "high"/"medium"/"low" come from the backend hex labels — we relabel them
// in opportunity language without changing the underlying keys.
const OPPORTUNITY_LABEL: Record<string, string> = {
  high: "Strong opportunity",
  medium: "Emerging market",
  low: "Saturated market",
};

type NormalizedStatus =
  | "Hard non-buildable"
  | "On-campus constrained"
  | "Already developed (infill/redevelopment only)"
  | "Potentially buildable";

function normalizeDevelopmentStatus(hex: HexFeatureProperties): NormalizedStatus {
  const status = hex.development_status;
  if (status === "Hard non-buildable") return status;
  if (status === "On-campus constrained") return status;
  if (status === "Already developed (infill/redevelopment only)") return status;
  if (status === "Potentially buildable") return status;
  if (hex.on_campus_constrained) return "On-campus constrained";
  if (hex.already_developed_for_housing) return "Already developed (infill/redevelopment only)";
  if (hex.buildable_for_housing === false) return "Hard non-buildable";
  return "Potentially buildable";
}

function hexFillColor(hex: HexFeatureProperties): string {
  const status = normalizeDevelopmentStatus(hex);
  if (status === "Hard non-buildable") return "#0ea5e9";
  if (status === "On-campus constrained") return "#6b7280";
  if (status === "Already developed (infill/redevelopment only)") return "#a855f7";
  return scoreToColor(hex.pressure_score);
}

function transitBadgeStyle(label: HexFeatureProperties["transit_label"]): {
  bg: string;
  text: string;
} {
  switch (label) {
    case "Transit Hub":
      return { bg: "#dbeafe", text: "#1d4ed8" };
    case "Walkable":
      return { bg: "#dcfce7", text: "#15803d" };
    default:
      return { bg: "#f4f4f5", text: "#71717a" };
  }
}

function formatPct(value: number | undefined): string {
  return `${Math.round((value ?? 0) * 100)}%`;
}

function readableReasonCode(code: string): string {
  return code.replace(/_/g, " ");
}

export function HexChoropleth({ hexData }: { hexData: HexGeoJSON }) {
  const [selectedHex, setSelectedHex] = useState<HexFeatureProperties | null>(null);
  const normalizedStatus = selectedHex
    ? normalizeDevelopmentStatus(selectedHex)
    : null;
  const constrained = normalizedStatus === "On-campus constrained";
  const developed = normalizedStatus === "Already developed (infill/redevelopment only)";
  const nonBuildable = normalizedStatus === "Hard non-buildable";
  const rawScore = selectedHex
    ? (selectedHex.raw_pressure_score ?? selectedHex.pressure_score)
    : 0;
  const campusCount = selectedHex?.campus_feature_count ?? 0;
  const dormCount = selectedHex?.dormitory_count ?? 0;
  const offCampusHousingCount = selectedHex?.off_campus_housing_count ?? 0;
  const nonBuildableCount = selectedHex?.non_buildable_marker_count ?? 0;
  const waterCount = selectedHex?.water_marker_count ?? 0;
  const golfCount = selectedHex?.golf_marker_count ?? 0;
  const forestCount = selectedHex?.forest_marker_count ?? 0;
  const fieldCount = selectedHex?.field_marker_count ?? 0;
  const developmentCount = selectedHex?.development_marker_count ?? 0;
  const campusSharePct = Math.round((selectedHex?.campus_share ?? 0) * 100);
  const buildabilityScore = selectedHex?.buildability_score ?? 100;
  const developmentStatus = normalizedStatus ?? "Potentially buildable";
  const reasonCodes = selectedHex?.classification_reason_codes ?? [];
  const coverage = selectedHex?.coverage_pct;
  const debugTrace = selectedHex?.debug_trace;
  const confidence = selectedHex?.classification_confidence ?? "low";
  const dominantLandUse = selectedHex?.dominant_land_use ?? "unknown";

  return (
    <>
      {hexData.features.map((f) => (
        <Polygon
          key={f.properties.h3_index}
          // GeoJSON coordinates are [lng, lat] — swap to {lat, lng} for Maps API
          paths={f.geometry.coordinates[0].map(([lng, lat]) => ({ lat, lng }))}
          strokeColor="#09090b"
          strokeOpacity={0.5}
          strokeWeight={0.5}
          fillColor={hexFillColor(f.properties)}
          fillOpacity={0.42}
          onClick={() => setSelectedHex(f.properties)}
        />
      ))}

      {selectedHex && (
        <InfoWindow
          position={{ lat: selectedHex.center_lat, lng: selectedHex.center_lng }}
          onCloseClick={() => setSelectedHex(null)}
        >
          <div className="p-2 min-w-[220px] font-sans">
            <div className="flex items-center gap-1.5 mb-2">
              <div
                className="w-3 h-3 rounded-sm"
                style={{ background: hexFillColor(selectedHex) }}
              />
              <span className="text-sm font-bold text-zinc-900">
                {selectedHex.pressure_score.toFixed(1)} / 100
              </span>
            </div>
            <div className="space-y-1 text-xs text-zinc-600">
              {(constrained || nonBuildable || developed) && (
                <p>
                  <span className="font-medium text-zinc-800">Raw demand:</span>{" "}
                  {rawScore.toFixed(1)} / 100
                </p>
              )}
              <p>
                <span className="font-medium text-zinc-800">Distance:</span>{" "}
                {selectedHex.distance_to_campus_miles.toFixed(2)} mi from campus
              </p>
              <p>
                <span className="font-medium text-zinc-800">Permit density:</span>{" "}
                {selectedHex.permit_density.toFixed(2)} / km²
              </p>
              <p>
                <span className="font-medium text-zinc-800">Unit density:</span>{" "}
                {selectedHex.unit_density.toFixed(1)} / km²
              </p>
              <p>
                <span className="font-medium text-zinc-800">Bus stops:</span>{" "}
                {selectedHex.bus_stop_count}
              </p>
              <p>
                <span className="font-medium text-zinc-800">Campus markers:</span>{" "}
                {campusCount} ({dormCount} dorm)
              </p>
              <p>
                <span className="font-medium text-zinc-800">Off-campus housing markers:</span>{" "}
                {offCampusHousingCount}
              </p>
              <p>
                <span className="font-medium text-zinc-800">Existing development markers:</span>{" "}
                {developmentCount}
              </p>
              <p>
                <span className="font-medium text-zinc-800">Non-buildable markers:</span>{" "}
                {nonBuildableCount} ({waterCount} water)
              </p>
              <p>
                <span className="font-medium text-zinc-800">Land constraints:</span>{" "}
                {golfCount} golf, {forestCount} forest, {fieldCount} fields
              </p>
              <p>
                <span className="font-medium text-zinc-800">Buildability:</span>{" "}
                {buildabilityScore.toFixed(1)} / 100
              </p>
              {constrained && (
                <p>
                  <span className="font-medium text-zinc-800">Campus share:</span>{" "}
                  {campusSharePct}%
                </p>
              )}
              {(() => {
                const style = transitBadgeStyle(selectedHex.transit_label);
                return (
                  <span
                    className="inline-block mt-1 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide"
                    style={{ background: style.bg, color: style.text }}
                  >
                    {selectedHex.transit_label}
                  </span>
                );
              })()}
              {coverage && (
                <>
                  <p>
                    <span className="font-medium text-zinc-800">Coverage:</span>{" "}
                    water {formatPct(coverage.water)}, wetland {formatPct(coverage.wetland)},
                    campus {formatPct(coverage.campus)}
                  </p>
                  <p>
                    <span className="font-medium text-zinc-800">Built:</span>{" "}
                    residential {formatPct(coverage.residential_built)},
                    commercial {formatPct(coverage.commercial_built)},
                    parking/infra {formatPct(coverage.parking_infrastructure)}
                  </p>
                  <p>
                    <span className="font-medium text-zinc-800">Open recreation:</span>{" "}
                    {formatPct(coverage.open_recreation)}
                  </p>
                </>
              )}
              <p>
                <span className="font-medium text-zinc-800">Dominant land use:</span>{" "}
                {dominantLandUse.replace(/_/g, " ")}
              </p>
              <p>
                <span className="font-medium text-zinc-800">Confidence:</span>{" "}
                {confidence}
              </p>
              {reasonCodes.length > 0 && (
                <p>
                  <span className="font-medium text-zinc-800">Reasons:</span>{" "}
                  {reasonCodes.map(readableReasonCode).join(", ")}
                </p>
              )}
              {debugTrace?.decision_flags && (
                <p>
                  <span className="font-medium text-zinc-800">Decision flags:</span>{" "}
                  hard={String(Boolean(debugTrace.decision_flags["hard_non_buildable"]))},{" "}
                  campus={String(Boolean(debugTrace.decision_flags["campus_constrained"]))},{" "}
                  developed={String(Boolean(debugTrace.decision_flags["already_developed"]))}
                </p>
              )}
              {debugTrace?.sampling && (
                <p>
                  <span className="font-medium text-zinc-800">Sampling:</span>{" "}
                  {debugTrace.sampling["sample_count"] ?? 0} points, radius{" "}
                  {Number(debugTrace.sampling["coverage_radius_km"] ?? 0).toFixed(3)} km
                </p>
              )}
              {debugTrace?.pressure_components && (
                <p>
                  <span className="font-medium text-zinc-800">Pressure math:</span>{" "}
                  raw {Number(debugTrace.pressure_components["raw_pressure_score"] ?? 0).toFixed(1)} → cap{" "}
                  {Number(debugTrace.pressure_components["pressure_cap"] ?? 0).toFixed(1)} → final{" "}
                  {Number(debugTrace.pressure_components["final_pressure_score"] ?? 0).toFixed(1)}
                </p>
              )}
              {debugTrace?.buildability_components && (
                <p>
                  <span className="font-medium text-zinc-800">Buildability math:</span>{" "}
                  non-build {Number(debugTrace.buildability_components["weighted_non_buildable"] ?? 0).toFixed(2)}, built{" "}
                  {Number(debugTrace.buildability_components["development_pressure"] ?? 0).toFixed(2)}
                </p>
              )}
              <p className="font-medium pt-1" style={{ color: hexFillColor(selectedHex) }}>
                {developmentStatus === "Potentially buildable"
                  ? (OPPORTUNITY_LABEL[selectedHex.label] ?? selectedHex.label)
                  : developmentStatus}
              </p>
            </div>
          </div>
        </InfoWindow>
      )}
    </>
  );
}
