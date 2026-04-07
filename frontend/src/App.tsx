import { useState } from "react";
import { APIProvider } from "@vis.gl/react-google-maps";
import { streamScore } from "./lib/api";
import { fetchHexGrid } from "./lib/hexApi";
import { SearchBar } from "./components/ui/SearchBar";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
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
  const [agentLogs, setAgentLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Derived — what the side panel shows right now
  const activeScore = selectedName ? (scoreCache[selectedName] ?? null) : null;
  const activeHexData = selectedName ? (hexCache[selectedName] ?? null) : null;

  // ── Core computation ────────────────────────────────────────────────────────

  const runReport = async (name: string) => {
    setLoading(true);
    setError(null);
    setAgentLogs([]);

    try {
      for await (const event of streamScore(name)) {
        if (event.type === "log") {
          setAgentLogs((prev) => [...prev, { message: event.message, ts: new Date() }]);
        } else if (event.type === "result") {
          // Store in persistent cache keyed by the queried name
          setScoreCache((prev) => ({ ...prev, [name]: event.data }));
          fetchHexGrid(event.data.university.name)
            .then((hex) => setHexCache((prev) => ({ ...prev, [name]: hex })))
            .catch(() => {});
          setLoading(false);
        } else if (event.type === "error") {
          setError(event.message);
          setLoading(false);
        }
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch score");
      setLoading(false);
    }
  };

  // ── Handlers ────────────────────────────────────────────────────────────────

  // Pin click or suggestion select — navigate to university, show preview or cached result
  const handleSelectUniversity = (name: string) => {
    setSelectedName(name);
    setSearchQuery(name);
    // No computation — PreviewPanel shows with "Generate Report" button
    // If already cached, ScorePanel shows instantly
  };

  // Search bar "Enter" or "Search for X" row — explicit request to compute
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = searchQuery.trim();
    if (!name) return;
    setSelectedName(name);
    await runReport(name);
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

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-zinc-950 text-zinc-50">
      <SearchBar
        query={searchQuery}
        onChange={setSearchQuery}
        onSubmit={handleSearch}
        onSelectUniversity={handleSelectUniversity}
        disabled={loading}
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
        <SidePanel
          loading={loading}
          error={error}
          selectedName={selectedName}
          activeScore={activeScore}
          agentLogs={agentLogs}
          onRecompute={handleRecompute}
          onGenerateReport={handleGenerateReport}
        />
      </main>
    </div>
  );
}

export default App;
