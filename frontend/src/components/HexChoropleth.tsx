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

// One-sentence plain-English verdict for the InfoWindow.
function hexVerdict(hex: HexFeatureProperties, status: NormalizedStatus): string {
  if (status === "Hard non-buildable") {
    return "Land constraints prevent development — water, wetland, or preserved open space.";
  }
  if (status === "On-campus constrained") {
    return "Campus-controlled land. University approval required for any off-campus development nearby.";
  }
  if (status === "Already developed (infill/redevelopment only)") {
    return hex.pressure_score >= 55
      ? "High-demand infill zone — redevelopment or value-add opportunity."
      : "Existing structures present. Moderate demand; infill or value-add play.";
  }
  // Zoning overrides for buildable hexes
  if (hex.zoning_pbsh_signal === "restrictive") {
    return `Demand is here but zoning (${hex.zoning_code}) requires rezoning before PBSH can be built. Planning commission approval needed.`;
  }
  if (hex.zoning_pbsh_signal === "negative") {
    return `Zoned ${hex.zoning_code} — industrial or R&D use. Residential conversion is very costly and unlikely to be approved.`;
  }
  if (hex.zoning_pbsh_signal === "constrained") {
    return "University-zoned land. Effectively off-limits for private development without institutional partnership.";
  }
  // Potentially buildable
  const s = hex.pressure_score;
  const t = hex.transit_label;
  if (s >= 70 && t === "Transit Hub") return "Prime site — strong demand pressure and transit access. Leading development target.";
  if (s >= 70) return "Strong demand near campus with limited supply. High-priority development site.";
  if (s >= 55 && t !== "Isolated") return "Emerging opportunity with solid transit connectivity. Good mid-tier target.";
  if (s >= 55) return "Moderate demand pressure. Verify site-level buildability before committing.";
  if (s >= 40) return "Below-average demand signal. May suit smaller-scale or value-add projects.";
  return "Low demand in this zone. Elevated market-entry risk.";
}

function zoningBadgeStyle(signal: HexFeatureProperties["zoning_pbsh_signal"]): {
  bg: string;
  text: string;
  dot: string;
} {
  switch (signal) {
    case "positive":    return { bg: "#dcfce7", text: "#15803d", dot: "#22c55e" };
    case "neutral":     return { bg: "#fef9c3", text: "#854d0e", dot: "#eab308" };
    case "restrictive": return { bg: "#ffedd5", text: "#9a3412", dot: "#f97316" };
    case "constrained": return { bg: "#f4f4f5", text: "#52525b", dot: "#a1a1aa" };
    case "negative":    return { bg: "#fee2e2", text: "#991b1b", dot: "#ef4444" };
    default:            return { bg: "#f4f4f5", text: "#71717a", dot: "#a1a1aa" };
  }
}

const ZONING_SIGNAL_LABEL: Record<string, string> = {
  positive:    "By-right PBSH",
  neutral:     "Conditional",
  restrictive: "Rezoning required",
  constrained: "Institutional",
  negative:    "Not residential",
};

// "high"/"medium"/"low" come from the backend hex labels — we relabel them
// in opportunity language without changing the underlying keys.
const OPPORTUNITY_LABEL: Record<string, string> = {
  high: "Strong opportunity",
  medium: "Emerging market",
  low: "Saturated market",
};

function opportunityLabel(hex: HexFeatureProperties): string {
  if (hex.zoning_pbsh_signal === "restrictive") return "Rezoning risk";
  if (hex.zoning_pbsh_signal === "negative") return "Not buildable (zoning)";
  return OPPORTUNITY_LABEL[hex.label] ?? hex.label;
}

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

// Amber-brown — distinct from the green→red demand gradient and from
// the gray physical-constraint palette. Reads as "caution: political risk."
const ZONING_BLOCK_COLOR = "#b45309";

function hexFillColor(hex: HexFeatureProperties): string {
  const status = normalizeDevelopmentStatus(hex);
  if (status === "Hard non-buildable") return "#64748b";
  if (status === "On-campus constrained") return "#6b7280";
  if (status === "Already developed (infill/redevelopment only)") return "#a855f7";
  // Potentially buildable physically, but zoning blocks residential use
  if (
    status === "Potentially buildable" &&
    (hex.zoning_pbsh_signal === "restrictive" || hex.zoning_pbsh_signal === "negative")
  ) return ZONING_BLOCK_COLOR;
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


export function HexChoropleth({
  hexData,
  maxDistanceMiles,
}: {
  hexData: HexGeoJSON;
  maxDistanceMiles?: number;
}) {
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
  const developmentStatus = normalizedStatus ?? "Potentially buildable";

  return (
    <>
      {hexData.features
        .filter((f) => maxDistanceMiles == null || f.properties.distance_to_campus_miles <= maxDistanceMiles)
        .map((f) => (
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
          headerDisabled={true}
        >
          <div className="p-2 min-w-[230px] max-w-[270px] font-sans">
            {/* Header row: score chip + close */}
            <div className="flex items-center justify-between mb-2.5">
              <div className="flex items-center gap-1.5">
                <div
                  className="w-3 h-3 rounded-sm flex-shrink-0"
                  style={{ background: hexFillColor(selectedHex) }}
                />
                <span className="text-sm font-bold text-zinc-900">
                  {nonBuildable || constrained
                    ? developmentStatus
                    : `${selectedHex.pressure_score.toFixed(0)} / 100`}
                </span>
              </div>
              <button
                onClick={() => setSelectedHex(null)}
                className="ml-4 text-zinc-400 hover:text-zinc-700 text-base leading-none"
                aria-label="Close"
              >
                ✕
              </button>
            </div>

            {/* Opportunity label (buildable hexes only) */}
            {!nonBuildable && !constrained && (
              <p
                className="text-xs font-semibold mb-2"
                style={{ color: hexFillColor(selectedHex) }}
              >
                {developed
                  ? "Infill / Redevelopment"
                  : opportunityLabel(selectedHex)}
              </p>
            )}

            {/* Verdict sentence */}
            <p className="text-xs text-zinc-600 leading-snug mb-2.5 border-b border-zinc-100 pb-2.5">
              {hexVerdict(selectedHex, normalizedStatus!)}
            </p>

            {/* Key stats */}
            <div className="space-y-1.5 text-xs text-zinc-600">
              <div className="flex justify-between">
                <span className="text-zinc-500">Distance</span>
                <span className="font-medium text-zinc-800">
                  {selectedHex.distance_to_campus_miles.toFixed(2)} mi from campus
                </span>
              </div>

              {(constrained || nonBuildable || developed) && rawScore > 0 && (
                <div className="flex justify-between">
                  <span className="text-zinc-500">Underlying demand</span>
                  <span className="font-medium text-zinc-800">{rawScore.toFixed(0)} / 100</span>
                </div>
              )}

              <div className="flex justify-between">
                <span className="text-zinc-500">New construction nearby</span>
                <span className="font-medium text-zinc-800">
                  {selectedHex.permit_density.toFixed(2)} permits / km²
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-zinc-500">Transit access</span>
                <span>
                  {(() => {
                    const style = transitBadgeStyle(selectedHex.transit_label);
                    return (
                      <span
                        className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide"
                        style={{ background: style.bg, color: style.text }}
                      >
                        {selectedHex.transit_label} · {selectedHex.bus_stop_count} stop{selectedHex.bus_stop_count !== 1 ? "s" : ""}
                      </span>
                    );
                  })()}
                </span>
              </div>

              <div className="flex justify-between">
                <span className="text-zinc-500">Existing housing density</span>
                <span className="font-medium text-zinc-800">
                  {selectedHex.unit_density.toFixed(0)} units / km²
                </span>
              </div>

              {selectedHex.zoning_code && (
                <div className="flex justify-between items-center pt-1 mt-0.5 border-t border-zinc-100">
                  <span className="text-zinc-500">Zoning</span>
                  <span className="flex items-center gap-1.5">
                    <span className="font-medium text-zinc-800 text-[11px]">
                      {selectedHex.zoning_code}
                    </span>
                    {(() => {
                      const style = zoningBadgeStyle(selectedHex.zoning_pbsh_signal);
                      return (
                        <span
                          className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide flex items-center gap-1"
                          style={{ background: style.bg, color: style.text }}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full inline-block"
                            style={{ background: style.dot }}
                          />
                          {ZONING_SIGNAL_LABEL[selectedHex.zoning_pbsh_signal ?? ""] ?? selectedHex.zoning_pbsh_signal}
                        </span>
                      );
                    })()}
                  </span>
                </div>
              )}

              {/* Land parcels section */}
              {(selectedHex.vacant_parcel_count ?? 0) > 0 && selectedHex.land_parcels && (
                <div className="pt-1.5 mt-1 border-t border-zinc-100">
                  <div className="flex justify-between items-center mb-1">
                    <span className="text-zinc-500">Available land</span>
                    <span
                      className="px-1.5 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide"
                      style={{ background: "#fef9c3", color: "#854d0e" }}
                    >
                      {selectedHex.vacant_parcel_count} parcel{selectedHex.vacant_parcel_count !== 1 ? "s" : ""}
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {selectedHex.land_parcels.slice(0, 3).map((parcel, i) => (
                      <div key={i} className="bg-zinc-50 rounded p-1.5 text-[10px] text-zinc-700">
                        <div className="font-medium text-zinc-900 truncate">
                          {parcel.address || "Address not available"}
                        </div>
                        <div className="flex justify-between mt-0.5">
                          <span>
                            {parcel.lot_size_acres > 0
                              ? `${parcel.lot_size_acres.toFixed(2)} ac`
                              : parcel.land_use}
                          </span>
                          <span className="font-medium">
                            {parcel.land_value > 0
                              ? `$${(parcel.land_value / 1000).toFixed(0)}k land value`
                              : parcel.market_value > 0
                              ? `$${(parcel.market_value / 1000).toFixed(0)}k assessed`
                              : "Value unknown"}
                          </span>
                        </div>
                        <div className="flex justify-between mt-0.5 text-zinc-500">
                          <span className="truncate max-w-[120px]">{parcel.owner_name}</span>
                          {parcel.is_absentee && (
                            <span
                              className="px-1 py-0 rounded text-[9px] font-semibold uppercase"
                              style={{ background: "#fce7f3", color: "#9d174d" }}
                            >
                              Absentee owner
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                    {(selectedHex.vacant_parcel_count ?? 0) > 3 && (
                      <div className="text-[10px] text-zinc-400 text-center">
                        +{(selectedHex.vacant_parcel_count ?? 0) - 3} more parcel{(selectedHex.vacant_parcel_count ?? 0) - 3 !== 1 ? "s" : ""}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </InfoWindow>
      )}
    </>
  );
}
