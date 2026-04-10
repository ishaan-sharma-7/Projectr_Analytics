/**
 * RankingView — leaderboard of universities ranked by Housing Pressure Score.
 *
 * Full sortable table with state + score filters.
 * Click any row → uses existing handleSelectUniversity to navigate.
 */

import { useState, useMemo } from "react";
import { TrendingUp, ChevronDown, ArrowLeft } from "lucide-react";
import type { UniversityListItem } from "../lib/api";

const SCORE_COLOR = (score: number) =>
  score >= 70 ? "#ef4444" : score >= 40 ? "#eab308" : "#22c55e";

const LABEL = (score: number) =>
  score >= 70 ? "High Pressure" : score >= 40 ? "Emerging" : "Balanced";

const LABEL_CLASS = (score: number) =>
  score >= 70
    ? "text-red-400 bg-red-500/10 border-red-500/20"
    : score >= 40
    ? "text-yellow-400 bg-yellow-500/10 border-yellow-500/20"
    : "text-green-400 bg-green-500/10 border-green-500/20";

type ScoreFilter = "all" | "high" | "medium" | "low";

interface RankingViewProps {
  universities: UniversityListItem[];
  onSelect: (name: string) => void;
  onExitRanking: () => void;
}

export function RankingView({ universities, onSelect, onExitRanking }: RankingViewProps) {
  const [stateFilter, setStateFilter] = useState("");
  const [scoreFilter, setScoreFilter] = useState<ScoreFilter>("all");

  // Sort by score descending
  const sorted = useMemo(
    () => [...universities].sort((a, b) => b.score - a.score),
    [universities],
  );

  // Unique states for the dropdown
  const states = useMemo(
    () => [...new Set(sorted.map((u) => u.state))].sort(),
    [sorted],
  );

  // Apply filters
  const filtered = useMemo(() => {
    return sorted.filter((u) => {
      if (stateFilter && u.state !== stateFilter) return false;
      if (scoreFilter === "high" && u.score < 70) return false;
      if (scoreFilter === "medium" && (u.score < 40 || u.score >= 70)) return false;
      if (scoreFilter === "low" && u.score >= 40) return false;
      return true;
    });
  }, [sorted, stateFilter, scoreFilter]);

  const handleClick = (name: string) => {
    onSelect(name);
    onExitRanking();
  };

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: "#080808" }}>
      <div className="max-w-5xl mx-auto px-8 py-8">

        {/* Editorial page header */}
        <div className="mb-8" style={{ borderBottom: "1px solid rgba(240,240,240,0.08)", paddingBottom: "2rem" }}>
          <button
            onClick={onExitRanking}
            className="flex items-center gap-1.5 mb-6 transition-opacity hover:opacity-60"
            style={{ fontSize: "0.7rem", fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: "rgba(240,240,240,0.4)" }}
          >
            <ArrowLeft className="w-3 h-3" />
            Back to Map
          </button>

          <div className="flex items-end justify-between gap-4">
            <div>
              <p style={{ fontSize: "0.7rem", fontWeight: 600, letterSpacing: "0.15em", textTransform: "uppercase", color: "rgba(240,240,240,0.3)", marginBottom: "0.6rem" }}>
                Housing Market Intel
              </p>
              <h2 style={{ fontSize: "clamp(2.5rem,5vw,5rem)", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 0.9 }}>
                MARKET<br />
                <span style={{ color: "transparent", WebkitTextStroke: "2px #f0f0f0" }}>RANK</span>INGS
              </h2>
            </div>
            <div className="text-right pb-1">
              <p style={{ fontSize: "0.7rem", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(240,240,240,0.28)", marginBottom: "0.4rem" }}>
                Showing
              </p>
              <p style={{ fontSize: "2.5rem", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1 }}>
                {filtered.length}
                <span style={{ color: "transparent", WebkitTextStroke: "1.5px rgba(240,240,240,0.3)", fontSize: "1.5rem" }}>
                  /{sorted.length}
                </span>
              </p>
            </div>
          </div>
        </div>

        {/* Filters bar */}
        <div className="flex items-center gap-3 mb-6 flex-wrap">
          <div className="flex items-center gap-2 mr-auto">
            <TrendingUp className="w-3.5 h-3.5" style={{ color: "rgba(240,240,240,0.3)" }} />
            <span style={{ fontSize: "0.7rem", fontWeight: 600, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(240,240,240,0.4)" }}>
              Filter
            </span>
          </div>

          {/* State filter */}
          <div className="relative">
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="appearance-none pl-3 pr-8 py-1.5 outline-none cursor-pointer transition-colors"
              style={{
                background: "rgba(240,240,240,0.04)",
                border: "1px solid rgba(240,240,240,0.1)",
                borderRadius: "100px",
                fontSize: "0.7rem",
                fontWeight: 600,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "#f0f0f0",
              }}
            >
              <option value="">All States</option>
              {states.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3 h-3 pointer-events-none" style={{ color: "rgba(240,240,240,0.4)" }} />
          </div>

          {/* Score filter pills */}
          <div className="flex gap-1">
            {([
              ["all", "All"],
              ["high", "70+"],
              ["medium", "40–69"],
              ["low", "<40"],
            ] as [ScoreFilter, string][]).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setScoreFilter(key)}
                className="px-3 py-1.5 transition-all"
                style={{
                  borderRadius: "100px",
                  fontSize: "0.68rem",
                  fontWeight: 600,
                  letterSpacing: "0.08em",
                  textTransform: "uppercase",
                  background: scoreFilter === key ? "#2563eb" : "rgba(240,240,240,0.04)",
                  color: scoreFilter === key ? "#ffffff" : "rgba(240,240,240,0.45)",
                  border: scoreFilter === key ? "1px solid #3b82f6" : "1px solid rgba(240,240,240,0.1)",
                }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div style={{ border: "1px solid rgba(240,240,240,0.08)", borderRadius: "8px", overflow: "hidden" }}>
          {/* Table header */}
          <div
            className="grid grid-cols-[48px_1fr_140px_100px_100px] gap-2 px-5 py-3"
            style={{ borderBottom: "1px solid rgba(240,240,240,0.08)", fontSize: "0.65rem", fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(240,240,240,0.3)" }}
          >
            <span>#</span>
            <span>University</span>
            <span>Location</span>
            <span className="text-right">Score</span>
            <span className="text-right">Status</span>
          </div>

          {filtered.length === 0 ? (
            <div className="px-5 py-12 text-center" style={{ fontSize: "0.85rem", color: "rgba(240,240,240,0.3)" }}>
              No universities match the current filters.
            </div>
          ) : (
            filtered.map((uni) => {
              const rank = sorted.findIndex((u) => u.unitid === uni.unitid) + 1;

              return (
                <button
                  key={uni.unitid}
                  onClick={() => handleClick(uni.name)}
                  className="w-full grid grid-cols-[48px_1fr_140px_100px_100px] gap-2 px-5 py-3.5 items-center text-left group transition-colors"
                  style={{ borderBottom: "1px solid rgba(240,240,240,0.05)" }}
                  onMouseEnter={e => (e.currentTarget.style.background = "rgba(240,240,240,0.03)")}
                  onMouseLeave={e => (e.currentTarget.style.background = "transparent")}
                >
                  <span
                    style={{
                      fontSize: "0.9rem",
                      fontWeight: 800,
                      letterSpacing: "-0.02em",
                      color: rank <= 3 ? "#f59e0b" : "rgba(240,240,240,0.2)",
                    }}
                  >
                    {rank}
                  </span>

                  <div className="min-w-0">
                    <p className="text-sm font-semibold truncate" style={{ letterSpacing: "-0.01em" }}>
                      {uni.name}
                    </p>
                  </div>

                  <p className="text-xs truncate" style={{ color: "rgba(240,240,240,0.4)", letterSpacing: "0.04em", textTransform: "uppercase", fontSize: "0.65rem", fontWeight: 500 }}>
                    {uni.city}, {uni.state}
                  </p>

                  <div className="flex items-center justify-end gap-2">
                    <div className="w-1.5 h-1.5 rounded-full" style={{ background: SCORE_COLOR(uni.score) }} />
                    <span className="text-sm font-extrabold tabular-nums tracking-[-0.02em]" style={{ color: SCORE_COLOR(uni.score) }}>
                      {uni.score.toFixed(1)}
                    </span>
                  </div>

                  <div className="flex justify-end">
                    <span
                      className={`text-[10px] font-semibold px-2 py-0.5 rounded-full border tracking-[0.06em] uppercase ${LABEL_CLASS(uni.score)}`}
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
