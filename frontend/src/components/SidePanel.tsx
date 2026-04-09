import { useState } from "react";
import { EmptyState } from "./panels/EmptyState";
import { AgentLogPanel } from "./panels/AgentLogPanel";
import { PreviewPanel } from "./panels/PreviewPanel";
import { ScorePanel } from "./panels/ScorePanel";
import { ChatbotWidget } from "./ui/ChatbotWidget";
import type { HousingPressureScore } from "../lib/api";
import type { UniversitySuggestion } from "../lib/universityList";

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
  onSelectNearest?: (name: string, coords: { lat: number; lng: number }) => void;
  extraUniversities?: UniversitySuggestion[];
}

export function SidePanel({
  loading,
  error,
  selectedName,
  activeScore,
  agentLogs,
  onRecompute,
  onGenerateReport,
  onSelectNearest,
  extraUniversities,
}: SidePanelProps) {
  const [activeTab, setActiveTab] = useState<"data" | "chat">("data");

  const showEmpty = !loading && !error && !selectedName;
  const showLog = loading;
  const showError = !loading && !!error;
  const showPreview = !loading && !error && !!selectedName && !activeScore;
  const showScore = !loading && !error && !!activeScore;

  return (
    <aside className="w-[440px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl overflow-hidden">
      
      {/* Tab Header */}
      {selectedName && (
        <div className="flex bg-zinc-900 border-b border-zinc-800 p-2 gap-2 z-30 shrink-0">
          <button 
            onClick={() => setActiveTab("data")}
            className={`flex-1 py-1.5 px-3 rounded-lg text-sm font-medium transition-colors ${activeTab === "data" ? "bg-zinc-700 text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"}`}
          >
            Data Report
          </button>
          <button 
            onClick={() => setActiveTab("chat")}
            className={`flex-1 flex justify-center items-center gap-2 py-1.5 px-3 rounded-lg text-sm font-medium transition-colors ${activeTab === "chat" ? "bg-blue-600 text-white shadow-sm" : "text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/50"}`}
          >
            AI Assistant
          </button>
        </div>
      )}

      <div className="flex-1 relative overflow-hidden flex flex-col">
        {/* Empty — nothing selected */}
        <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${(activeTab === "data" || !selectedName) && showEmpty ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
          <EmptyState
            onSelectNearest={onSelectNearest}
            extraUniversities={extraUniversities}
          />
        </div>

        {/* Agent log — computation in progress */}
        <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${(activeTab === "data" || !selectedName) && showLog ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
          <AgentLogPanel logs={agentLogs} />
        </div>

        {/* Error */}
        <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${(activeTab === "data" || !selectedName) && showError ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
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
        <div className={`absolute inset-0 transition-opacity duration-300 ${(activeTab === "data" || !selectedName) && showPreview ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
          {selectedName && (
            <PreviewPanel name={selectedName} onGenerateReport={onGenerateReport} />
          )}
        </div>

        {/* Score — computed result */}
        <div className={`absolute inset-0 overflow-y-auto transition-opacity duration-300 ${(activeTab === "data" || !selectedName) && showScore ? "opacity-100" : "opacity-0 pointer-events-none"}`}>
          {activeScore && <ScorePanel score={activeScore} onRecompute={onRecompute} />}
        </div>

        {/* Chatbot Panel - rendered always, but visibility depends on tab */}
        <div className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${activeTab === "chat" && !!selectedName ? "opacity-100 z-10" : "opacity-0 pointer-events-none"}`}>
          <ChatbotWidget selectedName={selectedName} activeScore={activeScore} />
        </div>
      </div>
    </aside>
  );
}
