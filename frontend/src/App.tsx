import { useState, useEffect } from "react";
import { APIProvider } from "@vis.gl/react-google-maps";
import { fetchUniversities, streamScore, computeScoreById } from "./lib/api";
import { fetchHexGrid } from "./lib/hexApi";
import { SearchBar } from "./components/ui/SearchBar";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import type { HousingPressureScore, UniversityListItem } from "./lib/api";
import type { HexGeoJSON } from "./lib/hexApi";

const MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";

interface LogEntry {
  message: string;
  ts: Date;
}

function App() {
  const [searchQuery, setSearchQuery] = useState("");
  const [universities, setUniversities] = useState<UniversityListItem[]>([]);
  const [activeScore, setActiveScore] = useState<HousingPressureScore | null>(null);
  const [hexData, setHexData] = useState<HexGeoJSON | null>(null);
  const [loading, setLoading] = useState(false);
  const [agentLogs, setAgentLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // Load pre-scored universities for national map on mount
  useEffect(() => {
    fetchUniversities()
      .then(setUniversities)
      .catch(() => {});
  }, []);

  // Fetch H3 hex grid whenever a new score is set
  const loadHexData = (score: HousingPressureScore) => {
    setHexData(null);
    fetchHexGrid(score.university.name).then(setHexData).catch(() => {});
  };

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;

    setLoading(true);
    setError(null);
    setActiveScore(null);
    setHexData(null);
    setAgentLogs([]);

    try {
      for await (const event of streamScore(searchQuery)) {
        if (event.type === "log") {
          setAgentLogs((prev) => [...prev, { message: event.message, ts: new Date() }]);
        } else if (event.type === "result") {
          setActiveScore(event.data);
          loadHexData(event.data);
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

  const handleMarkerClick = async (unitid: number) => {
    setLoading(true);
    setError(null);
    setActiveScore(null);
    setHexData(null);
    setAgentLogs([{ message: "Loading from pre-scored cache...", ts: new Date() }]);
    try {
      const result = await computeScoreById(unitid);
      setActiveScore(result);
      loadHexData(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load university");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-zinc-950 text-zinc-50">
      <SearchBar
        query={searchQuery}
        onChange={setSearchQuery}
        onSubmit={handleSearch}
        onSelectUniversity={(unitid, name) => {
          setSearchQuery(name);
          handleMarkerClick(unitid);
        }}
        universities={universities}
        disabled={loading}
      />
      <main className="flex-1 flex mt-[73px]">
        <APIProvider apiKey={MAPS_API_KEY}>
          <MapView
            universities={universities}
            activeScore={activeScore}
            hexData={hexData}
            onMarkerClick={handleMarkerClick}
          />
        </APIProvider>
        <SidePanel
          loading={loading}
          error={error}
          activeScore={activeScore}
          agentLogs={agentLogs}
          universityCount={universities.length}
        />
      </main>
    </div>
  );
}

export default App;
