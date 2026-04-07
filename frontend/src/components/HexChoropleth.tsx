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
                {selectedHex.distance_km.toFixed(2)} km from campus
              </p>
              <p>
                <span className="font-medium text-zinc-800">Permit density:</span>{" "}
                {selectedHex.permit_density.toFixed(2)} / km²
              </p>
              <p>
                <span className="font-medium text-zinc-800">Unit density:</span>{" "}
                {selectedHex.unit_density.toFixed(1)} / km²
              </p>
              <p className="capitalize font-medium" style={{ color: scoreToColor(selectedHex.pressure_score) }}>
                {selectedHex.label} pressure
              </p>
            </div>
          </div>
        </InfoWindow>
      )}
    </>
  );
}
