/**
 * CompareSetupPanel — shows the two selection slots & their status
 * while the user is picking universities in compare mode.
 */

import { GitCompareArrows, Loader2, CheckCircle2, MousePointerClick, Clock } from "lucide-react";
import type { HousingPressureScore } from "../../lib/api";

interface LogEntry {
  message: string;
  ts: Date;
}

type SlotStatus = "empty" | "selected" | "queued" | "loading" | "ready";

interface SlotProps {
  index: number;
  name: string | null;
  status: SlotStatus;
  score: HousingPressureScore | null;
}

function Slot({ index, name, status, score }: SlotProps) {
  return (
    <div className={`rounded-xl border p-4 transition-all ${
      status === "ready"
        ? "border-green-500/30 bg-green-500/5"
        : status === "loading"
        ? "border-blue-500/30 bg-blue-500/5"
        : status === "queued"
        ? "border-amber-500/30 bg-amber-500/5"
        : status === "selected"
        ? "border-zinc-600 bg-zinc-900"
        : "border-dashed border-zinc-700 bg-zinc-900/50"
    }`}>
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs font-bold text-zinc-500 uppercase">
          University {index === 0 ? "A" : "B"}
        </span>
        {status === "ready"   && <CheckCircle2 className="w-3.5 h-3.5 text-green-400" />}
        {status === "loading" && <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />}
        {status === "queued"  && <Clock className="w-3.5 h-3.5 text-amber-400" />}
      </div>

      {status === "empty" ? (
        <div className="flex items-center gap-2 text-zinc-600 mt-2">
          <MousePointerClick className="w-4 h-4" />
          <p className="text-sm">Click a pin on the map</p>
        </div>
      ) : (
        <div>
          <p className="text-sm font-semibold text-zinc-200 leading-tight">{name}</p>
          {status === "loading" && (
            <p className="text-xs text-blue-400 mt-1 animate-pulse">Generating report…</p>
          )}
          {status === "queued" && (
            <p className="text-xs text-amber-400 mt-1">Queued — will start shortly…</p>
          )}
          {status === "ready" && score && (
            <p className="text-xs text-green-400 mt-1">
              Score: {score.score.toFixed(0)}/100 ✓
            </p>
          )}
        </div>
      )}
    </div>
  );
}

interface CompareSetupPanelProps {
  compareNames: [string | null, string | null];
  scoreCache: Record<string, HousingPressureScore>;
  loadingName: string | null;
  queuedNames: string[];
  activeLogs: LogEntry[];
}

export function CompareSetupPanel({
  compareNames,
  scoreCache,
  loadingName,
  queuedNames,
  activeLogs,
}: CompareSetupPanelProps) {
  const getStatus = (name: string | null): SlotStatus => {
    if (!name) return "empty";
    if (scoreCache[name]) return "ready";
    if (loadingName === name) return "loading";
    if (queuedNames.includes(name)) return "queued";
    return "selected";
  };

  const statusA = getStatus(compareNames[0]);
  const statusB = getStatus(compareNames[1]);
  const isGenerating = statusA === "loading" || statusB === "loading"
    || statusA === "queued" || statusB === "queued";
  const oneReady = (statusA === "ready") !== (statusB === "ready"); // XOR

  const subtitle = isGenerating
    ? "Generating reports, this may take a moment…"
    : oneReady
    ? "Now select a second university"
    : "Click two university pins on the map to compare their housing markets side-by-side.";

  const recentLogs = activeLogs.slice(-4);

  return (
    <div className="flex flex-col items-center justify-center h-full p-8">
      <div className={`w-14 h-14 rounded-2xl border flex items-center justify-center mb-6 transition-colors ${
        isGenerating
          ? "bg-blue-500/10 border-blue-500/20"
          : "bg-blue-500/10 border-blue-500/20"
      }`}>
        {isGenerating
          ? <Loader2 className="w-7 h-7 text-blue-400 animate-spin" />
          : <GitCompareArrows className="w-7 h-7 text-blue-400" />
        }
      </div>

      <h2 className="text-lg font-bold text-zinc-200 mb-1">Compare Mode</h2>
      <p className="text-sm text-zinc-500 mb-8 text-center max-w-xs transition-all">
        {subtitle}
      </p>

      <div className="w-full max-w-xs space-y-3">
        <Slot
          index={0}
          name={compareNames[0]}
          status={statusA}
          score={compareNames[0] ? scoreCache[compareNames[0]] ?? null : null}
        />

        {/* Connector */}
        <div className="flex justify-center">
          <div className="w-px h-4 bg-zinc-700" />
        </div>

        <Slot
          index={1}
          name={compareNames[1]}
          status={statusB}
          score={compareNames[1] ? scoreCache[compareNames[1]] ?? null : null}
        />

        {/* Live log tail — only visible while a report is running */}
        {recentLogs.length > 0 && (
          <div className="mt-4 bg-zinc-950/60 rounded-lg px-3 py-2 font-mono text-[10px] space-y-0.5 max-h-[72px] overflow-y-auto">
            {recentLogs.map((log, i) => (
              <div key={i} className="text-zinc-500 truncate leading-relaxed">
                <span className="text-zinc-700 mr-1.5">
                  {log.ts.toLocaleTimeString("en", {
                    hour12: false,
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </span>
                › {log.message}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
