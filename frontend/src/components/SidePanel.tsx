import { EmptyState } from "./panels/EmptyState";
import { AgentLogPanel } from "./panels/AgentLogPanel";
import { ScorePanel } from "./panels/ScorePanel";
import type { HousingPressureScore } from "../lib/api";

interface LogEntry {
  message: string;
  ts: Date;
}

interface SidePanelProps {
  loading: boolean;
  error: string | null;
  activeScore: HousingPressureScore | null;
  agentLogs: LogEntry[];
  universityCount: number;
}

export function SidePanel({
  loading,
  error,
  activeScore,
  agentLogs,
  universityCount,
}: SidePanelProps) {
  return (
    <aside className="w-[440px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl overflow-hidden">

      {/* Agent log — shown while loading */}
      <div
        className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${
          loading ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        <AgentLogPanel logs={agentLogs} />
      </div>

      {/* Error state */}
      <div
        className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${
          !loading && error ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        <div className="p-6 m-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 mt-20">
          <h3 className="font-bold mb-1">Analysis Failed</h3>
          <p className="text-sm">{error}</p>
        </div>
      </div>

      {/* Empty state */}
      <div
        className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${
          !loading && !error && !activeScore ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        <EmptyState universityCount={universityCount} />
      </div>

      {/* Score panel — fades in when result arrives */}
      <div
        className={`absolute inset-0 overflow-y-auto transition-opacity duration-300 ${
          !loading && activeScore ? "opacity-100" : "opacity-0 pointer-events-none"
        }`}
      >
        {activeScore && <ScorePanel score={activeScore} />}
      </div>
    </aside>
  );
}
