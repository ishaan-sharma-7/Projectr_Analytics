import { useState, useEffect, useRef } from "react";
import { APIProvider } from "@vis.gl/react-google-maps";
import { streamScore } from "./lib/api";
import { fetchHexGrid } from "./lib/hexApi";
import { readCache, writeEntry } from "./lib/storage";
import { UNIVERSITIES } from "./lib/universityList";
import type { UniversitySuggestion } from "./lib/universityList";
import { SearchBar } from "./components/ui/SearchBar";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { ComparePanel } from "./components/panels/ComparePanel";
import { CompareSetupPanel } from "./components/panels/CompareSetupPanel";
import type { HousingPressureScore } from "./lib/api";
import type { HexGeoJSON } from "./lib/hexApi";
import LocationButton from "./components/LocationButton";
const MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";
const CACHE_VERSION = "v8";
const SCORE_CACHE_KEY = `campuslens_scores_${CACHE_VERSION}`;
const HEX_CACHE_KEY = `campuslens_hex_${CACHE_VERSION}`;
const DYNAMIC_UNIS_CACHE_KEY = `campuslens_dynamic_unis_${CACHE_VERSION}`;
const CACHE_SCHEMA_KEY = "campuslens_cache_schema_version";
const DEFAULT_HEX_RADIUS_MILES = 1.5;
const HEX_RESOLUTION = 9;

interface LogEntry {
  message: string;
  ts: Date;
}

/** Extract a bare hostname from a Scorecard URL like "www.vt.edu" or "https://vt.edu/". */
function extractDomain(url: string | null): string {
  if (!url) return "";
  try {
    const withProto = url.startsWith("http") ? url : `https://${url}`;
    return new URL(withProto).hostname.replace(/^www\./, "");
  } catch {
    return url.replace(/^https?:\/\//, "").replace(/^www\./, "").split("/")[0];
  }
}

function isValidLatLng(lat: number, lng: number): boolean {
  return (
    Number.isFinite(lat)
    && Number.isFinite(lng)
    && lat >= -90
    && lat <= 90
    && lng >= -180
    && lng <= 180
  );
}

function normalizeSchoolName(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, " ")
    .trim()
    .replace(/\s+/g, " ");
}

function isVirginiaTechName(name: string): boolean {
  const normalized = normalizeSchoolName(name);
  return (
    normalized.includes("virginia tech")
    || normalized.includes("virginia polytechnic institute and state university")
  );
}

function hexCacheKey(
  name: string,
  resolution: number,
  debugHex: boolean,
  radiusMiles: number
): string {
  const radiusToken = radiusMiles.toFixed(2);
  return `${name}::hex_r${resolution}::rad${radiusToken}${debugHex ? "::dbg1" : ""}`;
}

function clearHexEntriesForName(
  cache: Record<string, HexGeoJSON>,
  name: string
): Record<string, HexGeoJSON> {
  const next = { ...cache };
  for (const key of Object.keys(next)) {
    if (key === name || key.startsWith(`${name}::hex_r`)) {
      delete next[key];
    }
  }
  return next;
}

function findKnownCoords(
  name: string,
  dynamicUnis: Record<string, UniversitySuggestion>,
  scoreCache?: Record<string, HousingPressureScore>
): { lat: number; lng: number } | null {
  const dynamic = dynamicUnis[name];
  if (dynamic && isValidLatLng(dynamic.lat, dynamic.lon)) {
    return { lat: dynamic.lat, lng: dynamic.lon };
  }
  const staticUni = UNIVERSITIES.find((u) => u.name === name);
  if (staticUni && isValidLatLng(staticUni.lat, staticUni.lon)) {
    return { lat: staticUni.lat, lng: staticUni.lon };
  }

  const target = normalizeSchoolName(name);
  for (const uni of Object.values(dynamicUnis)) {
    if (
      normalizeSchoolName(uni.name) === target
      && isValidLatLng(uni.lat, uni.lon)
    ) {
      return { lat: uni.lat, lng: uni.lon };
    }
  }
  for (const uni of UNIVERSITIES) {
    if (
      normalizeSchoolName(uni.name) === target
      && isValidLatLng(uni.lat, uni.lon)
    ) {
      return { lat: uni.lat, lng: uni.lon };
    }
  }
  if (scoreCache) {
    const scored = scoreCache[name];
    if (
      scored
      && isValidLatLng(scored.university.lat, scored.university.lon)
    ) {
      return { lat: scored.university.lat, lng: scored.university.lon };
    }
    for (const value of Object.values(scoreCache)) {
      const uni = value.university;
      if (
        normalizeSchoolName(uni.name) === target
        && isValidLatLng(uni.lat, uni.lon)
      ) {
        return { lat: uni.lat, lng: uni.lon };
      }
    }
  }
  return null;
}

function App() {
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [selectedCoords, setSelectedCoords] = useState<{ lat: number; lng: number } | null>(null);
  // Persistent score + hex caches — survive page refresh for 24 h
  const [scoreCache, setScoreCache] = useState<Record<string, HousingPressureScore>>(
    () => readCache<HousingPressureScore>(SCORE_CACHE_KEY)
  );
  const [hexCache, setHexCache] = useState<Record<string, HexGeoJSON>>(
    () => readCache<HexGeoJSON>(HEX_CACHE_KEY)
  );

  // Dynamic universities discovered via search — appear as map pins and suggestions
  const [dynamicUnis, setDynamicUnis] = useState<Record<string, UniversitySuggestion>>(
    () => readCache<UniversitySuggestion>(DYNAMIC_UNIS_CACHE_KEY)
  );

  const [loading, setLoading] = useState(false);
  const [mapZoom, setMapZoom] = useState<number>(14);
  const [loadingName, setLoadingName] = useState<string | null>(null);
  const [agentLogs, setAgentLogs] = useState<LogEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  // One-time cache schema migration: clears old localhost cache buckets.
  useEffect(() => {
    try {
      const current = localStorage.getItem(CACHE_SCHEMA_KEY);
      if (current === CACHE_VERSION) return;
      localStorage.removeItem("campuslens_scores");
      localStorage.removeItem("campuslens_hex");
      localStorage.removeItem("campuslens_dynamic_unis");
      localStorage.removeItem("campuslens_scores_v2");
      localStorage.removeItem("campuslens_hex_v2");
      localStorage.removeItem("campuslens_dynamic_unis_v2");
      localStorage.removeItem("campuslens_scores_v3");
      localStorage.removeItem("campuslens_hex_v3");
      localStorage.removeItem("campuslens_dynamic_unis_v3");
      localStorage.removeItem("campuslens_scores_v4");
      localStorage.removeItem("campuslens_hex_v4");
      localStorage.removeItem("campuslens_dynamic_unis_v4");
      localStorage.removeItem("campuslens_scores_v5");
      localStorage.removeItem("campuslens_hex_v5");
      localStorage.removeItem("campuslens_dynamic_unis_v5");
      localStorage.setItem(CACHE_SCHEMA_KEY, CACHE_VERSION);
    } catch {
      // Ignore storage failures in private mode.
    }
  }, []);

  // ── Compare mode state ──────────────────────────────────────────────────
  const [compareMode, setCompareMode] = useState(false);
  const [compareNames, setCompareNames] = useState<[string | null, string | null]>([null, null]);

  // Queue: name to auto-run report for after current loading finishes
  const pendingReportRef = useRef<string | null>(null);
  const inflightHexLoadsRef = useRef<Set<string>>(new Set());

  // Derived — what the side panel shows right now
  const activeScore = selectedName ? (scoreCache[selectedName] ?? null) : null;
  const activeHexData = (() => {
    if (!selectedName || mapZoom < 11) return null;
    const debugHex = isVirginiaTechName(selectedName);
    const preferredKeys = [
      hexCacheKey(selectedName, HEX_RESOLUTION, debugHex, DEFAULT_HEX_RADIUS_MILES),
      selectedName,
    ];
    for (const key of preferredKeys) {
      const data = hexCache[key];
      if (data) return data;
    }
    return null;
  })();

  // Derived — compare panel data
  const compareScoreA = compareNames[0] ? (scoreCache[compareNames[0]] ?? null) : null;
  const compareScoreB = compareNames[1] ? (scoreCache[compareNames[1]] ?? null) : null;
  const showCompareResult = compareMode && compareScoreA && compareScoreB;

  // ── Core computation ──────────────────────────────────────────────────────

  const loadHexStream = async (
    queryName: string,
    cacheNames: string[],
    resolution: number,
    radiusMiles: number,
    debugHex: boolean,
    clearTargetBeforeLoad = false,
    persistToStorage = true
  ) => {
    const names = Array.from(new Set(cacheNames.filter(Boolean)));
    if (names.length === 0) return;

    const requestKey = `${queryName}::hex_r${resolution}::rad${radiusMiles.toFixed(2)}${debugHex ? "::dbg1" : ""}`;
    if (inflightHexLoadsRef.current.has(requestKey)) return;
    inflightHexLoadsRef.current.add(requestKey);

    try {
      if (clearTargetBeforeLoad) {
        setHexCache((prev) => {
          const next = { ...prev };
          for (const n of names) {
            delete next[hexCacheKey(n, resolution, debugHex, radiusMiles)];
          }
          return next;
        });
      }

      let partial: HexGeoJSON = {
        type: "FeatureCollection",
        features: [],
        metadata: undefined,
      };

      const applyPartial = (payload: HexGeoJSON) => {
        setHexCache((prev) => {
          const next = { ...prev };
          for (const n of names) {
            next[hexCacheKey(n, resolution, debugHex, radiusMiles)] = payload;
          }
          return next;
        });
      };

      applyPartial(partial);

      partial = await fetchHexGrid(
        queryName,
        radiusMiles,
        resolution,
        false,
        debugHex
      );
      applyPartial(partial);
      if (persistToStorage) {
        for (const n of names) {
          writeEntry(HEX_CACHE_KEY, hexCacheKey(n, resolution, debugHex, radiusMiles), partial);
        }
      }
    } catch {
      // keep side panel usable even if hex stream fails
    } finally {
      inflightHexLoadsRef.current.delete(requestKey);
    }
  };

  const runReport = async (name: string, forceRefreshHex = false) => {
    setLoading(true);
    setLoadingName(name);
    setError(null);
    setAgentLogs([]);
    if (forceRefreshHex) {
      setHexCache((prev) => clearHexEntriesForName(prev, name));
    }

    try {
      for await (const event of streamScore(name)) {
        if (event.type === "log") {
          setAgentLogs((prev) => [...prev, { message: event.message, ts: new Date() }]);
        } else if (event.type === "result") {
          const uni = event.data.university;
          const actualName = uni.name;

          // ── Score cache: store under query key AND actual university name ──
          // This ensures pin clicks (which use actualName) also hit the cache.
          setScoreCache((prev) => {
            const next = { ...prev, [name]: event.data };
            if (actualName !== name) next[actualName] = event.data;
            return next;
          });
          writeEntry(SCORE_CACHE_KEY, name, event.data);
          if (actualName !== name) writeEntry(SCORE_CACHE_KEY, actualName, event.data);

          // ── Dynamic pin: add if not already in the static list ────────────
          const inStatic =
            UNIVERSITIES.some((u) => u.name === name) ||
            UNIVERSITIES.some((u) => u.name === actualName);

          if (!inStatic) {
            const newPin: UniversitySuggestion = {
              name: actualName,
              city: uni.city,
              state: uni.state,
              lat: uni.lat,
              lon: uni.lon,
              domain: extractDomain(uni.url),
            };
            setDynamicUnis((prev) => ({ ...prev, [actualName]: newPin }));
            writeEntry(DYNAMIC_UNIS_CACHE_KEY, actualName, newPin);
          }

          // ── Hex cache (single resolution stream) ────────────────────────
          const debugHex = isVirginiaTechName(actualName) || isVirginiaTechName(name);
          void loadHexStream(
            actualName,
            [name, actualName],
            HEX_RESOLUTION,
            DEFAULT_HEX_RADIUS_MILES,
            debugHex,
            forceRefreshHex,
            true
          );

          // Canonicalize to backend-resolved name so map targeting is stable.
          setSelectedName(actualName);
          setSearchQuery(actualName);
          if (isValidLatLng(uni.lat, uni.lon)) {
            setSelectedCoords({ lat: uni.lat, lng: uni.lon });
          }
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

  // ── Auto-run queued compare reports ───────────────────────────────────────
  // When loading finishes and there's a pending name, auto-run it
  useEffect(() => {
    if (!loading && pendingReportRef.current) {
      const pending = pendingReportRef.current;
      pendingReportRef.current = null;
      runReport(pending);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  // Safety net: if a name is selected but coords are missing/stale, derive
  // coords from known university lists/cache so camera can always target.
  useEffect(() => {
    if (!selectedName) return;
    if (
      selectedCoords
      && isValidLatLng(selectedCoords.lat, selectedCoords.lng)
    ) {
      return;
    }
    const known = findKnownCoords(selectedName, dynamicUnis, scoreCache);
    if (known) {
      setSelectedCoords(known);
    }
  }, [selectedName, selectedCoords, dynamicUnis, scoreCache]);

  // Hex loading: ensure selected campus + radius has a fetched grid.
  useEffect(() => {
    if (!selectedName || loading) return;
    const debugHex = isVirginiaTechName(selectedName);
    const key = hexCacheKey(selectedName, HEX_RESOLUTION, debugHex, DEFAULT_HEX_RADIUS_MILES);
    if (!hexCache[key]) {
      void loadHexStream(
        selectedName,
        [selectedName],
        HEX_RESOLUTION,
        DEFAULT_HEX_RADIUS_MILES,
        debugHex,
        false
      );
    }
  }, [selectedName, hexCache, loading]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Handlers ──────────────────────────────────────────────────────────────

  /** Pin click or suggestion select — in compare mode fills slots and auto-runs
   *  reports for uncached selections; in normal mode just shows preview. */
  const handleSelectUniversity = (name: string, coords?: { lat: number; lng: number }) => {
    if (coords && isValidLatLng(coords.lat, coords.lng)) {
      setSelectedCoords(coords);
    } else {
      const known = findKnownCoords(name, dynamicUnis, scoreCache);
      if (known) setSelectedCoords(known);
    }

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

  /** Search bar Enter — in compare mode delegates to selection, else explicit compute. */
  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    const name = searchQuery.trim();
    if (!name) return;
    if (compareMode) {
      handleSelectUniversity(name);
    } else {
      const known = findKnownCoords(name, dynamicUnis, scoreCache);
      if (known) setSelectedCoords(known);
      setSelectedName(name);
      await runReport(name);
    }
  };

  /** "Generate Report" button in PreviewPanel. */
  const handleGenerateReport = async (name: string) => {
    const known = findKnownCoords(name, dynamicUnis, scoreCache);
    if (known) setSelectedCoords(known);
    setSelectedName(name);
    await runReport(name);
  };

  /** "Recompute" button in ScorePanel. */
  const handleRecompute = async () => {
    if (!selectedName) return;
    await runReport(selectedName, true);
  };

  const handleHoverPrefetch = (name: string) => {
    const debugHex = isVirginiaTechName(name);
    const key = hexCacheKey(name, HEX_RESOLUTION, debugHex, DEFAULT_HEX_RADIUS_MILES);
    if (!hexCache[key]) {
      void loadHexStream(name, [name], HEX_RESOLUTION, DEFAULT_HEX_RADIUS_MILES, debugHex, false, false);
    }
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
    setSelectedCoords(null);
    setSearchQuery("");
  };

  const handleZoomOutMap = () => {
    setSelectedName(null);
    setSelectedCoords(null);
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
        extraUniversities={Object.values(dynamicUnis)}
        disabled={loading && !compareMode}
        compareMode={compareMode}
        onToggleCompare={handleToggleCompare}
        compareGuide={compareGuide}
      />
      <LocationButton />
      <main className="flex mt-[73px] h-[calc(100vh-73px)]">
        <APIProvider apiKey={MAPS_API_KEY}>
          <MapView
            selectedName={selectedName}
            selectedCoords={selectedCoords}
            scoreCache={scoreCache}
            dynamicUnis={dynamicUnis}
            activeHexData={activeHexData}
            onPinClick={handleSelectUniversity}
            onZoomOut={handleZoomOutMap}
            onZoomChange={setMapZoom}
            onHoverPrefetch={handleHoverPrefetch}
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
