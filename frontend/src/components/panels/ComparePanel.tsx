/**
 * ComparePanel — side-by-side comparison of two universities.
 *
 * Reuses existing ScoreGauge and types. Shows both scores, components,
 * key stats, and a logic-based comparison insight.
 */

import { ScoreGauge } from "../ui/ScoreGauge";
import { generateCompareInsight } from "../../lib/compareInsight";
import type { HousingPressureScore } from "../../lib/api";

function getLabel(score: number): "high" | "medium" | "low" {
  return score >= 70 ? "high" : score >= 40 ? "medium" : "low";
}

const LABEL_COLORS = {
  high: "text-red-400",
  medium: "text-yellow-400",
  low: "text-green-400",
} as const;

const LABEL_TEXT = {
  high: "High Pressure",
  medium: "Emerging",
  low: "Balanced",
} as const;

interface ComparePanelProps {
  scoreA: HousingPressureScore;
  scoreB: HousingPressureScore;
  onClear: () => void;
}

function StatCell({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-zinc-900/50 p-3 rounded-lg border border-zinc-800/50">
      <p className="text-xs text-zinc-500 font-medium mb-1">{label}</p>
      <p className="text-sm font-bold tabular-nums">{value}</p>
      {sub && <p className="text-xs text-zinc-600 mt-0.5">{sub}</p>}
    </div>
  );
}

function ComponentBar({ label, valueA, valueB, color }: { label: string; valueA: number; valueB: number; color: string }) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-medium">
        <span className="text-zinc-400">{label}</span>
        <div className="flex gap-3">
          <span className="text-zinc-300 tabular-nums">{valueA.toFixed(0)}</span>
          <span className="text-zinc-500">vs</span>
          <span className="text-zinc-300 tabular-nums">{valueB.toFixed(0)}</span>
        </div>
      </div>
      <div className="flex gap-1">
        <div className="flex-1 h-1.5 bg-zinc-950 rounded-full overflow-hidden">
          <div className={`h-full ${color} rounded-full transition-all duration-700`} style={{ width: `${valueA}%` }} />
        </div>
        <div className="flex-1 h-1.5 bg-zinc-950 rounded-full overflow-hidden">
          <div className={`h-full ${color} rounded-full transition-all duration-700 opacity-50`} style={{ width: `${valueB}%` }} />
        </div>
      </div>
    </div>
  );
}

export function ComparePanel({ scoreA, scoreB, onClear }: ComparePanelProps) {
  const labelA = getLabel(scoreA.score);
  const labelB = getLabel(scoreB.score);
  const insight = generateCompareInsight(scoreA, scoreB);

  const enrollA = scoreA.enrollment_trend.at(-1)?.total_enrollment;
  const enrollB = scoreB.enrollment_trend.at(-1)?.total_enrollment;

  const rentA = scoreA.rent_history.at(-1)?.median_rent;
  const rentB = scoreB.rent_history.at(-1)?.median_rent;

  const permitsA = scoreA.permit_history.reduce((s, p) => s + p.permits, 0);
  const permitsB = scoreB.permit_history.reduce((s, p) => s + p.permits, 0);

  return (
    <div className="p-5 space-y-5 overflow-y-auto h-full">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
          Compare Universities
        </h3>
        <button
          onClick={onClear}
          className="text-xs text-zinc-500 hover:text-zinc-300 transition-colors px-2 py-1 rounded-lg hover:bg-zinc-800"
        >
          Clear
        </button>
      </div>

      {/* University names side-by-side */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-zinc-900 rounded-xl p-4 border border-zinc-800">
          <p className="text-xs text-zinc-500 mb-1">{scoreA.university.city}, {scoreA.university.state}</p>
          <h4 className="text-sm font-bold leading-tight">{scoreA.university.name}</h4>
          <div className="flex items-center gap-1.5 mt-2">
            <span className={`text-2xl font-black tabular-nums ${LABEL_COLORS[labelA]}`}>
              {scoreA.score.toFixed(0)}
            </span>
            <span className={`text-xs font-medium ${LABEL_COLORS[labelA]}`}>
              {LABEL_TEXT[labelA]}
            </span>
          </div>
        </div>
        <div className="bg-zinc-900 rounded-xl p-4 border border-zinc-800">
          <p className="text-xs text-zinc-500 mb-1">{scoreB.university.city}, {scoreB.university.state}</p>
          <h4 className="text-sm font-bold leading-tight">{scoreB.university.name}</h4>
          <div className="flex items-center gap-1.5 mt-2">
            <span className={`text-2xl font-black tabular-nums ${LABEL_COLORS[labelB]}`}>
              {scoreB.score.toFixed(0)}
            </span>
            <span className={`text-xs font-medium ${LABEL_COLORS[labelB]}`}>
              {LABEL_TEXT[labelB]}
            </span>
          </div>
        </div>
      </div>

      {/* Score gauges side-by-side */}
      <div className="grid grid-cols-2 gap-3">
        <div className="flex justify-center bg-zinc-900/50 rounded-xl p-4 border border-zinc-800/50">
          <ScoreGauge score={scoreA.score} label={labelA} />
        </div>
        <div className="flex justify-center bg-zinc-900/50 rounded-xl p-4 border border-zinc-800/50">
          <ScoreGauge score={scoreB.score} label={labelB} />
        </div>
      </div>

      {/* Comparison insight */}
      <div className="bg-zinc-900/50 rounded-xl p-4 border border-zinc-800/50">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-4 h-4 rounded-full bg-blue-500/20 flex items-center justify-center">
            <div className="w-2 h-2 rounded-full bg-blue-400" />
          </div>
          <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
            Market Insight
          </span>
        </div>
        <p className="text-sm text-zinc-300 leading-relaxed">{insight}</p>
      </div>

      {/* Component bars — A full opacity, B half opacity */}
      <div className="bg-zinc-900 rounded-xl p-4 border border-zinc-800 space-y-4">
        <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
          Score Components
        </p>
        <ComponentBar label="Enrollment Growth" valueA={scoreA.components.enrollment_pressure} valueB={scoreB.components.enrollment_pressure} color="bg-blue-500" />
        <ComponentBar label="Permit Gap" valueA={scoreA.components.permit_gap} valueB={scoreB.components.permit_gap} color="bg-purple-500" />
        <ComponentBar label="Rent Inflation" valueA={scoreA.components.rent_pressure} valueB={scoreB.components.rent_pressure} color="bg-rose-500" />
      </div>

      {/* Key stats comparison */}
      <div>
        <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider mb-3">Key Metrics</p>
        <div className="grid grid-cols-2 gap-2">
          <StatCell label={`Enrollment — ${scoreA.university.name.split(" ")[0]}`} value={enrollA?.toLocaleString() ?? "N/A"} />
          <StatCell label={`Enrollment — ${scoreB.university.name.split(" ")[0]}`} value={enrollB?.toLocaleString() ?? "N/A"} />
          <StatCell label={`Rent — ${scoreA.university.name.split(" ")[0]}`} value={rentA ? `$${rentA.toLocaleString()}` : "N/A"} />
          <StatCell label={`Rent — ${scoreB.university.name.split(" ")[0]}`} value={rentB ? `$${rentB.toLocaleString()}` : "N/A"} />
          <StatCell label={`Permits — ${scoreA.university.name.split(" ")[0]}`} value={permitsA > 0 ? permitsA.toLocaleString() : "N/A"} sub="5yr total" />
          <StatCell label={`Permits — ${scoreB.university.name.split(" ")[0]}`} value={permitsB > 0 ? permitsB.toLocaleString() : "N/A"} sub="5yr total" />
          <StatCell label={`Housing — ${scoreA.university.name.split(" ")[0]}`} value={scoreA.nearby_housing_units > 0 ? scoreA.nearby_housing_units.toLocaleString() : "N/A"} sub="county total" />
          <StatCell label={`Housing — ${scoreB.university.name.split(" ")[0]}`} value={scoreB.nearby_housing_units > 0 ? scoreB.nearby_housing_units.toLocaleString() : "N/A"} sub="county total" />
        </div>
      </div>
    </div>
  );
}
