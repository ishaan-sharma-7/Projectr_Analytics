import { EmptyState } from "./panels/EmptyState";
import { AgentLogPanel } from "./panels/AgentLogPanel";
import { PreviewPanel } from "./panels/PreviewPanel";
import { ScorePanel } from "./panels/ScorePanel";
import type { HousingPressureScore } from "../lib/api";

interface LogEntry {
  message: string;
  ts: Date;
}

interface SidePanelProps {
  loading: boolean;
  error: string | null;
  selectedName: string | null;
  activeScore: HousingPressureScore | null;
  agentLogs: LogEntry[];
  onRecompute: () => void;
  onGenerateReport: (name: string) => void;
}

export function SidePanel({
  loading,
  error,
  selectedName,
  activeScore,
  agentLogs,
  onRecompute,
  onGenerateReport,
}: SidePanelProps) {
  const showEmpty = !loading && !error && !selectedName;
  const showLog = loading;
  const showError = !loading && !!error;
  const showPreview = !loading && !error && !!selectedName && !activeScore;
  const showScore = !loading && !error && !!activeScore;

  return (
    <aside className="w-[440px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl overflow-hidden">

      {/* Empty — nothing selected */}
      <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${showEmpty ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
        <EmptyState />
      </div>

      {/* Agent log — computation in progress */}
      <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${showLog ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
        <AgentLogPanel logs={agentLogs} />
      </div>

      {/* Error */}
      <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${showError ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
        <div className="p-6 m-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 mt-20">
          <h3 className="font-bold mb-1">Analysis Failed</h3>
          <p className="text-sm">{error}</p>
          {selectedName && (
            <button
              onClick={() => onGenerateReport(selectedName)}
              className="mt-3 text-xs text-red-300 underline"
            >
              Try again
            </button>
          )}
        </div>
      </div>

      {/* Preview — university selected but not yet computed */}
      <div className={`absolute inset-0 transition-opacity duration-300 ${showPreview ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
        {selectedName && (
          <PreviewPanel name={selectedName} onGenerateReport={onGenerateReport} />
        )}
      </div>

      {/* Score — computed result (from cache, instant re-render) */}
      <div className={`absolute inset-0 overflow-y-auto transition-opacity duration-300 ${showScore ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
        {activeScore && <ScorePanel score={activeScore} onRecompute={onRecompute} />}
      </div>
    </aside>
  );
}
