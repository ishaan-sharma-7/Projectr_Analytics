import { UNIVERSITIES } from "../../lib/universityList";
import type { UniversitySuggestion } from "../../lib/universityList";
import LocationButton from "../LocationButton";

export function EmptyState({
  onSelectNearest,
  extraUniversities = [],
}: {
  onSelectNearest?: (name: string, coords: { lat: number; lng: number }) => void;
  extraUniversities?: UniversitySuggestion[];
}) {
  const staticNames = new Set(UNIVERSITIES.map((u) => u.name));
  const totalCount = UNIVERSITIES.length + extraUniversities.filter((e) => !staticNames.has(e.name)).length;
  return (
    <div
      className="flex-1 flex flex-col justify-between p-8"
      style={{ borderLeft: "1px solid rgba(240,240,240,0.08)" }}
    >
      {/* Top — editorial large title */}
      <div className="pt-2">
        <p
          className="text-[10px] font-semibold tracking-[0.15em] uppercase mb-5"
          style={{ color: "rgba(240,240,240,0.3)" }}
        >
          Housing Market Intel
        </p>

        <h2
          className="font-extrabold leading-[0.88] tracking-[-0.04em]"
          style={{ fontSize: "clamp(2.8rem,4.5vw,4.2rem)" }}
        >
          NO
        </h2>
        <div className="my-3 h-px" style={{ background: "rgba(240,240,240,0.08)" }} />
        <h2
          className="font-extrabold leading-[0.88] tracking-[-0.04em]"
          style={{
            fontSize: "clamp(2.8rem,4.5vw,4.2rem)",
            color: "transparent",
            WebkitTextStroke: "2px #f0f0f0",
          }}
        >
          MARKET
        </h2>
        <div className="my-3 h-px" style={{ background: "rgba(240,240,240,0.08)" }} />
        <h2
          className="font-extrabold leading-[0.88] tracking-[-0.04em]"
          style={{ fontSize: "clamp(2.8rem,4.5vw,4.2rem)" }}
        >
          SELECT
          <span style={{ color: "transparent", WebkitTextStroke: "2px #f0f0f0" }}>ED</span>
        </h2>
      </div>

      {/* Middle — description + CTA */}
      <div className="py-4">
        <p
          className="text-sm leading-relaxed font-light mb-6"
          style={{ color: "rgba(240,240,240,0.4)", maxWidth: "220px" }}
        >
          Click any pin on the map or search for a university to run a live housing market analysis.
        </p>
        <LocationButton
          onSelectNearest={onSelectNearest}
          extraUniversities={extraUniversities}
        />
      </div>

      {/* Bottom — dual stat row */}
      <div>
        <div className="h-px mb-5" style={{ background: "rgba(240,240,240,0.08)" }} />
        <div className="flex items-end justify-between">
          <div>
            <p
              className="text-[10px] tracking-[0.12em] uppercase font-semibold mb-1"
              style={{ color: "rgba(240,240,240,0.28)" }}
            >
              Universities
            </p>
            <p className="text-4xl font-extrabold tracking-[-0.05em] leading-none">
              {totalCount}
            </p>
          </div>
          <div className="text-right">
            <p
              className="text-[10px] tracking-[0.12em] uppercase font-semibold mb-1"
              style={{ color: "rgba(240,240,240,0.28)" }}
            >
              Coverage
            </p>
            <p
              className="text-4xl font-extrabold tracking-[-0.05em] leading-none"
              style={{ color: "transparent", WebkitTextStroke: "1.5px #f0f0f0" }}
            >
              US
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
