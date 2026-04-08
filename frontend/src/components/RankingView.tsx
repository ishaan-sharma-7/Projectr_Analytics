/**
 * RankingView — leaderboard of universities ranked by Housing Pressure Score.
 *
 * Full sortable table with state + score filters.
 * Click any row → uses existing handleSelectUniversity to navigate.
 */

import { useState, useMemo } from "react";
import { TrendingUp, ChevronDown } from "lucide-react";
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
    <div className="flex-1 overflow-y-auto bg-zinc-950">
      <div className="max-w-5xl mx-auto px-6 py-8">

        {/* Filters */}
        <div className="flex items-center gap-3 mb-5">
          <div className="flex items-center gap-2 mr-auto">
            <TrendingUp className="w-4 h-4 text-zinc-500" />
            <h3 className="text-sm font-semibold text-zinc-300">
              Market Rankings
              <span className="text-zinc-600 font-normal ml-2">
                {filtered.length} of {sorted.length}
              </span>
            </h3>
          </div>

          {/* State filter */}
          <div className="relative">
            <select
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="appearance-none bg-zinc-900 border border-zinc-700 rounded-lg pl-3 pr-8 py-1.5
                         text-xs font-medium text-zinc-300 outline-none focus:border-blue-500 transition-colors cursor-pointer"
            >
              <option value="">All States</option>
              {states.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <ChevronDown className="absolute right-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500 pointer-events-none" />
          </div>

          {/* Score filter buttons */}
          <div className="flex rounded-lg border border-zinc-800 overflow-hidden">
            {([
              ["all", "All"],
              ["high", "70+"],
              ["medium", "40–69"],
              ["low", "<40"],
            ] as [ScoreFilter, string][]).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setScoreFilter(key)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  scoreFilter === key
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-900 text-zinc-400 hover:text-zinc-200"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Leaderboard Table */}
        <div className="bg-zinc-900/50 border border-zinc-800 rounded-xl overflow-hidden">
          {/* Header */}
          <div className="grid grid-cols-[48px_1fr_140px_100px_100px] gap-2 px-4 py-3 border-b border-zinc-800 text-xs font-semibold text-zinc-500 uppercase tracking-wider">
            <span>#</span>
            <span>University</span>
            <span>Location</span>
            <span className="text-right">Score</span>
            <span className="text-right">Status</span>
          </div>

          {/* Rows */}
          {filtered.length === 0 ? (
            <div className="px-4 py-10 text-center text-sm text-zinc-600">
              No universities match the current filters.
            </div>
          ) : (
            filtered.map((uni) => {
              const rank = sorted.findIndex((u) => u.unitid === uni.unitid) + 1;

              return (
                <button
                  key={uni.unitid}
                  onClick={() => handleClick(uni.name)}
                  className="w-full grid grid-cols-[48px_1fr_140px_100px_100px] gap-2 px-4 py-3 items-center
                             border-b border-zinc-800/50 last:border-b-0
                             hover:bg-zinc-800/50 transition-colors text-left group"
                >
                  <span className={`text-sm font-bold tabular-nums ${rank <= 3 ? "text-amber-400" : "text-zinc-600"}`}>
                    {rank}
                  </span>

                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-zinc-200 truncate group-hover:text-white transition-colors">
                      {uni.name}
                    </p>
                  </div>

                  <p className="text-xs text-zinc-500 truncate">
                    {uni.city}, {uni.state}
                  </p>

                  <div className="flex items-center justify-end gap-2">
                    <div
                      className="w-2 h-2 rounded-full"
                      style={{ background: SCORE_COLOR(uni.score) }}
                    />
                    <span
                      className="text-sm font-bold tabular-nums"
                      style={{ color: SCORE_COLOR(uni.score) }}
                    >
                      {uni.score.toFixed(1)}
                    </span>
                  </div>

                  <div className="flex justify-end">
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${LABEL_CLASS(uni.score)}`}>
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
