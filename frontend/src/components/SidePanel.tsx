import { useState } from "react";
import {
  ChevronDown,
  AlertCircle,
  CheckCircle2,
  ArrowRight,
  ArrowLeft,
  MapPin,
  Download,
} from "lucide-react";
import { EmptyState } from "./panels/EmptyState";
import { PreviewPanel } from "./panels/PreviewPanel";
import { ScorePanel } from "./panels/ScorePanel";
import { AgentLogPanel } from "./panels/AgentLogPanel";
import { ChatbotWidget } from "./ui/ChatbotWidget";
import type { HousingPressureScore } from "../lib/api";
import type { HexFeatureProperties } from "../lib/hexApi";
import type { UniversitySuggestion } from "../lib/universityList";
import type { LogEntry, ReportJob } from "../App";

// ── QueueStatusBar ────────────────────────────────────────────────────────────

// Reusable small pulsing hex SVG — matches the map corner indicator
function HexPulseIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="-8 -8 16 16"
      className="animate-pulse flex-shrink-0"
      style={{ filter: "drop-shadow(0 0 3px rgba(59,130,246,0.6))" }}
    >
      <polygon
        points="6,3.5 0,7 -6,3.5 -6,-3.5 0,-7 6,-3.5"
        fill="rgba(59,130,246,0.35)"
        stroke="rgba(96,165,250,0.9)"
        strokeWidth="1.5"
      />
    </svg>
  );
}

// Standalone bar — shown when no report bar is open
function HexLoadingBar({ name }: { name: string }) {
  return (
    <div
      className="flex-shrink-0"
      style={{
        borderBottom: "1px solid var(--border)",
        background: "rgba(28,28,28,0.8)",
        backdropFilter: "blur(8px)",
      }}
    >
      <div className="flex items-center gap-2.5 px-4 py-2.5">
        <HexPulseIcon />
        <p
          className="text-xs flex-1 min-w-0 truncate"
          style={{ color: "var(--text-2)" }}
        >
          Hex grid loading:{" "}
          <span className="font-medium" style={{ color: "var(--text)" }}>
            {name}
          </span>
        </p>
      </div>
    </div>
  );
}

// Green done banner — matches report DoneBanner style
function HexDoneBar({ name }: { name: string }) {
  return (
    <div
      className="mx-3 mt-3 flex items-center gap-2.5 rounded-xl px-3 py-2.5 flex-shrink-0"
      style={{
        background: "rgba(16,185,129,0.08)",
        border: "1px solid rgba(16,185,129,0.2)",
      }}
    >
      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-emerald-300 truncate">{name}</p>
        <p className="text-[11px] text-emerald-400/60 leading-none mt-0.5">
          Hex grid generated
        </p>
      </div>
    </div>
  );
}

function QueueStatusBar({
  activeJob,
  queuedJobs,
  hexLoadingName,
}: {
  activeJob: ReportJob | null;
  queuedJobs: ReportJob[];
  hexLoadingName?: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const total = (activeJob ? 1 : 0) + queuedJobs.length;

  if (total === 0) return null;

  const recentLogs = activeJob?.logs.slice(-5) ?? [];

  return (
    <div
      className="flex-shrink-0"
      style={{
        borderBottom: "1px solid var(--border)",
        background: "rgba(28,28,28,0.8)",
        backdropFilter: "blur(8px)",
      }}
    >
      {/* Header row */}
      <button
        className="w-full flex items-center gap-2.5 px-4 py-2.5 transition-colors text-left"
        style={{ background: "transparent" }}
        onMouseEnter={(e) =>
          (e.currentTarget.style.background = "rgba(255,255,255,0.03)")
        }
        onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        onClick={() => setExpanded((e) => !e)}
      >
        {/* Spinner */}
        <div className="w-3.5 h-3.5 border-2 border-blue-500/30 border-t-blue-400 rounded-full animate-spin flex-shrink-0" />

        <div className="flex-1 min-w-0">
          {activeJob && (
            <p className="text-xs truncate" style={{ color: "var(--text-2)" }}>
              Generating:{" "}
              <span className="font-medium" style={{ color: "var(--text)" }}>
                {activeJob.name}
              </span>
            </p>
          )}
          {queuedJobs.length > 0 && (
            <p
              className="text-[11px] leading-none mt-0.5"
              style={{ color: "var(--text-3)" }}
            >
              {queuedJobs.length} more queued
            </p>
          )}
          {hexLoadingName && (
            <div className="flex items-center gap-1.5 mt-0.5">
              <HexPulseIcon />
              <p className="text-[11px] text-blue-400/80 truncate">
                Hex grid:{" "}
                <span className="text-blue-300">{hexLoadingName}</span>
              </p>
            </div>
          )}
        </div>

        <ChevronDown
          className={`w-3.5 h-3.5 flex-shrink-0 transition-transform duration-200 ${
            expanded ? "rotate-180" : ""
          }`}
          style={{ color: 'var(--text-3)' }}
        />
      </button>

      {/* Expanded: log tail + queued list */}
      {expanded && (
        <div className="px-4 pb-3 space-y-2.5">
          {recentLogs.length > 0 && (
            <div
              className="rounded-lg px-3 py-2 font-mono text-[10px] space-y-0.5 max-h-[72px] overflow-y-auto"
              style={{ background: "rgba(0,0,0,0.4)" }}
            >
              {recentLogs.map((log: LogEntry, i: number) => (
                <div
                  key={i}
                  className="truncate leading-relaxed"
                  style={{ color: "var(--text-3)" }}
                >
                  <span
                    className="mr-1.5"
                    style={{ color: "rgba(255,255,255,0.15)" }}
                  >
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
              {queuedJobs.map((job) => (
                <div
                  key={job.id}
                  className="flex items-center gap-2 text-[11px] py-0.5"
                  style={{ color: 'var(--text-3)' }}
                >
                  <div className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: 'var(--text-3)' }} />
                  <span className="flex-1 truncate">{job.name}</span>
                  <span className="uppercase tracking-wide text-[9px] font-semibold" style={{ color: 'rgba(255,255,255,0.15)' }}>
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
  onExport,
}: {
  job: ReportJob;
  onView: (job: ReportJob) => void;
  onDismiss: (id: string) => void;
  onExport?: (job: ReportJob) => void;
}) {
  const displayName = job.resolvedName ?? job.name;
  return (
    <div
      className="mx-3 mt-3 flex items-center gap-2.5 rounded-xl px-3 py-2.5 flex-shrink-0"
      style={{
        background: "rgba(16,185,129,0.08)",
        border: "1px solid rgba(16,185,129,0.2)",
      }}
    >
      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium text-emerald-300 truncate">
          {displayName}
        </p>
        <p className="text-[11px] text-emerald-400/60 leading-none mt-0.5">
          Report ready
        </p>
      </div>
      <button
        onClick={() => onView(job)}
        className="flex items-center gap-1 text-[11px] font-medium transition-colors flex-shrink-0"
        style={{ color: "var(--text-2)" }}
        onMouseEnter={(e) => (e.currentTarget.style.color = "var(--text)")}
        onMouseLeave={(e) => (e.currentTarget.style.color = "var(--text-2)")}
      >
        View <ArrowRight className="w-3 h-3" />
      </button>
      {onExport && (
        <button
          onClick={() => onExport(job)}
          title="Export PDF"
          className="text-emerald-400/60 hover:text-emerald-300 transition-colors flex-shrink-0"
        >
          <Download className="w-3.5 h-3.5" />
        </button>
      )}
      <button
        onClick={() => onDismiss(job.id)}
        className="text-[11px] transition-colors flex-shrink-0"
        style={{ color: 'var(--text-3)' }}
        onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-2)')}
        onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}
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
    <div
      className="mx-3 mt-3 flex items-start gap-2.5 rounded-xl px-3 py-2.5 flex-shrink-0"
      style={{
        background: "rgba(239,68,68,0.08)",
        border: "1px solid rgba(239,68,68,0.2)",
      }}
    >
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
          className="text-[11px] transition-colors"
          style={{ color: "rgba(248,113,113,0.8)" }}
          onMouseEnter={(e) => (e.currentTarget.style.color = "#f87171")}
          onMouseLeave={(e) => (e.currentTarget.style.color = "rgba(248,113,113,0.8)")}
        >
          Retry
        </button>
        <button
          onClick={() => onDismiss(job.id)}
          className="text-[11px] transition-colors"
        style={{ color: 'var(--text-3)' }}
        onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-2)')}
        onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-3)')}
        >
          ✕
        </button>
      </div>
    </div>
  );
}

// ── LandParcelDetailPanel ─────────────────────────────────────────────────────

type LandParcel = {
  address: string;
  lot_size_acres: number;
  land_value: number;
  market_value: number;
  owner_name: string;
  is_absentee: boolean;
  land_use: string;
  parcel_type: string;
};

function LandParcelDetailPanel({
  parcels,
  label,
  onDismiss,
}: {
  parcels: LandParcel[];
  label: string;
  onDismiss: () => void;
}) {
  const absenteeCount = parcels.filter((p) => p.is_absentee).length;
  const landValues = parcels
    .filter((p) => p.land_value > 0)
    .map((p) => p.land_value);
  const avgLandValue =
    landValues.length > 0
      ? landValues.reduce((a, b) => a + b, 0) / landValues.length
      : 0;
  const totalAcres = parcels.reduce((s, p) => s + (p.lot_size_acres || 0), 0);

  return (
    <div className="absolute inset-0 flex flex-col z-30 overflow-hidden" style={{ background: 'var(--surface)' }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3 flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
        <button
          onClick={onDismiss}
          className="flex items-center gap-1.5 transition-colors text-xs"
          style={{ color: 'var(--text-2)' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-2)')}
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold truncate" style={{ color: 'var(--text)' }}>
            Available Land Parcels
          </p>
          <p className="text-[11px]" style={{ color: 'var(--text-3)' }}>{label}</p>
        </div>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-3 flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
        {[
          ["Lots", parcels.length],
          [
            "Avg value",
            avgLandValue > 0 ? `$${(avgLandValue / 1000).toFixed(0)}k` : "—",
          ],
          ["Total acres", totalAcres > 0 ? totalAcres.toFixed(1) : "—"],
        ].map(([k, v]) => (
          <div key={String(k)} className="px-3 py-2 text-center">
            <p className="text-sm font-bold" style={{ color: 'var(--text)' }}>{v}</p>
            <p className="text-[10px] mt-0.5" style={{ color: 'var(--text-3)' }}>{k}</p>
          </div>
        ))}
      </div>
      {absenteeCount > 0 && (
        <div className="px-4 py-2 bg-pink-950/30 border-b border-pink-900/40 flex-shrink-0">
          <p className="text-[11px] text-pink-300">
            <span className="font-semibold">{absenteeCount}</span> absentee
            owner{absenteeCount !== 1 ? "s" : ""} — potential off-market leads
          </p>
        </div>
      )}

      {/* Parcel list */}
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-2">
        {parcels.map((parcel, i) => {
          const value =
            parcel.land_value > 0 ? parcel.land_value : parcel.market_value;
          return (
            <div
              key={i}
              className="rounded-xl p-3 transition-colors"
              style={{ background: 'var(--surface-2)', border: '1px solid var(--border)' }}
            >
              <div className="flex items-start justify-between gap-2 mb-1.5">
                <div className="flex items-center gap-1.5 min-w-0">
                  <MapPin className="w-3 h-3 text-amber-500 flex-shrink-0" />
                  <p className="text-xs font-medium truncate" style={{ color: 'var(--text)' }}>
                    {parcel.address || "Address not listed"}
                  </p>
                </div>
                {parcel.is_absentee && (
                  <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold uppercase flex-shrink-0 bg-pink-950/60 text-pink-300 border border-pink-800/50">
                    Absentee
                  </span>
                )}
              </div>

              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-3)' }}>Size</span>
                  <span style={{ color: 'var(--text-2)' }}>
                    {parcel.lot_size_acres > 0
                      ? `${parcel.lot_size_acres.toFixed(2)} ac`
                      : "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-3)' }}>Value</span>
                  <span className="text-amber-400 font-medium">
                    {value > 0 ? `$${(value / 1000).toFixed(0)}k` : "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-3)' }}>Owner</span>
                  <span className="truncate max-w-[120px] text-right" style={{ color: 'var(--text-2)' }}>
                    {parcel.owner_name || "—"}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span style={{ color: 'var(--text-3)' }}>Type</span>
                  <span className="capitalize" style={{ color: 'var(--text-2)' }}>
                    {parcel.parcel_type === "land_dominant"
                      ? "Underutilized"
                      : "Vacant"}
                  </span>
                </div>
              </div>

              {parcel.land_use && (
                <p className="text-[10px] mt-1.5 truncate" style={{ color: 'var(--text-3)' }}>
                  {parcel.land_use}
                </p>
              )}
            </div>
          );
        })}
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
  onSelectNearest?: (
    name: string,
    coords: { lat: number; lng: number },
  ) => void;
  extraUniversities?: UniversitySuggestion[];
  hexLoadingName?: string | null;
  hexJustLoaded?: string | null;
  activeLandParcels?: { parcels: LandParcel[]; label: string } | null;
  onDismissLandParcels?: () => void;
  selectedHexProps?: HexFeatureProperties | null;
  onUniversityScored?: (score: HousingPressureScore) => void;
  onExportJob?: (job: ReportJob) => void;
  onSelectHex?: (h3Index: string) => void;
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
  hexLoadingName,
  hexJustLoaded,
  activeLandParcels,
  onDismissLandParcels,
  selectedHexProps,
  onUniversityScored,
  onExportJob,
  onSelectHex,
}: SidePanelProps) {
  const [activeTab, setActiveTab] = useState<"data" | "chat">("data");

  const showEmpty = !selectedName;
  const showPreview = !!selectedName && !activeScore;
  const showScore = !!activeScore;

  const isCurrentSchoolGenerating =
    !!activeJob &&
    activeJob.status === "running" &&
    (activeJob.name === selectedName || activeJob.resolvedName === selectedName);

  return (
    <aside
      className="w-[440px] flex flex-col relative z-20 overflow-hidden"
      style={{
        background: "var(--surface)",
        borderLeft: "1px solid var(--border)",
        boxShadow: "-4px 0 20px rgba(0,0,0,0.3)",
      }}
    >
      {/* Tab Header */}
      {selectedName && (
        <div
          className="flex shrink-0 px-4 gap-1"
          style={{
            position: "relative",
            zIndex: 40,
            borderBottom: "1px solid var(--border)",
            background: "var(--surface)",
          }}
        >
          <button
            onClick={() => {
              setActiveTab("data");
              onDismissLandParcels?.();
            }}
            className="py-3 px-1 text-sm font-medium transition-all"
            style={{
              color:
                activeTab === "data" && !activeLandParcels
                  ? "var(--text)"
                  : "var(--text-3)",
              borderBottom:
                activeTab === "data" && !activeLandParcels
                  ? "2px solid var(--text)"
                  : "2px solid transparent",
              marginBottom: "-1px",
            }}
          >
            Data Report
          </button>
          <button
            onClick={() => {
              setActiveTab("chat");
              onDismissLandParcels?.();
            }}
            className="py-3 px-1 ml-4 text-sm font-medium transition-all"
            style={{
              color:
                activeTab === "chat" && !activeLandParcels
                  ? "var(--text)"
                  : "var(--text-3)",
              borderBottom:
                activeTab === "chat" && !activeLandParcels
                  ? "2px solid var(--accent)"
                  : "2px solid transparent",
              marginBottom: "-1px",
            }}
          >
            AI Assistant
          </button>
        </div>
      )}

      {/* Queue status bar — always on top, shows only when work is pending */}
      <div
        className={`transition-opacity duration-300 ${activeTab === "data" || !selectedName ? "opacity-100" : "opacity-0 pointer-events-none absolute"}`}
      >
        {/* Report bar — only when generating for a DIFFERENT school */}
        {!isCurrentSchoolGenerating && (
          <QueueStatusBar
            activeJob={activeJob}
            queuedJobs={queuedJobs}
            hexLoadingName={hexLoadingName}
          />
        )}

        {/* Standalone hex bars — always shown as a compact top bar */}
        {!activeJob && queuedJobs.length === 0 && hexLoadingName && (
          <HexLoadingBar name={hexLoadingName} />
        )}
        {/* Hex done bar: suppress if you're already on that school (hex is visible) */}
        {!activeJob &&
          queuedJobs.length === 0 &&
          !hexLoadingName &&
          hexJustLoaded &&
          hexJustLoaded !== selectedName && <HexDoneBar name={hexJustLoaded} />}

        {/* Done banners: suppress if you're already viewing that school's report */}
        {doneJobs
          .filter((job) => {
            const jobName = job.resolvedName ?? job.name;
            const isCurrentSchool =
              jobName === selectedName || job.name === selectedName;
            return !(isCurrentSchool && showScore);
          })
          .map((job) => (
            <DoneBanner
              key={job.id}
              job={job}
              onView={onViewReport}
              onDismiss={onDismissJob}
              onExport={onExportJob}
            />
          ))}

        {/* Error banners */}
        {errorJobs.map((job) => (
          <ErrorBanner
            key={job.id}
            job={job}
            onDismiss={onDismissJob}
            onRetry={onGenerateReport}
          />
        ))}
      </div>

      {/* Content panels */}
      <div className="flex-1 overflow-hidden relative flex flex-col">
        {/* Land parcel detail — overlays content area only (tabs remain visible/clickable) */}
        {activeLandParcels && (
          <LandParcelDetailPanel
            parcels={activeLandParcels.parcels}
            label={activeLandParcels.label}
            onDismiss={() => onDismissLandParcels?.()}
          />
        )}

        {/* Full-sidebar agent log — report generating for current school */}
        <div
          className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${
            activeTab === "data" && isCurrentSchoolGenerating
              ? "opacity-100 z-20"
              : "opacity-0 pointer-events-none"
          }`}
        >
          {activeJob && <AgentLogPanel logs={activeJob.logs} />}
        </div>

        {/* Empty — nothing selected */}
        <div
          className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${
            (activeTab === "data" || !selectedName) && showEmpty
              ? "opacity-100"
              : "opacity-0 pointer-events-none"
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
            (activeTab === "data" || !selectedName) &&
            showPreview &&
            !isCurrentSchoolGenerating
              ? "opacity-100"
              : "opacity-0 pointer-events-none"
          }`}
        >
          {selectedName && (
            <PreviewPanel
              name={selectedName}
              onGenerateReport={onGenerateReport}
            />
          )}
        </div>

        {/* Score — computed result */}
        <div
          className={`absolute inset-0 overflow-y-auto transition-opacity duration-300 ${
            (activeTab === "data" || !selectedName) && showScore
              ? "opacity-100"
              : "opacity-0 pointer-events-none"
          }`}
        >
          {activeScore && (
            <ScorePanel score={activeScore} onRecompute={onRecompute} />
          )}
        </div>

        {/* Chatbot Panel - rendered always, but visibility depends on tab */}
        <div
          className={`absolute inset-0 flex flex-col transition-opacity duration-300 ${activeTab === "chat" && !!selectedName ? "opacity-100 z-10" : "opacity-0 pointer-events-none"}`}
        >
          <ChatbotWidget
            selectedName={selectedName}
            activeScore={activeScore}
            selectedHex={selectedHexProps ?? null}
            onUniversityScored={onUniversityScored}
            onSelectHex={onSelectHex}
          />
        </div>
      </div>
    </aside>
  );
}
