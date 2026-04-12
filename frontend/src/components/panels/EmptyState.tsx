import { MapPin } from "lucide-react";
import { UNIVERSITIES } from "../../lib/universityList";
import type { UniversitySuggestion } from "../../lib/universityList";
import LocationButton from "../LocationButton";

export function EmptyState({
  onSelectNearest,
  extraUniversities = [],
}: {
  onSelectNearest?: (
    name: string,
    coords: { lat: number; lng: number },
  ) => void;
  extraUniversities?: UniversitySuggestion[];
}) {
  const staticNames = new Set(UNIVERSITIES.map((u) => u.name));
  const totalCount =
    UNIVERSITIES.length +
    extraUniversities.filter((e) => !staticNames.has(e.name)).length;

  return (
    <div
      className="flex-1 flex flex-col items-center justify-center p-8 text-center"
      style={{ background: "var(--bg)" }}
    >
      {/* Icon */}
      <div
        className="w-12 h-12 rounded-xl flex items-center justify-center mb-6"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border)",
        }}
      >
        <MapPin className="w-5 h-5" style={{ color: "var(--text-3)" }} />
      </div>

      {/* Heading */}
      <h2
        className="text-base font-semibold mb-2"
        style={{
          fontFamily: "'Inter Tight', sans-serif",
          letterSpacing: "-0.025em",
          color: "var(--text)",
        }}
      >
        No market selected
      </h2>

      {/* Subtext */}
      <p
        className="text-sm leading-relaxed max-w-[200px] mb-6"
        style={{ color: "var(--text-2)" }}
      >
        Search for a university or click a map pin to begin analysis.
      </p>

      {/* Location CTA — QuantumLab primary button style */}
      <LocationButton
        onSelectNearest={onSelectNearest}
        extraUniversities={extraUniversities}
      />

      {/* Count badge */}
      <div
        className="mt-8 inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px]"
        style={{ border: "1px solid var(--border)", color: "var(--text-3)" }}
      >
        <span className="font-semibold" style={{ color: "var(--text-2)" }}>
          {totalCount}
        </span>{" "}
        universities indexed
      </div>
    </div>
  );
}
