import { useState, useEffect, useMemo, useRef } from "react";
import { InfoWindow, useMap } from "@vis.gl/react-google-maps";
import { GoogleMapsOverlay } from "@deck.gl/google-maps";
import { H3HexagonLayer } from "@deck.gl/geo-layers";
import type { HexGeoJSON, HexFeatureProperties } from "../lib/hexApi";
import { detectPBSHFromParcels } from "../lib/pbshOperators";

/** Convert CSS hex color + opacity to deck.gl RGBA tuple (0-255). */
function hexToRgba(hex: string, opacity: number): [number, number, number, number] {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return [r, g, b, Math.round(opacity * 255)];
}


// Label-driven color palette. Each label gets a distinct, meaningful color.
const LABEL_COLORS: Record<string, string> = {
  protected:      "#64748b",  // slate gray — natural land, can't build
  campus:         "#6b7280",  // neutral gray — university land
  developed:      "#a855f7",  // purple — already built
  constrained:    "#78716c",  // warm gray — terrain/zoning constraints
  zoning_blocked: "#b45309",  // amber — buildable but zoning blocks
  prime:          "#22c55e",  // bright green — best opportunity
  opportunity:    "#84cc16",  // lime — good opportunity
  emerging:       "#14b8a6",  // teal — some potential
  open_land:      "#60a5fa",  // light blue — buildable but low demand, not bad just empty
  // Legacy fallbacks
  high:           "#22c55e",
  medium:         "#eab308",
  low:            "#60a5fa",
};

// One-sentence plain-English verdict for the InfoWindow.
function hexVerdict(hex: HexFeatureProperties, status: NormalizedStatus): string {
  if (status === "Hard non-buildable") {
    return "Land constraints prevent development — water, wetland, forest, or preserved open space.";
  }
  if (status === "Likely non-buildable (water/land-use constraints)") {
    return "Terrain or zoning constraints make development unlikely. May require environmental review or rezoning.";
  }
  if (status === "On-campus constrained") {
    return "Campus-controlled land. University approval required for any development.";
  }
  if (status === "Already developed (infill/redevelopment only)") {
    return hex.pressure_score >= 40
      ? "High-demand infill zone — redevelopment or value-add opportunity."
      : "Existing structures present. Infill or value-add play.";
  }
  if (hex.zoning_pbsh_signal === "restrictive") {
    return `Buildable land but zoning (${hex.zoning_code}) requires rezoning for PBSH. Planning commission approval needed.`;
  }
  if (hex.zoning_pbsh_signal === "negative") {
    return `Zoned ${hex.zoning_code} — not residential. Conversion is costly and unlikely to be approved.`;
  }
  if (hex.zoning_pbsh_signal === "constrained") {
    return "University-zoned land. Off-limits for private development without institutional partnership.";
  }
  const lots = hex.vacant_parcel_count ?? 0;
  const lotSuffix = lots > 0 ? ` ${lots} vacant lot${lots !== 1 ? "s" : ""} available.` : "";
  const t = hex.transit_label;
  if (hex.label === "prime") {
    return t === "Transit Hub"
      ? `Prime site — strong demand and transit access. Top development target.${lotSuffix}`
      : `Strong demand near campus. High-priority development site.${lotSuffix}`;
  }
  if (hex.label === "opportunity") {
    return `Solid development potential with moderate demand signal.${lotSuffix}`;
  }
  if (hex.label === "emerging") {
    return lots > 0
      ? `Lower demand but ${lots} vacant lot${lots !== 1 ? "s" : ""} available — potential land play.`
      : "Some development potential. Verify site-level feasibility.";
  }
  // open_land
  return lots > 0
    ? `Open land with ${lots} lot${lots !== 1 ? "s" : ""}. Low demand — speculative opportunity.`
    : "Open land with low demand. Not saturated, just far from the action.";
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

const OPPORTUNITY_LABEL: Record<string, string> = {
  protected:      "Protected land",
  campus:         "Campus land",
  developed:      "Developed area",
  constrained:    "Terrain constraints",
  zoning_blocked: "Zoning blocked",
  prime:          "Prime site",
  opportunity:    "Development opportunity",
  emerging:       "Emerging area",
  open_land:      "Open land",
  // Legacy
  high:           "Strong opportunity",
  medium:         "Emerging market",
  low:            "Open land",
};

function opportunityLabel(hex: HexFeatureProperties): string {
  return OPPORTUNITY_LABEL[hex.label] ?? hex.label;
}

type NormalizedStatus =
  | "Hard non-buildable"
  | "On-campus constrained"
  | "Already developed (infill/redevelopment only)"
  | "Likely non-buildable (water/land-use constraints)"
  | "Potentially buildable";

function normalizeDevelopmentStatus(hex: HexFeatureProperties): NormalizedStatus {
  const status = hex.development_status;
  if (status === "Hard non-buildable") return status;
  if (status === "On-campus constrained") return status;
  if (status === "Already developed (infill/redevelopment only)") return status;
  if (status === "Likely non-buildable (water/land-use constraints)") return status;
  if (status === "Potentially buildable") return status;
  if (hex.on_campus_constrained) return "On-campus constrained";
  if (hex.already_developed_for_housing) return "Already developed (infill/redevelopment only)";
  if (hex.buildable_for_housing === false) return "Hard non-buildable";
  return "Potentially buildable";
}

function hexFillColor(hex: HexFeatureProperties): string {
  return LABEL_COLORS[hex.label] ?? "#60a5fa";
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


type LandParcelItem = NonNullable<HexFeatureProperties["land_parcels"]>[number];

export function HexChoropleth({
  hexData,
  maxDistanceMiles,
  onViewAllParcels,
  onHexSelect,
  focusHexId,
}: {
  hexData: HexGeoJSON;
  maxDistanceMiles?: number;
  onViewAllParcels?: (parcels: LandParcelItem[], label: string) => void;
  onHexSelect?: (hex: HexFeatureProperties | null) => void;
  focusHexId?: string | null;
}) {
  const map = useMap();
  const overlayRef = useRef<GoogleMapsOverlay | null>(null);
  const [selectedHex, setSelectedHexLocal] = useState<HexFeatureProperties | null>(null);
  const setSelectedHex = (hex: HexFeatureProperties | null) => {
    setSelectedHexLocal(hex);
    onHexSelect?.(hex);
  };

  // Fast lookup: h3_index → properties
  const propsMap = useMemo(() => {
    const m = new Map<string, HexFeatureProperties>();
    for (const f of hexData.features) m.set(f.properties.h3_index, f.properties);
    return m;
  }, [hexData]);

  // Filtered feature list (stable reference when inputs don't change)
  const filteredFeatures = useMemo(
    () =>
      maxDistanceMiles == null
        ? hexData.features
        : hexData.features.filter(
            (f) => f.properties.distance_to_campus_miles <= maxDistanceMiles
          ),
    [hexData, maxDistanceMiles]
  );

  // ── deck.gl WebGL overlay — renders all hexes on the GPU ──
  // Attach overlay to map once; update layers when data changes.
  useEffect(() => {
    if (!map) return;
    if (!overlayRef.current) {
      overlayRef.current = new GoogleMapsOverlay({ interleaved: false });
      overlayRef.current.setMap(map as unknown as google.maps.Map);
    }
    return () => {
      overlayRef.current?.setMap(null);
      overlayRef.current?.finalize();
      overlayRef.current = null;
    };
  }, [map]);

  // Update deck.gl layers when hex data changes
  useEffect(() => {
    if (!overlayRef.current || !filteredFeatures.length) {
      overlayRef.current?.setProps({ layers: [] });
      return;
    }
    // Two layers: fills underneath, then outlines on top so borders aren't
    // hidden by adjacent hex fills.
    const fillLayer = new H3HexagonLayer<(typeof filteredFeatures)[number]>({
      id: "hex-fill",
      data: filteredFeatures,
      getHexagon: (d) => d.properties.h3_index,
      getFillColor: (d) => hexToRgba(LABEL_COLORS[d.properties.label] ?? "#60a5fa", 0.45),
      filled: true,
      stroked: false,
      pickable: true,
      onClick: (info) => {
        if (info.object) setSelectedHex(info.object.properties);
      },
      highPrecision: true,
      updateTriggers: { getFillColor: [hexData] },
    });
    const outlineLayer = new H3HexagonLayer<(typeof filteredFeatures)[number]>({
      id: "hex-outline",
      data: filteredFeatures,
      getHexagon: (d) => d.properties.h3_index,
      filled: false,
      stroked: true,
      getLineColor: [0, 0, 0, 100],
      getLineWidth: 1,
      lineWidthUnits: "pixels",
      lineWidthMinPixels: 1,
      highPrecision: true,
      pickable: false,
    });
    overlayRef.current.setProps({ layers: [fillLayer, outlineLayer] });
  }, [filteredFeatures, hexData]);

  // External hex selection (e.g. from chat agent)
  useEffect(() => {
    if (!focusHexId) return;
    const props = propsMap.get(focusHexId);
    if (props) {
      setSelectedHexLocal(props);
      onHexSelect?.(props);
    }
  }, [focusHexId]);

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
            <p className="text-xs text-zinc-600 leading-snug mb-2.5">
              {hexVerdict(selectedHex, normalizedStatus!)}
            </p>

            {/* Land availability callout — shown above stats when present */}
            {(selectedHex.vacant_parcel_count ?? 0) > 0 && selectedHex.land_parcels && (() => {
              const parcels = selectedHex.land_parcels!;
              const absenteeCount = parcels.filter(p => p.is_absentee).length;
              const landValues = parcels.filter(p => p.land_value > 0).map(p => p.land_value);
              const avgLandValue = landValues.length > 0
                ? landValues.reduce((a, b) => a + b, 0) / landValues.length
                : 0;
              return (
                <div
                  className="mb-2.5 rounded-md p-2 border"
                  style={{ background: "#fffbeb", borderColor: "#d97706" }}
                >
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[11px] font-bold" style={{ color: "#92400e" }}>
                      Land available nearby
                    </span>
                    <span
                      className="px-1.5 py-0.5 rounded-full text-[10px] font-bold"
                      style={{ background: "#d97706", color: "#fff" }}
                    >
                      {selectedHex.vacant_parcel_count} lot{selectedHex.vacant_parcel_count !== 1 ? "s" : ""}
                    </span>
                  </div>
                  {avgLandValue > 0 && (
                    <div className="text-[10px] mb-1" style={{ color: "#78350f" }}>
                      Avg land value: <span className="font-semibold">${(avgLandValue / 1000).toFixed(0)}k</span>
                    </div>
                  )}
                  {absenteeCount > 0 && (
                    <div className="text-[10px] mb-1.5" style={{ color: "#78350f" }}>
                      <span className="font-semibold">{absenteeCount}</span> absentee owner{absenteeCount !== 1 ? "s" : ""} — potential off-market leads
                    </div>
                  )}
                  <div className="space-y-1">
                    {parcels.slice(0, 2).map((parcel, i) => (
                      <div key={i} className="bg-white rounded p-1.5 text-[10px]" style={{ borderLeft: "2px solid #d97706" }}>
                        <div className="font-medium text-zinc-800 truncate">
                          {parcel.address || "Address not listed"}
                        </div>
                        <div className="flex justify-between mt-0.5 text-zinc-500">
                          <span>
                            {parcel.lot_size_acres > 0 ? `${parcel.lot_size_acres.toFixed(2)} ac` : parcel.land_use}
                          </span>
                          <span className="font-medium text-zinc-700">
                            {parcel.land_value > 0
                              ? `$${(parcel.land_value / 1000).toFixed(0)}k`
                              : parcel.market_value > 0
                              ? `$${(parcel.market_value / 1000).toFixed(0)}k`
                              : "—"}
                          </span>
                        </div>
                        <div className="flex justify-between mt-0.5">
                          <span className="text-zinc-400 truncate max-w-[130px]">{parcel.owner_name}</span>
                          {parcel.is_absentee && (
                            <span
                              className="px-1 rounded text-[9px] font-semibold uppercase"
                              style={{ background: "#fce7f3", color: "#9d174d" }}
                            >
                              Absentee
                            </span>
                          )}
                        </div>
                      </div>
                    ))}
                    {parcels.length > 2 && (
                      <button
                        onClick={() => {
                          const label = `${selectedHex.vacant_parcel_count} lots near hex #${selectedHex.hex_number ?? ""}`;
                          onViewAllParcels?.(parcels, label);
                          setSelectedHex(null);
                        }}
                        className="w-full text-[10px] text-center py-1 rounded font-medium transition-colors"
                        style={{ color: "#92400e", background: "#fef3c7" }}
                        onMouseEnter={e => (e.currentTarget.style.background = "#fde68a")}
                        onMouseLeave={e => (e.currentTarget.style.background = "#fef3c7")}
                      >
                        +{parcels.length - 2} more lot{parcels.length - 2 !== 1 ? "s" : ""} — view all in sidebar →
                      </button>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* PBSH operator detection (Option A — name matching on parcel data) */}
            {(() => {
              const parcels = selectedHex.land_parcels ?? [];
              const detected = detectPBSHFromParcels(parcels);
              if (detected.length === 0) return null;
              return (
                <div
                  className="mb-2.5 rounded-md p-2 border"
                  style={{ background: "#fef2f2", borderColor: "#f87171" }}
                >
                  <div className="flex items-center gap-1.5 mb-1">
                    <span className="text-[10px] font-bold" style={{ color: "#991b1b" }}>
                      Institutional land-banking detected
                    </span>
                  </div>
                  <div className="space-y-0.5">
                    {detected.map(({ operator, parcel_count }) => (
                      <div key={operator} className="text-[10px]" style={{ color: "#7f1d1d" }}>
                        <span className="font-semibold">{operator}</span>
                        {" — "}{parcel_count} parcel{parcel_count !== 1 ? "s" : ""} in tax records
                      </div>
                    ))}
                  </div>
                  <p className="text-[9px] mt-1" style={{ color: "#b91c1c" }}>
                    Matched via owner name · built PBSH may not appear here
                  </p>
                </div>
              );
            })()}

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

            </div>
          </div>
        </InfoWindow>
      )}
    </>
  );
}
