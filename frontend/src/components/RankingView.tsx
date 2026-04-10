/**
 * RankingView — leaderboard of universities ranked by Housing Pressure Score.
 */

import { useState, useMemo } from "react";
import { TrendingUp, ChevronDown, ArrowLeft, ArrowRight } from "lucide-react";
import type { UniversityListItem } from "../lib/api";

const SCORE_COLOR = (score: number) =>
  score < 0 ? "rgba(255,255,255,0.25)" : score >= 70 ? "#ef4444" : score >= 40 ? "#eab308" : "#22c55e";

const LABEL = (score: number) =>
  score < 0 ? "Not Scored" : score >= 70 ? "High Pressure" : score >= 40 ? "Emerging" : "Balanced";

type ScoreFilter = "all" | "high" | "medium" | "low" | "unscored";

interface RankingViewProps {
  universities: UniversityListItem[];
  onSelect: (name: string) => void;
  onExitRanking: () => void;
}

export function RankingView({
  universities,
  onSelect,
  onExitRanking,
}: RankingViewProps) {
  const [stateFilter, setStateFilter] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");

  const sorted = useMemo(
    () =>
      [...universities].sort((a, b) => {
        // Unscored (score < 0) sink to bottom, alphabetical among themselves
        if (a.score < 0 && b.score < 0) return a.name.localeCompare(b.name);
        if (a.score < 0) return 1;
        if (b.score < 0) return -1;
        return b.score - a.score;
      }),
    [universities],
  );

  const states = useMemo(
    () => [...new Set(sorted.map((u) => u.state))].sort(),
    [sorted],
  );

  const filtered = useMemo(() => {
    return sorted.filter((u) => {
      if (stateFilter && u.state !== stateFilter) return false;
      if (scoreFilter === "high" && u.score < 70) return false;
      if (scoreFilter === "medium" && (u.score < 40 || u.score >= 70))
        return false;
      if (scoreFilter === "low" && (u.score >= 40 || u.score < 0)) return false;
      if (scoreFilter === "unscored" && u.score >= 0) return false;
      return true;
    });
  }, [sorted, stateFilter, scoreFilter]);

  const handleClick = (name: string) => {
    onSelect(name);
    onExitRanking();
  };

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: "var(--bg)" }}>
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Back to Map */}
        <button
          onClick={onExitRanking}
          className="flex items-center gap-2 text-sm transition-colors mb-8"
          style={{ color: "var(--text-2)" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-2)")}
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Map
        </button>

        {/* Header */}
        <div className="mb-6">
          <h2
            className="text-xl font-semibold tracking-tight"
            style={{
              fontFamily: "'Inter Tight', sans-serif",
              color: "var(--text)",
            }}
          >
            Market Rankings
          </h2>
          <p className="text-sm mt-1" style={{ color: "var(--text-2)" }}>
            Universities ranked by Housing Pressure Score
          </p>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-3 mb-5 flex-wrap">
          <div className="flex items-center gap-2 mr-auto">
            <TrendingUp
              className="w-4 h-4"
              style={{ color: "var(--text-3)" }}
            />
            <span className="text-sm" style={{ color: "var(--text-2)" }}>
              {filtered.length} of {sorted.length} universities
            </span>
          </div>

          {/* State filter */}
          <div className="relative">
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="appearance-none pl-3 pr-8 py-1.5 text-xs font-medium outline-none cursor-pointer transition-all"
              style={{
                background: "var(--surface-2)",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: "8px",
                color: "var(--text-2)",
              }}
            >
              <option value="">All States</option>
              {states.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <ChevronDown
              className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 pointer-events-none"
              style={{ color: "var(--text-3)" }}
            />
          </div>

          {/* Score filter buttons */}
          <div
            className="flex rounded-lg overflow-hidden"
            style={{ border: "1px solid rgba(255,255,255,0.08)" }}
          >
            {(
              [
                ["all", "All"],
                ["high", "70+"],
                ["medium", "40–69"],
                ["low", "<40"],
                ["unscored", "—"],
              ] as [ScoreFilter, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setScoreFilter(key)}
                className="px-3 py-1.5 text-xs font-medium transition-all"
                style={
                  scoreFilter === key
                    ? { background: "#fff", color: "#0f0f0f" }
                    : {
                        background: "transparent",
                        color: "rgba(255,255,255,0.4)",
                      }
                }
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div className="card-quantum overflow-hidden">
          {/* Header */}
          <div
            className="grid grid-cols-[48px_1fr_140px_100px_100px] gap-2 px-4 py-3"
            style={{ borderBottom: "1px solid var(--border)" }}
          >
            {["#", "University", "Location", "Score", "Status"].map((h, i) => (
              <span
                key={h}
                className={`text-[10px] font-semibold uppercase tracking-widest ${i >= 3 ? "text-right" : ""}`}
                style={{ color: "var(--text-3)" }}
              >
                {h}
              </span>
            ))}
          </div>

          {/* Rows */}
          {filtered.length === 0 ? (
            <div
              className="px-4 py-12 text-center text-sm"
              style={{ color: "var(--text-3)" }}
            >
              No universities match the current filters.
            </div>
          ) : (
            filtered.map((uni) => {
              const isScored = uni.score >= 0;
              const rank = isScored
                ? sorted.filter((u) => u.score >= 0).findIndex((u) => u.unitid === uni.unitid) + 1
                : 0;

              return (
                <button
                  key={uni.unitid}
                  onClick={() => handleClick(uni.name)}
                  className="w-full grid grid-cols-[48px_1fr_140px_100px_100px] gap-2 px-4 py-3 items-center text-left group transition-colors"
                  style={{ borderBottom: "1px solid rgba(255,255,255,0.04)" }}
                  onMouseEnter={(e) =>
                    (e.currentTarget.style.background =
                      "rgba(255,255,255,0.03)")
                  }
                  onMouseLeave={(e) =>
                    (e.currentTarget.style.background = "transparent")
                  }
                >
                  <span
                    className="text-sm font-semibold tabular-nums"
                    style={{ color: isScored && rank <= 3 ? "#f59e0b" : "var(--text-3)" }}
                  >
                    {isScored ? rank : "—"}
                  </span>

                  <div className="min-w-0 flex items-center gap-2">
                    <p
                      className="text-sm font-medium truncate transition-colors"
                      style={{ color: isScored ? "var(--text-2)" : "var(--text-3)" }}
                    >
                      {uni.name}
                    </p>
                    <ArrowRight
                      className="w-3 h-3 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                      style={{ color: "var(--text-3)" }}
                    />
                  </div>

                  <p
                    className="text-xs truncate"
                    style={{ color: "var(--text-3)" }}
                  >
                    {uni.city}, {uni.state}
                  </p>

                  <div className="flex items-center justify-end gap-2">
                    {isScored ? (
                      <>
                        <div
                          className="w-1.5 h-1.5 rounded-full"
                          style={{ background: SCORE_COLOR(uni.score) }}
                        />
                        <span
                          className="text-sm font-semibold tabular-nums"
                          style={{ color: SCORE_COLOR(uni.score) }}
                        >
                          {uni.score.toFixed(1)}
                        </span>
                      </>
                    ) : (
                      <span className="text-sm" style={{ color: "var(--text-3)" }}>—</span>
                    )}
                  </div>

                  <div className="flex justify-end">
                    <span
                      className="text-[10px] font-medium px-2 py-0.5 rounded-full"
                      style={{
                        border: `1px solid ${SCORE_COLOR(uni.score)}40`,
                        color: SCORE_COLOR(uni.score),
                        background: `${SCORE_COLOR(uni.score)}10`,
                      }}
                    >
                      {LABEL(uni.score)}
                    </span>
                  </div>
                </button>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
}
