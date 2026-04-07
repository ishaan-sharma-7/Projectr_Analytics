import { useState, useEffect } from "react";
import {
  Map,
  AdvancedMarker,
  Pin,
  MapControl,
  ControlPosition,
  useMap,
} from "@vis.gl/react-google-maps";
import { Crosshair } from "lucide-react";
import { HexChoropleth } from "./HexChoropleth";
import type { UniversityListItem, HousingPressureScore } from "../lib/api";
import type { HexGeoJSON } from "../lib/hexApi";

// ── Helpers ──────────────────────────────────────────────────────────────────

const SCORE_COLOR = (score: number) =>
  score >= 70 ? "#ef4444" : score >= 40 ? "#eab308" : "#22c55e";

const LABEL_TEXT: Record<string, string> = {
  high: "High Pressure",
  medium: "Emerging",
  low: "Balanced",
};

const NATIONAL_CENTER = { lat: 39.5, lng: -98.35 };
const NATIONAL_ZOOM = 4;
const CAMPUS_ZOOM = 12;

// ── CameraController — must live inside <Map> to access useMap() ──────────────

function CameraController({ target }: { target: HousingPressureScore | null }) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;
    if (target) {
      map.panTo({ lat: target.university.lat, lng: target.university.lon });
      const t = setTimeout(() => map.setZoom(CAMPUS_ZOOM), 250);
      return () => clearTimeout(t);
    } else {
      map.panTo(NATIONAL_CENTER);
      const t = setTimeout(() => map.setZoom(NATIONAL_ZOOM), 250);
      return () => clearTimeout(t);
    }
  }, [map, target]);

  return null;
}

// ── RecenterButton — must live inside <Map> to access useMap() ───────────────

function RecenterButton({ target }: { target: HousingPressureScore | null }) {
  const map = useMap();

  const handleClick = () => {
    if (!map) return;
    if (target) {
      map.panTo({ lat: target.university.lat, lng: target.university.lon });
      setTimeout(() => map.setZoom(CAMPUS_ZOOM), 250);
    } else {
      map.panTo(NATIONAL_CENTER);
      setTimeout(() => map.setZoom(NATIONAL_ZOOM), 250);
    }
  };

  return (
    <MapControl position={ControlPosition.RIGHT_BOTTOM}>
      <button
        onClick={handleClick}
        title={target ? "Re-center on campus" : "Re-center national view"}
        className="mb-3 mr-3 w-10 h-10 bg-zinc-900/90 border border-zinc-700
                   hover:border-blue-500 rounded-xl flex items-center justify-center
                   text-zinc-400 hover:text-white transition-all shadow-lg backdrop-blur-sm"
      >
        <Crosshair className="w-4 h-4" />
      </button>
    </MapControl>
  );
}

// ── MapView ───────────────────────────────────────────────────────────────────

interface MapViewProps {
  universities: UniversityListItem[];
  activeScore: HousingPressureScore | null;
  hexData: HexGeoJSON | null;
  onMarkerClick: (unitid: number) => void;
}

export function MapView({ universities, activeScore, hexData, onMarkerClick }: MapViewProps) {
  const [hoveredUniId, setHoveredUniId] = useState<number | null>(null);

  return (
    <div className="flex-1 bg-zinc-900 relative">
      <Map
        mapId="CampusLensMap"
        defaultCenter={NATIONAL_CENTER}
        defaultZoom={NATIONAL_ZOOM}
        disableDefaultUI={true}
        zoomControl={true}
        gestureHandling="greedy"
      >
        <CameraController target={activeScore} />
        <RecenterButton target={activeScore} />

        {/* H3 hex choropleth — shown when a university is active */}
        {hexData && <HexChoropleth hexData={hexData} />}

        {/* National pre-scored university markers */}
        {universities.map((uni, i) => {
          const isActive = activeScore?.university.unitid === uni.unitid;
          const isHovered = hoveredUniId === uni.unitid;

          return (
            <AdvancedMarker
              key={uni.unitid}
              position={{ lat: uni.lat, lng: uni.lon }}
              onClick={() => onMarkerClick(uni.unitid)}
              onMouseEnter={() => setHoveredUniId(uni.unitid)}
              onMouseLeave={() => setHoveredUniId(null)}
              title={`${uni.name} — ${uni.score.toFixed(0)}/100`}
              zIndex={isActive ? 10 : isHovered ? 5 : 1}
            >
              {/* Staggered entrance animation */}
              <div
                style={{
                  animationDelay: `${i * 40}ms`,
                  animation: "markerIn 0.4s cubic-bezier(0.34,1.56,0.64,1) forwards",
                  opacity: 0,
                }}
              >
                <Pin
                  background={SCORE_COLOR(uni.score)}
                  borderColor="#18181b"
                  glyphColor="#ffffff"
                  scale={isActive ? 1.4 : 1.0}
                />
              </div>

              {/* Hover tooltip */}
              {isHovered && !isActive && (
                <div
                  className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2
                             bg-zinc-900/95 border border-zinc-700 rounded-xl px-3 py-2.5
                             whitespace-nowrap shadow-2xl pointer-events-none z-50"
                  style={{ backdropFilter: "blur(8px)" }}
                >
                  <p className="text-xs font-semibold text-white leading-tight">{uni.name}</p>
                  <p className="text-xs text-zinc-400 mt-0.5">
                    {uni.city}, {uni.state}
                  </p>
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ background: SCORE_COLOR(uni.score) }}
                    />
                    <span
                      className="text-xs font-medium"
                      style={{ color: SCORE_COLOR(uni.score) }}
                    >
                      {uni.score.toFixed(0)}/100 · {LABEL_TEXT[uni.score_label]}
                    </span>
                  </div>
                </div>
              )}
            </AdvancedMarker>
          );
        })}
      </Map>

      {/* Map legend */}
      <div className="absolute bottom-6 left-6 bg-zinc-950/80 backdrop-blur-sm border border-zinc-800 rounded-xl p-3 text-xs flex gap-4 pointer-events-none">
        {[
          ["High Pressure", "#ef4444"],
          ["Emerging", "#eab308"],
          ["Balanced", "#22c55e"],
        ].map(([label, color]) => (
          <div key={label} className="flex items-center gap-1.5">
            <div className="w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            <span className="text-zinc-400">{label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
