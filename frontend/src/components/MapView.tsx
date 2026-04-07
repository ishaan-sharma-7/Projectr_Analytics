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
import { UNIVERSITIES } from "../lib/universityList";
import type { HousingPressureScore } from "../lib/api";
import type { HexGeoJSON } from "../lib/hexApi";

const SCORE_COLOR = (score: number) =>
  score >= 70 ? "#ef4444" : score >= 40 ? "#eab308" : "#22c55e";

const NATIONAL_CENTER = { lat: 39.5, lng: -98.35 };
const NATIONAL_ZOOM = 4;
const CAMPUS_ZOOM = 12;

// ── CameraController ──────────────────────────────────────────────────────────
// Pans immediately on selectedName change using static list coordinates,
// so the camera moves on pin click — not after the 15-second computation.

interface CameraProps {
  selectedName: string | null;
  scoreCache: Record<string, HousingPressureScore>;
}

function CameraController({ selectedName, scoreCache }: CameraProps) {
  const map = useMap();

  useEffect(() => {
    if (!map) return;

    if (!selectedName) {
      map.panTo(NATIONAL_CENTER);
      const t = setTimeout(() => map.setZoom(NATIONAL_ZOOM), 250);
      return () => clearTimeout(t);
    }

    // Prefer exact lat/lon from computed result if available
    const computed = scoreCache[selectedName];
    const target = computed
      ? { lat: computed.university.lat, lng: computed.university.lon }
      : (() => {
          const u = UNIVERSITIES.find((u) => u.name === selectedName);
          return u ? { lat: u.lat, lng: u.lon } : null;
        })();

    if (target) {
      map.panTo(target);
      const t = setTimeout(() => map.setZoom(CAMPUS_ZOOM), 250);
      return () => clearTimeout(t);
    }
  }, [map, selectedName]); // intentionally exclude scoreCache — only move on selection change

  return null;
}

// ── RecenterButton ────────────────────────────────────────────────────────────

interface RecenterProps {
  selectedName: string | null;
  scoreCache: Record<string, HousingPressureScore>;
}

function RecenterButton({ selectedName, scoreCache }: RecenterProps) {
  const map = useMap();

  const handleClick = () => {
    if (!map) return;

    if (!selectedName) {
      map.panTo(NATIONAL_CENTER);
      setTimeout(() => map.setZoom(NATIONAL_ZOOM), 250);
      return;
    }

    const computed = scoreCache[selectedName];
    const target = computed
      ? { lat: computed.university.lat, lng: computed.university.lon }
      : (() => {
          const u = UNIVERSITIES.find((u) => u.name === selectedName);
          return u ? { lat: u.lat, lng: u.lon } : null;
        })();

    if (target) {
      map.panTo(target);
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
        title={selectedName ? "Re-center on campus" : "Re-center national view"}
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
  selectedName: string | null;
  scoreCache: Record<string, HousingPressureScore>;
  activeHexData: HexGeoJSON | null;
  onPinClick: (name: string) => void;
}

export function MapView({ selectedName, scoreCache, activeHexData, onPinClick }: MapViewProps) {
  const [hoveredName, setHoveredName] = useState<string | null>(null);

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
        <CameraController selectedName={selectedName} scoreCache={scoreCache} />
        <RecenterButton selectedName={selectedName} scoreCache={scoreCache} />

        {/* H3 hex choropleth for the selected university (persists until recomputed) */}
        {activeHexData && <HexChoropleth hexData={activeHexData} />}

        {/* University pins */}
        {UNIVERSITIES.map((uni, i) => {
          const computed = scoreCache[uni.name];
          const isSelected = selectedName === uni.name;
          const isHovered = hoveredName === uni.name;

          // Color priority: computed score > selected (blue) > neutral
          const pinBg = computed
            ? SCORE_COLOR(computed.score)
            : isSelected
            ? "#3b82f6"
            : "#52525b";
          const pinBorder = isSelected ? "#18181b" : computed ? "#18181b" : "#3f3f46";

          return (
            <AdvancedMarker
              key={uni.name}
              position={{ lat: uni.lat, lng: uni.lon }}
              onClick={() => onPinClick(uni.name)}
              onMouseEnter={() => setHoveredName(uni.name)}
              onMouseLeave={() => setHoveredName(null)}
              title={uni.name}
              zIndex={isSelected ? 10 : computed ? 4 : isHovered ? 5 : 1}
            >
              {/* Staggered entrance animation */}
              <div
                style={{
                  animationDelay: `${i * 30}ms`,
                  animation: "markerIn 0.4s cubic-bezier(0.34,1.56,0.64,1) forwards",
                  opacity: 0,
                }}
              >
                <Pin
                  background={pinBg}
                  borderColor={pinBorder}
                  glyphColor="#ffffff"
                  scale={isSelected ? 1.4 : isHovered ? 1.15 : 1.0}
                />
              </div>

              {/* Hover tooltip — always mounted, toggled via CSS to avoid DOM conflicts */}
              <div
                className="absolute bottom-full mb-2 left-1/2 -translate-x-1/2
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
                <p className="text-xs text-zinc-400 mt-0.5">
                  {uni.city}, {uni.state}
                </p>
                {computed ? (
                  <div className="flex items-center gap-1.5 mt-1.5">
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ background: SCORE_COLOR(computed.score) }}
                    />
                    <span
                      className="text-xs font-medium"
                      style={{ color: SCORE_COLOR(computed.score) }}
                    >
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

      {/* Map hint / legend */}
      <div className="absolute bottom-6 left-6 bg-zinc-950/80 backdrop-blur-sm border border-zinc-800 rounded-xl p-3 text-xs pointer-events-none">
        {activeHexData ? (
          <div className="flex gap-4">
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
        ) : (
          <p className="text-zinc-500">
            <span className="text-zinc-300 font-medium">{UNIVERSITIES.length} universities</span>
            {" "}· click any pin to explore
          </p>
        )}
      </div>
    </div>
  );
}
