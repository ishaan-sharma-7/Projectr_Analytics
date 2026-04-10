import { useState, useEffect, useRef, useMemo } from "react";
import {
  Map,
  AdvancedMarker,
  MapControl,
  ControlPosition,
  useMap,
  Polygon,
} from "@vis.gl/react-google-maps";
import { Crosshair, Globe, Plus, Minus } from "lucide-react";
import { HexChoropleth } from "./HexChoropleth";
import { UNIVERSITIES } from "../lib/universityList";
import type { UniversitySuggestion } from "../lib/universityList";
import type { HousingPressureScore } from "../lib/api";
import type { HexGeoJSON } from "../lib/hexApi";

/** Merge static list + dynamic pins, deduplicated by name. */
function mergeUniversities(
  dynamic: Record<string, UniversitySuggestion>
): UniversitySuggestion[] {
  const staticNames = new Set(UNIVERSITIES.map((u) => u.name));
  const extras = Object.values(dynamic).filter((d) => !staticNames.has(d.name));
  return [...UNIVERSITIES, ...extras];
}

// Higher score = better developer opportunity → green.
const SCORE_COLOR = (score: number) =>
  score >= 70 ? "#22c55e" : score >= 40 ? "#f59e0b" : "#ef4444";

const NATIONAL_CENTER = { lat: 38.7, lng: -96.5 };
const NATIONAL_ZOOM = 5;
const CAMPUS_ZOOM = 14;

const US_BOUNDS = {
  north: 52.0,
  south: 23.0,
  west: -128.0,
  east: -65.0,
};

function isValidLatLng(lat: number, lng: number): boolean {
  return (
    Number.isFinite(lat)
    && Number.isFinite(lng)
    && lat >= -90
    && lat <= 90
    && lng >= -180
    && lng <= 180
  );
}

function normalizeSchoolName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function getTargetPosition(
  name: string,
  scoreCache: Record<string, HousingPressureScore>,
  dynamicUnis: Record<string, UniversitySuggestion>
): { lat: number; lng: number } | null {
  // Prefer known pin coordinates first so stale score-cache entries cannot
  // send camera moves to an incorrect fallback location.
  const dynamic = dynamicUnis[name];
  if (dynamic && isValidLatLng(dynamic.lat, dynamic.lon)) {
    return { lat: dynamic.lat, lng: dynamic.lon };
  }

  const staticUni = UNIVERSITIES.find((u) => u.name === name);
  if (staticUni && isValidLatLng(staticUni.lat, staticUni.lon)) {
    return { lat: staticUni.lat, lng: staticUni.lon };
  }

  const computed = scoreCache[name];
  if (computed && isValidLatLng(computed.university.lat, computed.university.lon)) {
    return { lat: computed.university.lat, lng: computed.university.lon };
  }

  // Fuzzy fallback for minor naming differences ("Penn State" vs
  // "Pennsylvania State University", punctuation, etc.).
  const normalizedTarget = normalizeSchoolName(name);
  for (const uni of Object.values(dynamicUnis)) {
    if (
      normalizeSchoolName(uni.name) === normalizedTarget
      && isValidLatLng(uni.lat, uni.lon)
    ) {
      return { lat: uni.lat, lng: uni.lon };
    }
  }

  for (const uni of UNIVERSITIES) {
    if (
      normalizeSchoolName(uni.name) === normalizedTarget
      && isValidLatLng(uni.lat, uni.lon)
    ) {
      return { lat: uni.lat, lng: uni.lon };
    }
  }

  for (const value of Object.values(scoreCache)) {
    const uni = value.university;
    if (
      normalizeSchoolName(uni.name) === normalizedTarget
      && isValidLatLng(uni.lat, uni.lon)
    ) {
      return { lat: uni.lat, lng: uni.lon };
    }
  }

  return null;
}

// ── Logo Pin ──────────────────────────────────────────────────────────────────
// Circle with school favicon, pointer triangle at bottom, colored ring.
//
// Image source priority:
//   1. Per-school manual override (for schools whose favicon is the default
//      Google globe — e.g. Washington State, Utah)
//   2. Google s2 favicons by domain
//   3. Clearbit logo API
//   4. Initials fallback (last resort)
//
// The circle background is forced to a per-school brand color so transparent
// PNGs sit cleanly instead of showing the white circle bleeding through the
// edges of the logo.

interface LogoPinProps {
  uni: UniversitySuggestion;
  borderColor: string;
  scale: number;
}

// Per-domain logo overrides — keyed by the bare hostname stored on the
// suggestion. Use a Wikimedia URL when the school's favicon is generic.
const LOGO_OVERRIDES: Record<string, string> = {
  "wsu.edu":
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/Washington_State_Cougars_logo.svg/240px-Washington_State_Cougars_logo.svg.png",
  "utah.edu":
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/Utah_Utes_-_U_logo.svg/240px-Utah_Utes_-_U_logo.svg.png",
  "colostate.edu":
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a1/Colorado_State_University_logo.svg/240px-Colorado_State_University_logo.svg.png",
};

// Per-domain background tint behind transparent logos. Falls back to white
// for any school not listed.
const LOGO_BG: Record<string, string> = {
  "wsu.edu": "#981e32",   // WSU crimson
  "utah.edu": "#cc0000",  // Utah red
  "colostate.edu": "#1E4D2B",  // CSU green
};

function LogoPin({ uni, borderColor, scale }: LogoPinProps) {
  const [srcIdx, setSrcIdx] = useState(0);

  const override = LOGO_OVERRIDES[uni.domain];
  const srcs = override
    ? [override]
    : [
        `https://www.google.com/s2/favicons?domain=${uni.domain}&sz=64`,
        `https://logo.clearbit.com/${uni.domain}`,
      ];

  const src = srcs[srcIdx];
  const bg = LOGO_BG[uni.domain] ?? "#ffffff";

  // Initials fallback
  const initials = uni.name
    .split(/[\s\-&]+/)
    .filter((w) => !["of", "the", "at", "and", "for", "in", "a"].includes(w.toLowerCase()))
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        transform: `scale(${scale})`,
        transformOrigin: "bottom center",
        transition: "transform 0.15s cubic-bezier(0.34,1.56,0.64,1)",
        cursor: "pointer",
        filter: "drop-shadow(0 2px 6px rgba(0,0,0,0.5))",
      }}
    >
      {/* Circle badge */}
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: "50%",
          background: bg,
          border: `2.5px solid ${borderColor}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          overflow: "hidden",
          position: "relative",
        }}
      >
        {src ? (
          <img
            src={src}
            width={26}
            height={26}
            style={{ objectFit: "contain", display: "block" }}
            onError={() => setSrcIdx((i) => i + 1)}
          />
        ) : (
          <span
            style={{
              fontSize: 9,
              fontWeight: 800,
              color: bg === "#ffffff" ? borderColor : "#ffffff",
              letterSpacing: -0.5,
            }}
          >
            {initials}
          </span>
        )}
      </div>

      {/* Pointer triangle */}
      <div
        style={{
          width: 0,
          height: 0,
          borderLeft: "5px solid transparent",
          borderRight: "5px solid transparent",
          borderTop: `7px solid ${borderColor}`,
          marginTop: -1,
        }}
      />
    </div>
  );
}

// ── CameraController ──────────────────────────────────────────────────────────

function CameraController({
  selectedName,
  selectedCoords,
  scoreCache,
  dynamicUnis,
  forceNational,
}: {
  selectedName: string | null;
  selectedCoords?: { lat: number; lng: number } | null;
  scoreCache: Record<string, HousingPressureScore>;
  dynamicUnis: Record<string, UniversitySuggestion>;
  forceNational?: boolean;
}) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;

    if (forceNational || !selectedName) {
      map.moveCamera({ center: NATIONAL_CENTER, zoom: NATIONAL_ZOOM });
      return;
    }

    const target = (
      selectedCoords && isValidLatLng(selectedCoords.lat, selectedCoords.lng)
    )
      ? selectedCoords
      : getTargetPosition(selectedName, scoreCache, dynamicUnis);

    if (target) {
      map.moveCamera({ center: target, zoom: CAMPUS_ZOOM });
    }
  }, [map, selectedName, selectedCoords, scoreCache, dynamicUnis, forceNational]); // eslint-disable-line react-hooks/exhaustive-deps

  return null;
}

// ── RecenterButton ────────────────────────────────────────────────────────────

function RecenterButton({
  selectedName,
  selectedCoords,
  scoreCache,
  dynamicUnis,
  onZoomOut,
  onReturnToCampus,
  onForceNational,
}: {
  selectedName: string | null;
  selectedCoords?: { lat: number; lng: number } | null;
  scoreCache: Record<string, HousingPressureScore>;
  dynamicUnis: Record<string, UniversitySuggestion>;
  onZoomOut?: () => void;
  onReturnToCampus?: () => void;
  onForceNational?: () => void;
}) {
  const map = useMap();

  const handleClick = () => {
    if (!map) return;
    if (!selectedName) {
      map.moveCamera({ center: NATIONAL_CENTER, zoom: NATIONAL_ZOOM });
      return;
    }
    const target = (
      selectedCoords && isValidLatLng(selectedCoords.lat, selectedCoords.lng)
    )
      ? selectedCoords
      : getTargetPosition(selectedName, scoreCache, dynamicUnis);
    if (target) {
      onReturnToCampus?.();
      map.moveCamera({ center: target, zoom: CAMPUS_ZOOM });
    } else {
      map.moveCamera({ center: NATIONAL_CENTER, zoom: NATIONAL_ZOOM });
    }
  };

  const handleZoomOut = () => {
    if (!map) return;
    onForceNational?.();
    map.moveCamera({ center: NATIONAL_CENTER, zoom: NATIONAL_ZOOM });
    onZoomOut?.();
  };

  const btnClass =
    "w-10 h-10 bg-zinc-900/90 border border-zinc-700 hover:border-blue-500 rounded-xl " +
    "flex items-center justify-center text-zinc-400 hover:text-white transition-all shadow-lg backdrop-blur-sm";

  return (
    <MapControl position={ControlPosition.RIGHT_BOTTOM}>
      <div className="mb-3 mr-3 flex flex-col gap-2">
        <button className={btnClass} onClick={() => map?.setZoom((map.getZoom() ?? 10) + 1)} title="Zoom in">
          <Plus className="w-4 h-4" />
        </button>
        <button className={btnClass} onClick={() => map?.setZoom((map.getZoom() ?? 10) - 1)} title="Zoom out">
          <Minus className="w-4 h-4" />
        </button>
        <button className={btnClass} onClick={handleZoomOut} title="Zoom out to national view">
          <Globe className="w-4 h-4" />
        </button>
        <button
          className={btnClass}
          onClick={handleClick}
          title={selectedName ? "Re-center on campus" : "Re-center national view"}
        >
          <Crosshair className="w-4 h-4" />
        </button>
      </div>
    </MapControl>
  );
}

// ── ZoomTracker ───────────────────────────────────────────────────────────────

function ZoomTracker({ onZoomChange }: { onZoomChange: (zoom: number) => void }) {
  const map = useMap();
  useEffect(() => {
    if (!map) return;
    const listener = map.addListener("zoom_changed", () => {
      onZoomChange(map.getZoom() ?? 9);
    });
    return () => listener.remove();
  }, [map, onZoomChange]);
  return null;
}

// ── HexLoadingGrid ────────────────────────────────────────────────────────────
// Renders a phantom honeycomb of blue pulsing polygons anchored to lat/lng so
// they stay fixed to the map during pan/zoom — disappears when real hexes arrive.

type LatLngLit = { lat: number; lng: number };

function buildLoadingHexes(centerLat: number, centerLng: number, rings = 4): LatLngLit[][] {
  // H3 resolution-9 approximate dimensions
  const edgeM = 174; // metres per edge
  const hexW = edgeM * Math.sqrt(3); // pointy-top: point-to-point width
  const hexH = edgeM * 2;            // pointy-top: flat-to-flat height

  const latPerM = 1 / 111_000;
  const lngPerM = 1 / (111_000 * Math.cos((centerLat * Math.PI) / 180));

  const out: { paths: LatLngLit[]; ring: number }[] = [];

  for (let q = -rings; q <= rings; q++) {
    for (let r = -rings; r <= rings; r++) {
      const s = -q - r;
      const ring = Math.max(Math.abs(q), Math.abs(r), Math.abs(s));
      if (ring > rings) continue;

      // Axial → cartesian (pointy-top orientation)
      const xM = hexW * (q + r * 0.5);
      const yM = hexH * 0.75 * r;

      const cLat = centerLat + yM * latPerM;
      const cLng = centerLng + xM * lngPerM;

      const paths: LatLngLit[] = [];
      for (let i = 0; i < 6; i++) {
        const angle = (Math.PI / 3) * i + Math.PI / 6; // pointy-top vertex angles
        paths.push({
          lat: cLat + edgeM * Math.sin(angle) * latPerM,
          lng: cLng + edgeM * Math.cos(angle) * lngPerM,
        });
      }
      out.push({ paths, ring });
    }
  }

  // Sort by ring so animation ripples outward from center
  out.sort((a, b) => a.ring - b.ring);
  return out.map((h) => h.paths);
}

function HexLoadingGrid({ lat, lng }: { lat: number; lng: number }) {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 90);
    return () => clearInterval(id);
  }, []);

  const hexes = useMemo(() => buildLoadingHexes(lat, lng, 4), [lat, lng]);

  return (
    <>
      {hexes.map((paths, i) => {
        // Ripple outward: each hex offset in the wave by its position index
        const t = ((tick * 90 - i * 160) / 2200) % 1;
        const sin = Math.sin(Math.max(0, t) * Math.PI * 2);
        const fillOpacity = 0.06 + 0.28 * Math.max(0, sin);
        const strokeOpacity = 0.25 + 0.45 * Math.max(0, sin);

        return (
          <Polygon
            key={i}
            paths={paths}
            strokeColor="#60a5fa"
            strokeOpacity={strokeOpacity}
            strokeWeight={1}
            fillColor="#3b82f6"
            fillOpacity={fillOpacity}
          />
        );
      })}
    </>
  );
}

// ── MapView ───────────────────────────────────────────────────────────────────

interface MapViewProps {
  selectedName: string | null;
  selectedCoords?: { lat: number; lng: number } | null;
  scoreCache: Record<string, HousingPressureScore>;
  dynamicUnis: Record<string, UniversitySuggestion>;
  activeHexData: HexGeoJSON | null;
  hexRadiusMiles: number;
  onHexRadiusChange: (radius: number) => void;
  onPinClick: (name: string, coords?: { lat: number; lng: number }) => void;
  onZoomOut?: () => void;
  onZoomChange?: (zoom: number) => void;
  onHoverPrefetch?: (name: string) => void;
  isHexLoading?: boolean;
}

export function MapView({
  selectedName,
  selectedCoords,
  scoreCache,
  dynamicUnis,
  activeHexData,
  hexRadiusMiles,
  onHexRadiusChange,
  onPinClick,
  onZoomOut,
  onZoomChange,
  onHoverPrefetch,
  isHexLoading = false,
}: MapViewProps) {
  const allUniversities = mergeUniversities(dynamicUnis);
  const [hoveredName, setHoveredName] = useState<string | null>(null);
  const [forceNational, setForceNational] = useState(false);
  const [localZoom, setLocalZoom] = useState(14);
  const hoverTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (selectedName) setForceNational(false);
  }, [selectedName]);

  return (
    <div className="flex-1 bg-zinc-900 relative text-zinc-900">
      <Map
        mapId="CampusLensMap"
        defaultCenter={NATIONAL_CENTER}
        defaultZoom={NATIONAL_ZOOM}
        minZoom={NATIONAL_ZOOM}
        restriction={{
          latLngBounds: US_BOUNDS,
          strictBounds: false,
        }}
        disableDefaultUI={true}
        gestureHandling="greedy"
      >
        <CameraController
          selectedName={selectedName}
          selectedCoords={selectedCoords}
          scoreCache={scoreCache}
          dynamicUnis={dynamicUnis}
          forceNational={forceNational}
        />
        <RecenterButton
          selectedName={selectedName}
          selectedCoords={selectedCoords}
          scoreCache={scoreCache}
          dynamicUnis={dynamicUnis}
          onZoomOut={onZoomOut}
          onReturnToCampus={() => setForceNational(false)}
          onForceNational={() => setForceNational(true)}
        />
        <ZoomTracker onZoomChange={(z) => { setLocalZoom(z); onZoomChange?.(z); }} />
        {/* Loading phantom hex grid — anchored to map coordinates, moves with pan/zoom */}
        {isHexLoading && localZoom >= 11 && selectedCoords && (
          <HexLoadingGrid lat={selectedCoords.lat} lng={selectedCoords.lng} />
        )}
        {activeHexData && (
          <HexChoropleth hexData={activeHexData} maxDistanceMiles={hexRadiusMiles} />
        )}

        {allUniversities.map((uni, i) => {
          const computed = scoreCache[uni.name];
          const isSelected = selectedName === uni.name;
          const isHovered = hoveredName === uni.name;

          const borderColor = computed
            ? SCORE_COLOR(computed.score)
            : isSelected
            ? "#3b82f6"
            : "#71717a";

          const scale = isSelected ? 1.45 : isHovered ? 1.2 : 1.0;

          return (
            <AdvancedMarker
              key={uni.name}
              position={{ lat: uni.lat, lng: uni.lon }}
              onClick={() => {
                setForceNational(false);
                onPinClick(uni.name, { lat: uni.lat, lng: uni.lon });
              }}
              onMouseEnter={() => {
                setHoveredName(uni.name);
                hoverTimerRef.current = setTimeout(() => onHoverPrefetch?.(uni.name), 300);
              }}
              onMouseLeave={() => {
                setHoveredName(null);
                if (hoverTimerRef.current) {
                  clearTimeout(hoverTimerRef.current);
                  hoverTimerRef.current = null;
                }
              }}
              title={uni.name}
              zIndex={isSelected ? 20 : computed ? 6 : isHovered ? 10 : 1}
            >
              {/* Staggered entrance animation wrapper */}
              <div
                style={{
                  animationDelay: `${i * 30}ms`,
                  animation: "markerIn 0.4s cubic-bezier(0.34,1.56,0.64,1) forwards",
                  opacity: 0,
                }}
              >
                <LogoPin uni={uni} borderColor={borderColor} scale={scale} />
              </div>

              {/* Hover tooltip */}
              <div
                className="absolute bottom-full mb-3 left-1/2 -translate-x-1/2
                           bg-zinc-900/95 border border-zinc-700 rounded-xl px-3 py-2.5
                           whitespace-nowrap shadow-2xl pointer-events-none z-50
                           transition-opacity duration-150"
                style={{
                  backdropFilter: "blur(8px)",
                  opacity: isHovered ? 1 : 0,
                  visibility: isHovered ? "visible" : "hidden",
                }}
              >
                <p className="text-xs font-semibold text-white leading-tight">{uni.name}</p>
                <p className="text-xs text-zinc-400 mt-0.5">{uni.city}, {uni.state}</p>
                {computed ? (
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <div className="w-2 h-2 rounded-full" style={{ background: SCORE_COLOR(computed.score) }} />
                    <span className="text-xs font-medium" style={{ color: SCORE_COLOR(computed.score) }}>
                      {computed.score.toFixed(0)}/100
                    </span>
                  </div>
                ) : (
                  <p className="text-xs text-blue-400 mt-1.5">Click to view →</p>
                )}
              </div>
            </AdvancedMarker>
          );
        })}
      </Map>

      {/* Radius slider */}
      {activeHexData && (
        <div className="absolute top-4 left-4 bg-zinc-950/90 backdrop-blur-sm border border-zinc-800 rounded-xl p-3 shadow-lg z-10">
          <label className="text-xs text-zinc-400 font-medium block mb-1.5">
            Radius: <span className="text-white">{hexRadiusMiles.toFixed(1)} mi</span>
          </label>
          <input
            type="range"
            min={0.5}
            max={5.0}
            step={0.1}
            value={hexRadiusMiles}
            onChange={(e) => onHexRadiusChange(parseFloat(e.target.value))}
            className="w-36 h-1.5 accent-blue-500 cursor-pointer"
          />
          <div className="flex justify-between text-[10px] text-zinc-600 mt-0.5">
            <span>0.5 mi</span>
            <span>5.0 mi</span>
          </div>
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-6 left-6 bg-zinc-950/80 backdrop-blur-sm border border-zinc-800 rounded-xl p-3 text-xs pointer-events-none">
        {activeHexData ? (
          <div className="flex gap-4 flex-wrap">
            {[
              ["Strong Opportunity", "#22c55e"],
              ["Emerging", "#f59e0b"],
              ["Saturated", "#ef4444"],
              ["Already Developed", "#a855f7"],
              ["On-campus constrained", "#6b7280"],
              ["Hard non-buildable", "#64748b"],
            ].map(([label, color]) => (
              <div key={label} className="flex items-center gap-1.5">
                <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
                <span className="text-zinc-400">{label}</span>
              </div>
            ))}
            <div className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-sm border-2" style={{ borderColor: "#d97706", background: "transparent" }} />
              <span className="text-zinc-400">Land available</span>
            </div>
          </div>
        ) : (
          <p className="text-zinc-500">
            <span className="text-zinc-300 font-medium">{allUniversities.length} universities</span>
          </p>
        )}
      </div>
    </div>
  );
}
