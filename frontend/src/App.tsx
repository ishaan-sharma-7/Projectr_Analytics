import { useState, useEffect, useRef } from "react";
import { APIProvider } from "@vis.gl/react-google-maps";
import { streamScore } from "./lib/api";
import { fetchHexGrid } from "./lib/hexApi";
import { SearchBar } from "./components/ui/SearchBar";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { ComparePanel } from "./components/panels/ComparePanel";
import { CompareSetupPanel } from "./components/panels/CompareSetupPanel";
import type { HousingPressureScore } from "./lib/api";
import type { HexGeoJSON } from "./lib/hexApi";

const MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";

interface LogEntry {
  message: string;
  ts: Date;
}

function App() {
  const [searchQuery, setSearchQuery] = useState("");

  // Which pin/university is currently focused in the side panel
  const [selectedName, setSelectedName] = useState<string | null>(null);

  // Persistent caches — computed results stay until explicitly recomputed
  const [scoreCache, setScoreCache] = useState<Record<string, HousingPressureScore>>({});
  const [hexCache, setHexCache] = useState<Record<string, HexGeoJSON>>({});

  // Loading / log state (for the currently running computation)
  const [loading, setLoading] = useState(false);
  const [loadingName, setLoadingName] = useState<string | null>(null);
  const [agentLogs, setAgentLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // ── Compare mode state ──────────────────────────────────────────────────────
  const [compareMode, setCompareMode] = useState(false);
  const [compareNames, setCompareNames] = useState<[string | null, string | null]>([null, null]);

  // Queue: name to auto-run report for after current loading finishes
  const pendingReportRef = useRef<string | null>(null);

  // Derived — what the side panel shows right now
  const activeScore = selectedName ? (scoreCache[selectedName] ?? null) : null;
  const activeHexData = selectedName ? (hexCache[selectedName] ?? null) : null;

  // Derived — compare panel data
  const compareScoreA = compareNames[0] ? (scoreCache[compareNames[0]] ?? null) : null;
  const compareScoreB = compareNames[1] ? (scoreCache[compareNames[1]] ?? null) : null;
  const showCompareResult = compareMode && compareScoreA && compareScoreB;

  // ── Core computation ────────────────────────────────────────────────────────

  const runReport = async (name: string) => {
    setLoading(true);
    setLoadingName(name);
    setError(null);
    setAgentLogs([]);

    try {
      for await (const event of streamScore(name)) {
        if (event.type === "log") {
          setAgentLogs((prev) => [...prev, { message: event.message, ts: new Date() }]);
        } else if (event.type === "result") {
          setScoreCache((prev) => ({ ...prev, [name]: event.data }));
          fetchHexGrid(event.data.university.name)
            .then((hex) => setHexCache((prev) => ({ ...prev, [name]: hex })))
            .catch(() => {});
          setLoading(false);
          setLoadingName(null);
        } else if (event.type === "error") {
          setError(event.message);
          setLoading(false);
          setLoadingName(null);
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch score");
      setLoading(false);
      setLoadingName(null);
    }
  };

  // ── Auto-run queued compare reports ─────────────────────────────────────────
  // When loading finishes and there's a pending name, auto-run it
  useEffect(() => {
    if (!loading && pendingReportRef.current) {
      const pending = pendingReportRef.current;
      pendingReportRef.current = null;
      runReport(pending);
    }
  }, [loading]);

  // ── Handlers ────────────────────────────────────────────────────────────────

  // Pin click or suggestion select
  const handleSelectUniversity = (name: string) => {
    if (compareMode) {
      setCompareNames((prev) => {
        let next: [string | null, string | null];
        if (prev[0] === null) {
          next = [name, prev[1]];
        } else if (prev[1] === null && prev[0] !== name) {
          next = [prev[0], name];
        } else {
          // Both filled or same name — restart with this one
          next = [name, null];
        }

        // Auto-trigger reports for any slot that isn't cached yet
        const needsReport = (n: string | null) => n && !scoreCache[n];

        if (needsReport(next[0]) && needsReport(next[1])) {
          // Both need reports — run first now, queue second
          if (!loading) {
            runReport(next[0]!);
            pendingReportRef.current = next[1]!;
          } else {
            pendingReportRef.current = next[0]!;
          }
        } else if (needsReport(name)) {
          // Only the newly selected one needs a report
          if (!loading) {
            runReport(name);
          } else {
            pendingReportRef.current = name;
          }
        }

        return next;
      });
      setSelectedName(name);
      setSearchQuery(name);
      return;
    }

    // Normal mode — no auto-compute
    setSelectedName(name);
    setSearchQuery(name);
  };

  // Search bar "Enter"
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = searchQuery.trim();
    if (!name) return;
    if (compareMode) {
      handleSelectUniversity(name);
    } else {
      setSelectedName(name);
      await runReport(name);
    }
  };

  // "Generate Report" button in PreviewPanel
  const handleGenerateReport = async (name: string) => {
    setSelectedName(name);
    await runReport(name);
  };

  // "Recompute" button in ScorePanel
  const handleRecompute = async () => {
    if (!selectedName) return;
    await runReport(selectedName);
  };

  // Toggle compare mode
  const handleToggleCompare = () => {
    setCompareMode((prev) => {
      if (!prev) {
        if (selectedName) {
          setCompareNames([selectedName, null]);
        } else {
          setCompareNames([null, null]);
        }
      } else {
        setCompareNames([null, null]);
        pendingReportRef.current = null;
      }
      return !prev;
    });
  };

  // Clear compare selections
  const handleClearCompare = () => {
    setCompareNames([null, null]);
    pendingReportRef.current = null;
    setSelectedName(null);
    setSearchQuery("");
  };

  // Compare guide text for the search bar
  const compareGuide = compareMode
    ? compareNames[0] === null
      ? "Click a pin or search for first university…"
      : compareNames[1] === null
      ? "Now click or search for the second…"
      : undefined
    : undefined;

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-zinc-950 text-zinc-50">
      <SearchBar
        query={searchQuery}
        onChange={setSearchQuery}
        onSubmit={handleSearch}
        onSelectUniversity={handleSelectUniversity}
        disabled={loading && !compareMode}
        compareMode={compareMode}
        onToggleCompare={handleToggleCompare}
        compareGuide={compareGuide}
      />
      <main className="flex-1 flex mt-[73px]">
        <APIProvider apiKey={MAPS_API_KEY}>
          <MapView
            selectedName={selectedName}
            scoreCache={scoreCache}
            activeHexData={activeHexData}
            onPinClick={handleSelectUniversity}
          />
        </APIProvider>

        {/* Side panel: compare result → compare setup → normal */}
        {showCompareResult ? (
          <aside className="w-[440px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl overflow-hidden">
            <ComparePanel
              scoreA={compareScoreA!}
              scoreB={compareScoreB!}
              onClear={handleClearCompare}
            />
          </aside>
        ) : compareMode ? (
          <aside className="w-[440px] border-l border-zinc-800 bg-zinc-950 flex flex-col relative z-20 shadow-2xl overflow-hidden">
            <CompareSetupPanel
              compareNames={compareNames}
              scoreCache={scoreCache}
              loadingName={loadingName}
            />
          </aside>
        ) : (
          <SidePanel
            loading={loading}
            error={error}
            selectedName={selectedName}
            activeScore={activeScore}
            agentLogs={agentLogs}
            onRecompute={handleRecompute}
            onGenerateReport={handleGenerateReport}
          />
        )}
      </main>
    </div>
  );
}

export default App;
