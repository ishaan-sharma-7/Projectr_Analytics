/**
 * ComparePanel — side-by-side comparison of two universities.
 */

import { useState, useRef, useEffect } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import { ScoreGauge } from "../ui/ScoreGauge";
import { generateCompareInsight } from "../../lib/compareInsight";
import type { HousingPressureScore } from "../../lib/api";
import {
  exportComparisonToPDF,
  exportComparisonToDocx,
} from "../../lib/exportReport";
import { resolveCompareLabels } from "../../lib/uniAbbrev";

function getLabel(score: number): "high" | "medium" | "low" {
  return score >= 70 ? "high" : score >= 40 ? "medium" : "low";
}

const LABEL_COLORS = {
  high: "text-emerald-400",
  medium: "text-amber-400",
  low: "text-red-400",
} as const;

const LABEL_TEXT = {
  high: "Strong Opportunity",
  medium: "Emerging Market",
  low: "Saturated",
} as const;

interface ComparePanelProps {
  scoreA: HousingPressureScore;
  scoreB: HousingPressureScore;
  onClear: () => void;
}

function StatCell({
  label,
  value,
  sub,
}: {
  label: string;
  value: string;
  sub?: string;
}) {
  return (
    <div
      className="p-3 rounded-lg"
      style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
    >
      <p className="text-[10px] font-medium uppercase tracking-wide mb-1" style={{ color: "var(--text-3)" }}>
        {label}
      </p>
      <p className="text-sm font-bold tabular-nums" style={{ color: "var(--text)" }}>
        {value}
      </p>
      {sub && (
        <p className="text-[10px] mt-0.5" style={{ color: "var(--text-3)" }}>
          {sub}
        </p>
      )}
    </div>
  );
}

function ComponentBar({
  label,
  valueA,
  valueB,
  color,
}: {
  label: string;
  valueA: number;
  valueB: number;
  color: string;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between text-xs font-medium">
        <span style={{ color: "var(--text-2)" }}>{label}</span>
        <div className="flex gap-3">
          <span className="tabular-nums" style={{ color: "var(--text)" }}>
            {valueA.toFixed(0)}
          </span>
          <span style={{ color: "var(--text-3)" }}>vs</span>
          <span className="tabular-nums" style={{ color: "var(--text-2)" }}>
            {valueB.toFixed(0)}
          </span>
        </div>
      </div>
      <div className="flex gap-1">
        <div
          className="flex-1 h-1.5 rounded-full overflow-hidden"
          style={{ background: "var(--bg)" }}
        >
          <div
            className={`h-full ${color} rounded-full transition-all duration-700`}
            style={{ width: `${valueA}%` }}
          />
        </div>
        <div
          className="flex-1 h-1.5 rounded-full overflow-hidden"
          style={{ background: "var(--bg)" }}
        >
          <div
            className={`h-full ${color} rounded-full transition-all duration-700 opacity-50`}
            style={{ width: `${valueB}%` }}
          />
        </div>
      </div>
    </div>
  );
}

function CompareExportButton({
  scoreA,
  scoreB,
}: {
  scoreA: HousingPressureScore;
  scoreB: HousingPressureScore;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState<"pdf" | "docx" | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  async function handle(format: "pdf" | "docx") {
    setOpen(false);
    setLoading(format);
    try {
      if (format === "pdf") await exportComparisonToPDF(scoreA, scoreB);
      else await exportComparisonToDocx(scoreA, scoreB);
    } finally {
      setLoading(null);
    }
  }

  const isLoading = loading !== null;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => !isLoading && setOpen((v) => !v)}
        disabled={isLoading}
        className="btn-ql btn-ql-secondary disabled:opacity-50"
      >
        {isLoading ? "Exporting..." : "Export"}
        <span className="btn-icon">
          {isLoading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <ChevronDown
              className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
            />
          )}
        </span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 w-44 rounded-xl shadow-2xl z-50 overflow-hidden"
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
          }}
        >
          {[
            { key: "pdf" as const, label: "Download PDF", sub: "Side-by-side report" },
            { key: "docx" as const, label: "Download Word", sub: ".docx, fully editable" },
          ].map(({ key, label, sub }) => (
            <button
              key={key}
              onClick={() => handle(key)}
              className="w-full text-left px-4 py-3 transition-colors"
              style={{ borderBottom: "1px solid var(--border)" }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "rgba(255,255,255,0.04)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              <p className="text-xs font-medium" style={{ color: "var(--text)" }}>
                {label}
              </p>
              <p className="text-[10px] mt-0.5" style={{ color: "var(--text-3)" }}>
                {sub}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ComparePanel({ scoreA, scoreB, onClear }: ComparePanelProps) {
  const labelA = getLabel(scoreA.score);
  const labelB = getLabel(scoreB.score);
  const insight = generateCompareInsight(scoreA, scoreB);
  const [abbrevA, abbrevB] = resolveCompareLabels(
    scoreA.university.name,
    scoreA.university.city,
    scoreB.university.name,
    scoreB.university.city,
  );

  const enrollA = scoreA.enrollment_trend.at(-1)?.total_enrollment;
  const enrollB = scoreB.enrollment_trend.at(-1)?.total_enrollment;
  const rentA = scoreA.rent_history.at(-1)?.median_rent;
  const rentB = scoreB.rent_history.at(-1)?.median_rent;
  const permitsA = scoreA.permit_history.reduce((s, p) => s + p.permits, 0);
  const permitsB = scoreB.permit_history.reduce((s, p) => s + p.permits, 0);

  return (
    <div className="flex-1 min-h-0 overflow-y-auto p-5 space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p
          className="text-[10px] font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-3)" }}
        >
          Compare Universities
        </p>
        <div className="flex items-center gap-2">
          <CompareExportButton scoreA={scoreA} scoreB={scoreB} />
          <button
            onClick={onClear}
            className="btn-ql btn-ql-secondary"
            style={{ fontSize: "12px" }}
          >
            Clear
            <span className="btn-icon">
              <span style={{ fontSize: "10px", lineHeight: 1 }}>✕</span>
            </span>
          </button>
        </div>
      </div>

      {/* University names side-by-side */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { score: scoreA, label: labelA },
          { score: scoreB, label: labelB },
        ].map(({ score, label }, i) => (
          <div
            key={i}
            className="rounded-xl p-4"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
          >
            <p className="text-[10px] mb-1" style={{ color: "var(--text-3)" }}>
              {score.university.city}, {score.university.state}
            </p>
            <h4
              className="text-sm font-bold leading-tight"
              style={{ fontFamily: "'Inter Tight', sans-serif", color: "var(--text)", letterSpacing: "-0.02em" }}
            >
              {score.university.name}
            </h4>
            <div className="flex items-center gap-1.5 mt-2">
              <span className={`text-2xl font-black tabular-nums ${LABEL_COLORS[label]}`}>
                {score.score.toFixed(0)}
              </span>
              <span className={`text-xs font-medium ${LABEL_COLORS[label]}`}>
                {LABEL_TEXT[label]}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Score gauges */}
      <div className="grid grid-cols-2 gap-3">
        {[scoreA, scoreB].map((s, i) => (
          <div
            key={i}
            className="flex justify-center rounded-xl p-4"
            style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
          >
            <ScoreGauge score={s.score} label={getLabel(s.score)} />
          </div>
        ))}
      </div>

      {/* Insight */}
      <div
        className="rounded-xl p-4"
        style={{ background: "var(--surface-2)", border: "1px solid var(--border)" }}
      >
        <div className="flex items-center gap-2 mb-2">
          <div
            className="w-4 h-4 rounded-full flex items-center justify-center"
            style={{ background: "rgba(255,255,255,0.06)" }}
          >
            <div className="w-1.5 h-1.5 rounded-full" style={{ background: "var(--text-3)" }} />
          </div>
          <span
            className="text-[10px] font-semibold uppercase tracking-widest"
            style={{ color: "var(--text-3)" }}
          >
            Market Insight
          </span>
        </div>
        <p className="text-sm leading-relaxed" style={{ color: "var(--text-2)" }}>
          {insight}
        </p>
      </div>

      {/* Component bars */}
      <div
        className="rounded-xl p-4 space-y-4"
        style={{ background: "var(--surface)", border: "1px solid var(--border)" }}
      >
        <p
          className="text-[10px] font-semibold uppercase tracking-widest"
          style={{ color: "var(--text-3)" }}
        >
          Score Components
        </p>
        <ComponentBar
          label="Enrollment Growth"
          valueA={scoreA.components.enrollment_pressure}
          valueB={scoreB.components.enrollment_pressure}
          color="bg-blue-500"
        />
        <ComponentBar
          label="Permit Gap"
          valueA={scoreA.components.permit_gap}
          valueB={scoreB.components.permit_gap}
          color="bg-purple-500"
        />
        <ComponentBar
          label="Rent Inflation"
          valueA={scoreA.components.rent_pressure}
          valueB={scoreB.components.rent_pressure}
          color="bg-rose-500"
        />
      </div>

      {/* Key stats */}
      <div>
        <p
          className="text-[10px] font-semibold uppercase tracking-widest mb-3"
          style={{ color: "var(--text-3)" }}
        >
          Key Metrics
        </p>
        <div className="grid grid-cols-2 gap-2">
          <StatCell label={`Enrollment — ${abbrevA}`} value={enrollA?.toLocaleString() ?? "N/A"} />
          <StatCell label={`Enrollment — ${abbrevB}`} value={enrollB?.toLocaleString() ?? "N/A"} />
          <StatCell label={`Rent — ${abbrevA}`} value={rentA ? `$${rentA.toLocaleString()}` : "N/A"} />
          <StatCell label={`Rent — ${abbrevB}`} value={rentB ? `$${rentB.toLocaleString()}` : "N/A"} />
          <StatCell label={`Permits — ${abbrevA}`} value={permitsA > 0 ? permitsA.toLocaleString() : "N/A"} sub="5yr total" />
          <StatCell label={`Permits — ${abbrevB}`} value={permitsB > 0 ? permitsB.toLocaleString() : "N/A"} sub="5yr total" />
          <StatCell label={`Housing — ${abbrevA}`} value={scoreA.nearby_housing_units > 0 ? scoreA.nearby_housing_units.toLocaleString() : "N/A"} sub="county total" />
          <StatCell label={`Housing — ${abbrevB}`} value={scoreB.nearby_housing_units > 0 ? scoreB.nearby_housing_units.toLocaleString() : "N/A"} sub="county total" />
        </div>
      </div>
    </div>
  );
}
