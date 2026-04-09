import { useState } from "react";
import { ChevronDown, AlertCircle, CheckCircle2, ArrowRight } from "lucide-react";
import { EmptyState } from "./panels/EmptyState";
import { PreviewPanel } from "./panels/PreviewPanel";
import { ScorePanel } from "./panels/ScorePanel";
import type { HousingPressureScore } from "../lib/api";
import type { UniversitySuggestion } from "../lib/universityList";
import type { LogEntry, ReportJob } from "../App";

// ── QueueStatusBar ────────────────────────────────────────────────────────────

function QueueStatusBar({
  activeJob,
  queuedJobs,
}: {
  activeJob: ReportJob | null;
  queuedJobs: ReportJob[];
}) {
  const [expanded, setExpanded] = useState(false);
  const total = (activeJob ? 1 : 0) + queuedJobs.length;

  if (total === 0) return null;

  const recentLogs = activeJob?.logs.slice(-5) ?? [];

  return (
    <div className="border-b border-zinc-800 bg-zinc-900/70 backdrop-blur-sm flex-shrink-0">
      {/* Header row */}
      <button
        className="w-full flex items-center gap-2.5 px-4 py-2.5 hover:bg-zinc-800/40 transition-colors text-left"
        onClick={() => setExpanded(e => !e)}
      >
        {/* Spinner */}
        <div className="w-3.5 h-3.5 border-2 border-blue-500/30 border-t-blue-400 rounded-full animate-spin flex-shrink-0" />

        <div className="flex-1 min-w-0">
          {activeJob && (
            <p className="text-xs text-zinc-300 truncate">
              Generating:{" "}
              <span className="text-white font-medium">{activeJob.name}</span>
            </p>
          )}
          {queuedJobs.length > 0 && (
            <p className="text-[11px] text-zinc-500 leading-none mt-0.5">
              {queuedJobs.length} more queued
            </p>
          )}
        </div>

        <ChevronDown
          className={`w-3.5 h-3.5 text-zinc-500 flex-shrink-0 transition-transform duration-200 ${
            expanded ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Expanded: log tail + queued list */}
      {expanded && (
        <div className="px-4 pb-3 space-y-2.5">
          {recentLogs.length > 0 && (
            <div className="bg-zinc-950/60 rounded-lg px-3 py-2 font-mono text-[10px] space-y-0.5 max-h-[72px] overflow-y-auto">
              {recentLogs.map((log: LogEntry, i: number) => (
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

          {queuedJobs.length > 0 && (
            <div className="space-y-1">
              {queuedJobs.map(job => (
                <div
                  key={job.id}
                  className="flex items-center gap-2 text-[11px] text-zinc-500 py-0.5"
                >
                  <div className="w-1.5 h-1.5 rounded-full bg-zinc-600 flex-shrink-0" />
                  <span className="flex-1 truncate">{job.name}</span>
                  <span className="text-zinc-700 uppercase tracking-wide text-[9px] font-semibold">
                    queued
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── DoneBanner ────────────────────────────────────────────────────────────────

function DoneBanner({
  job,
  onView,
  onDismiss,
}: {
  job: ReportJob;
  onView: (job: ReportJob) => void;
  onDismiss: (id: string) => void;
}) {
  const displayName = job.resolvedName ?? job.name;
  return (
    <div className="mx-3 mt-3 flex items-center gap-2.5 bg-emerald-500/10 border border-emerald-500/20 rounded-xl px-3 py-2.5 flex-shrink-0">
      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-emerald-300 truncate">{displayName}</p>
        <p className="text-[11px] text-emerald-400/60 leading-none mt-0.5">Report ready</p>
      </div>
      <button
        onClick={() => onView(job)}
        className="flex items-center gap-1 text-[11px] text-emerald-300 hover:text-white font-medium transition-colors flex-shrink-0"
      >
        View <ArrowRight className="w-3 h-3" />
      </button>
      <button
        onClick={() => onDismiss(job.id)}
        className="text-[11px] text-zinc-600 hover:text-zinc-300 transition-colors flex-shrink-0"
      >
        ✕
      </button>
    </div>
  );
}

// ── ErrorBanner ───────────────────────────────────────────────────────────────

function ErrorBanner({
  job,
  onDismiss,
  onRetry,
}: {
  job: ReportJob;
  onDismiss: (id: string) => void;
  onRetry: (name: string) => void;
}) {
  return (
    <div className="mx-3 mt-3 flex items-start gap-2.5 bg-red-500/10 border border-red-500/20 rounded-xl px-3 py-2.5 flex-shrink-0">
      <AlertCircle className="w-3.5 h-3.5 text-red-400 flex-shrink-0 mt-0.5" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-red-300 truncate">{job.name}</p>
        <p className="text-[11px] text-red-400/70 truncate mt-0.5">
          {job.errorMsg ?? "Analysis failed"}
        </p>
      </div>
      <div className="flex gap-2 flex-shrink-0">
        <button
          onClick={() => onRetry(job.name)}
          className="text-[11px] text-red-300 hover:text-white transition-colors underline"
        >
          Retry
        </button>
        <button
          onClick={() => onDismiss(job.id)}
          className="text-[11px] text-zinc-600 hover:text-zinc-300 transition-colors"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

// ── SidePanel ─────────────────────────────────────────────────────────────────

interface SidePanelProps {
  selectedName: string | null;
  activeScore: HousingPressureScore | null;
  activeJob: ReportJob | null;
  queuedJobs: ReportJob[];
  doneJobs: ReportJob[];
  errorJobs: ReportJob[];
  onRecompute: () => void;
  onGenerateReport: (name: string) => void;
  onDismissJob: (id: string) => void;
  onViewReport: (job: ReportJob) => void;
  onSelectNearest?: (name: string, coords: { lat: number; lng: number }) => void;
  extraUniversities?: UniversitySuggestion[];
}

export function SidePanel({
  selectedName,
  activeScore,
  activeJob,
  queuedJobs,
  doneJobs,
  errorJobs,
  onRecompute,
  onGenerateReport,
  onDismissJob,
  onViewReport,
  onSelectNearest,
  extraUniversities,
}: SidePanelProps) {
  const showEmpty = !selectedName;
  const showPreview = !!selectedName && !activeScore;
  const showScore = !!activeScore;

  return (
    <aside className="w-[440px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl overflow-hidden">
      {/* Queue status bar — always on top, shows only when work is pending */}
      <QueueStatusBar activeJob={activeJob} queuedJobs={queuedJobs} />

      {/* Done banners */}
      {doneJobs.map(job => (
        <DoneBanner
          key={job.id}
          job={job}
          onView={onViewReport}
          onDismiss={onDismissJob}
        />
      ))}

      {/* Error banners */}
      {errorJobs.map(job => (
        <ErrorBanner
          key={job.id}
          job={job}
          onDismiss={onDismissJob}
          onRetry={onGenerateReport}
        />
      ))}

      {/* Content panels — always navigable */}
      <div className="flex-1 overflow-hidden relative">
        {/* Empty — nothing selected */}
        <div
          className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${
            showEmpty ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          <EmptyState
            onSelectNearest={onSelectNearest}
            extraUniversities={extraUniversities}
          />
        </div>

        {/* Preview — university selected but not yet computed */}
        <div
          className={`absolute inset-0 transition-opacity duration-300 ${
            showPreview ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          {selectedName && (
            <PreviewPanel name={selectedName} onGenerateReport={onGenerateReport} />
          )}
        </div>

        {/* Score — computed result */}
        <div
          className={`absolute inset-0 overflow-y-auto transition-opacity duration-300 ${
            showScore ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
        >
          {activeScore && <ScorePanel score={activeScore} onRecompute={onRecompute} />}
        </div>
      </div>
    </aside>
  );
}
