import { useState } from "react";
import { Polygon, InfoWindow } from "@vis.gl/react-google-maps";
import type { HexGeoJSON, HexFeatureProperties } from "../lib/hexApi";

function scoreToColor(score: number): string {
  if (score >= 70) return "#ef4444";
  if (score >= 55) return "#f97316";
  if (score >= 40) return "#eab308";
  if (score >= 25) return "#84cc16";
  return "#22c55e";
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

export function HexChoropleth({ hexData }: { hexData: HexGeoJSON }) {
  const [selectedHex, setSelectedHex] = useState<HexFeatureProperties | null>(null);

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
          fillColor={scoreToColor(f.properties.pressure_score)}
          fillOpacity={0.42}
          onClick={() => setSelectedHex(f.properties)}
        />
      ))}

      {selectedHex && (
        <InfoWindow
          position={{ lat: selectedHex.center_lat, lng: selectedHex.center_lng }}
          onCloseClick={() => setSelectedHex(null)}
        >
          <div className="p-2 min-w-[160px] font-sans">
            <div className="flex items-center gap-1.5 mb-2">
              <div
                className="w-3 h-3 rounded-sm"
                style={{ background: scoreToColor(selectedHex.pressure_score) }}
              />
              <span className="text-sm font-bold text-zinc-900">
                {selectedHex.pressure_score.toFixed(1)} / 100
              </span>
            </div>
            <div className="space-y-1 text-xs text-zinc-600">
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
              <p className="capitalize font-medium pt-1" style={{ color: scoreToColor(selectedHex.pressure_score) }}>
                {selectedHex.label} pressure
              </p>
            </div>
          </div>
        </InfoWindow>
      )}
    </>
  );
}
