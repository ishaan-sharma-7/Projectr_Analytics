import { useState, useEffect, useRef } from "react";
import { exportToPDF } from "./lib/exportReport";
import { APIProvider } from "@vis.gl/react-google-maps";
import { streamScore, fetchUniversities } from "./lib/api";
import { fetchHexGrid } from "./lib/hexApi";
import { readCache, writeEntry, readSplitCache, writeSplitEntry, purgeSplitCache } from "./lib/storage";
import { UNIVERSITIES } from "./lib/universityList";
import type { UniversitySuggestion } from "./lib/universityList";
import { SearchBar } from "./components/ui/SearchBar";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { ComparePanel } from "./components/panels/ComparePanel";
import { CompareSetupPanel } from "./components/panels/CompareSetupPanel";
import { RankingView } from "./components/RankingView";
import type { HousingPressureScore, UniversityListItem } from "./lib/api";
import type { HexGeoJSON, HexFeatureProperties } from "./lib/hexApi";

const MAPS_API_KEY = import.meta.env.VITE_GOOGLE_MAPS_API_KEY || "";
const CACHE_VERSION = "v10";
const SCORE_CACHE_KEY = `campuslens_scores_${CACHE_VERSION}`;
const HEX_CACHE_KEY = `campuslens_hex_${CACHE_VERSION}`;
const DYNAMIC_UNIS_CACHE_KEY = `campuslens_dynamic_unis_${CACHE_VERSION}`;
const CACHE_SCHEMA_KEY = "campuslens_cache_schema_version";
const MAX_HEX_RADIUS_MILES = 5.0;
const DEFAULT_HEX_RADIUS_MILES = 2.5;
const HEX_RESOLUTION = 9;

export interface LogEntry {
  message: string;
  ts: Date;
}

export interface ReportJob {
  id: string;
  name: string;
  resolvedName?: string; // backend-canonical name, set on completion
  status: "queued" | "running" | "done" | "error";
  logs: LogEntry[];
  errorMsg?: string;
  forceRefreshHex: boolean;
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
    () => readSplitCache<HexGeoJSON>(HEX_CACHE_KEY)
  );

  // Currently selected hex cell (clicked by user on map) — forwarded to chat
  const [selectedHexProps, setSelectedHexProps] = useState<HexFeatureProperties | null>(null);
  // Hex ID to focus on the map (set by chat agent recommendations)
  const [focusHexId, setFocusHexId] = useState<string | null>(null);

  // Land parcel detail panel — populated when user clicks "view all" in a hex popup
  const [activeLandParcels, setActiveLandParcels] = useState<{
    parcels: { address: string; lot_size_acres: number; land_value: number; market_value: number; owner_name: string; is_absentee: boolean; land_use: string; parcel_type: string }[];
    label: string;
  } | null>(null);

  // Dynamic universities discovered via search — appear as map pins and suggestions
  const [dynamicUnis, setDynamicUnis] = useState<Record<string, UniversitySuggestion>>(
    () => readCache<UniversitySuggestion>(DYNAMIC_UNIS_CACHE_KEY)
  );

  const [mapZoom, setMapZoom] = useState<number>(14);
  const [hexRadiusMiles, setHexRadiusMiles] = useState(DEFAULT_HEX_RADIUS_MILES);

  // ── Report queue ────────────────────────────────────────────────────────────
  const [reportQueue, setReportQueue] = useState<ReportJob[]>([]);
  const isProcessingRef = useRef(false);
  const inflightHexLoadsRef = useRef<Set<string>>(new Set());

  // ── Hex loading state ────────────────────────────────────────────────────────
  const [hexLoadingNames, setHexLoadingNames] = useState<Set<string>>(new Set());
  const [hexJustLoaded, setHexJustLoaded] = useState<string | null>(null);

  // Derived — what CompareSetupPanel needs
  const loadingName = reportQueue.find(j => j.status === "running")?.name ?? null;

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
      localStorage.removeItem("campuslens_scores_v6");
      localStorage.removeItem("campuslens_hex_v6");
      localStorage.removeItem("campuslens_dynamic_unis_v6");
      localStorage.removeItem("campuslens_scores_v7");
      localStorage.removeItem("campuslens_hex_v7");
      localStorage.removeItem("campuslens_dynamic_unis_v7");
      localStorage.removeItem("campuslens_scores_v8");
      localStorage.removeItem("campuslens_hex_v8");
      localStorage.removeItem("campuslens_dynamic_unis_v8");
      localStorage.removeItem("campuslens_scores_v9");
      localStorage.removeItem("campuslens_hex_v9");
      localStorage.removeItem("campuslens_dynamic_unis_v9");
      purgeSplitCache("campuslens_hex_v8");
      purgeSplitCache("campuslens_hex_v9");
      localStorage.setItem(CACHE_SCHEMA_KEY, CACHE_VERSION);
    } catch {
      // Ignore storage failures in private mode.
    }
  }, []);

  // ── Compare mode state ──────────────────────────────────────────────────────
  const [compareMode, setCompareMode] = useState(false);
  const [compareNames, setCompareNames] = useState<[string | null, string | null]>([null, null]);

  // ── Ranking mode state ──────────────────────────────────────────────────
  const [rankingMode, setRankingMode] = useState(false);
  const [nationalUniversities, setNationalUniversities] = useState<UniversityListItem[]>([]);

  // Fetch pre-scored universities on mount
  useEffect(() => {
    fetchUniversities()
      .then(setNationalUniversities)
      .catch(() => {});
  }, []);
  // Derived — what the side panel shows right now
  const activeScore = selectedName ? (scoreCache[selectedName] ?? null) : null;
  const activeHexData = (() => {
    if (!selectedName || mapZoom < 11) return null;
    if (!scoreCache[selectedName]) return null; // require paired cached score
    const debugHex = isVirginiaTechName(selectedName);
    const preferredKeys = [
      hexCacheKey(selectedName, HEX_RESOLUTION, debugHex, MAX_HEX_RADIUS_MILES),
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

  // ── Hex loading ─────────────────────────────────────────────────────────────

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
    setHexLoadingNames(prev => new Set([...prev, queryName]));
    setHexJustLoaded(null);

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

      let partial: HexGeoJSON = { type: "FeatureCollection", features: [], metadata: undefined };

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

      partial = await fetchHexGrid(queryName, radiusMiles, resolution, false, debugHex);
      applyPartial(partial);
      if (persistToStorage) {
        for (const n of names) {
          writeSplitEntry(HEX_CACHE_KEY, hexCacheKey(n, resolution, debugHex, radiusMiles), partial);
        }
      }
    } catch {
      // keep side panel usable even if hex fetch fails
    } finally {
      inflightHexLoadsRef.current.delete(requestKey);
      setHexLoadingNames(prev => {
        const next = new Set(prev);
        next.delete(queryName);
        return next;
      });
      setHexJustLoaded(queryName);
      setTimeout(() => setHexJustLoaded(prev => prev === queryName ? null : prev), 4000);
    }
  };

  // Hex loading: fetch hex grid only for the selected university, only when
  // score is cached AND user is at city zoom. Avoids phantom hex loads for
  // universities the user isn't viewing.
  const hexCacheRef = useRef(hexCache);
  hexCacheRef.current = hexCache;
  useEffect(() => {
    if (!selectedName) return;
    if (!scoreCache[selectedName]) return;
    if (mapZoom < 11) return; // only load at city zoom
    const debugHex = isVirginiaTechName(selectedName);
    const key = hexCacheKey(selectedName, HEX_RESOLUTION, debugHex, MAX_HEX_RADIUS_MILES);
    if (!hexCacheRef.current[key]) {
      void loadHexStream(selectedName, [selectedName], HEX_RESOLUTION, MAX_HEX_RADIUS_MILES, debugHex, false);
    }
  }, [selectedName, scoreCache, mapZoom]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── Report queue processing ─────────────────────────────────────────────────

  const enqueueReport = (name: string, forceRefreshHex = false) => {
    setReportQueue(prev => {
      // Already queued or running — skip
      if (prev.some(j => j.name === name && (j.status === "queued" || j.status === "running"))) {
        return prev;
      }
      // Remove any stale error/done entry for this name, then append
      const filtered = prev.filter(j => !(j.name === name && (j.status === "error" || j.status === "done")));
      const id = `${name}::${Date.now()}`;
      return [...filtered, { id, name, status: "queued", logs: [], forceRefreshHex }];
    });
  };

  const dismissJob = (id: string) => {
    setReportQueue(prev => prev.filter(j => j.id !== id));
  };

  const handleViewReport = (job: ReportJob) => {
    const name = job.resolvedName ?? job.name;
    const known = findKnownCoords(name, dynamicUnis, scoreCache);
    if (known) setSelectedCoords(known);
    setSelectedName(name);
    setSearchQuery(name);
    dismissJob(job.id);
  };

  // Process the next queued job whenever the queue changes
  useEffect(() => {
    const nextQueued = reportQueue.find(j => j.status === "queued");
    const hasRunning = reportQueue.some(j => j.status === "running");

    if (!nextQueued || hasRunning || isProcessingRef.current) return;

    isProcessingRef.current = true;
    const job = nextQueued;

    // Mark running synchronously, then execute
    setReportQueue(prev => prev.map(j => j.id === job.id ? { ...j, status: "running" as const } : j));

    const run = async () => {
      const { id, name, forceRefreshHex } = job;

      if (forceRefreshHex) {
        setHexCache(prev => clearHexEntriesForName(prev, name));
      }

      try {
        for await (const event of streamScore(name)) {
          if (event.type === "log") {
            setReportQueue(prev => prev.map(j =>
              j.id === id
                ? { ...j, logs: [...j.logs, { message: event.message, ts: new Date() }] }
                : j
            ));
          } else if (event.type === "result") {
            const uni = event.data.university;
            const actualName = uni.name;

            setScoreCache(prev => {
              const next = { ...prev, [name]: event.data };
              if (actualName !== name) next[actualName] = event.data;
              return next;
            });
            writeEntry(SCORE_CACHE_KEY, name, event.data);
            if (actualName !== name) writeEntry(SCORE_CACHE_KEY, actualName, event.data);

            setNationalUniversities(prev => {
              const newItem: UniversityListItem = {
                unitid: uni.unitid,
                name: actualName,
                city: uni.city,
                state: uni.state,
                lat: uni.lat,
                lon: uni.lon,
                score: event.data.score,
                score_label: event.data.score >= 70 ? "high" : event.data.score >= 40 ? "medium" : "low"
              };
              const existingIndex = prev.findIndex(u => u.unitid === uni.unitid);
              if (existingIndex >= 0) {
                const next = [...prev];
                next[existingIndex] = newItem;
                return next;
              }
              return [...prev, newItem];
            });

            const inStatic =
              UNIVERSITIES.some(u => u.name === name) ||
              UNIVERSITIES.some(u => u.name === actualName);

            if (!inStatic) {
              const newPin: UniversitySuggestion = {
                name: actualName,
                city: uni.city,
                state: uni.state,
                lat: uni.lat,
                lon: uni.lon,
                domain: extractDomain(uni.url),
              };
              setDynamicUnis(prev => ({ ...prev, [actualName]: newPin }));
              writeEntry(DYNAMIC_UNIS_CACHE_KEY, actualName, newPin);
            }

            // Hex data loaded on-demand when user views university at city zoom
            // (driven by the hex loading useEffect, not eagerly here)

            // Mark done — let the user navigate themselves
            setReportQueue(prev => prev.map(j =>
              j.id === id ? { ...j, status: "done" as const, resolvedName: actualName } : j
            ));
          } else if (event.type === "error") {
            setReportQueue(prev => prev.map(j =>
              j.id === id ? { ...j, status: "error" as const, errorMsg: event.message } : j
            ));
          }
        }
      } catch (err: unknown) {
        setReportQueue(prev => prev.map(j =>
          j.id === id
            ? { ...j, status: "error" as const, errorMsg: err instanceof Error ? err.message : "Failed to fetch score" }
            : j
        ));
      } finally {
        isProcessingRef.current = false;
      }
    };

    run();
  }, [reportQueue]); // eslint-disable-line react-hooks/exhaustive-deps

  // Safety net: if a name is selected but coords are missing/stale, derive coords.
  useEffect(() => {
    if (!selectedName) return;
    if (selectedCoords && isValidLatLng(selectedCoords.lat, selectedCoords.lng)) return;
    const known = findKnownCoords(selectedName, dynamicUnis, scoreCache);
    if (known) setSelectedCoords(known);
  }, [selectedName, selectedCoords, dynamicUnis, scoreCache]);

  // ── Handlers ────────────────────────────────────────────────────────────────

  /** Pin click or suggestion select */
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
          next = [name, null];
        }

        const needsReport = (n: string | null) => n && !scoreCache[n];
        if (needsReport(next[0])) enqueueReport(next[0]!);
        if (needsReport(next[1])) enqueueReport(next[1]!);

        return next;
      });
      setSelectedName(name);
      setSearchQuery(name);
      return;
    }

    setSelectedName(name);
    setSearchQuery(name);
  };

  /** Logo / title click — return to map with no selection */
  const handleHome = () => {
    setSelectedName(null);
    setSelectedCoords(null);
    setSearchQuery("");
    if (compareMode) handleToggleCompare();
    if (rankingMode) setRankingMode(false);
  };

  /** Search bar Enter */
  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    const name = searchQuery.trim();
    if (!name) return;
    if (compareMode) {
      handleSelectUniversity(name);
    } else {
      const known = findKnownCoords(name, dynamicUnis, scoreCache);
      if (known) setSelectedCoords(known);
      setSelectedName(name);
      enqueueReport(name);
    }
  };

  /** "Generate Report" button in PreviewPanel */
  const handleGenerateReport = (name: string) => {
    const known = findKnownCoords(name, dynamicUnis, scoreCache);
    if (known) setSelectedCoords(known);
    setSelectedName(name);
    enqueueReport(name);
  };

  /** "Recompute" button in ScorePanel */
  const handleRecompute = () => {
    if (!selectedName) return;
    enqueueReport(selectedName, true);
  };

  /** Called by ChatbotWidget when the AI agent scores a new university during chat. */
  const handleUniversityScored = (score: HousingPressureScore) => {
    const uni = score.university;
    const name = uni.name;

    setScoreCache(prev => ({ ...prev, [name]: score }));
    writeEntry(SCORE_CACHE_KEY, name, score);

    setNationalUniversities(prev => {
      const item: UniversityListItem = {
        unitid: uni.unitid,
        name,
        city: uni.city,
        state: uni.state,
        lat: uni.lat,
        lon: uni.lon,
        score: score.score,
        score_label: score.score >= 70 ? "high" : score.score >= 40 ? "medium" : "low",
      };
      const idx = prev.findIndex(u => u.unitid === uni.unitid);
      if (idx >= 0) {
        const next = [...prev];
        next[idx] = item;
        return next;
      }
      return [...prev, item];
    });

    const inStatic = UNIVERSITIES.some(u => u.name === name);
    if (!inStatic) {
      const pin: UniversitySuggestion = {
        name,
        city: uni.city,
        state: uni.state,
        lat: uni.lat,
        lon: uni.lon,
        domain: extractDomain(uni.url),
      };
      setDynamicUnis(prev => ({ ...prev, [name]: pin }));
      writeEntry(DYNAMIC_UNIS_CACHE_KEY, name, pin);
    }

    const debugHex = isVirginiaTechName(name);
    void loadHexStream(name, [name], HEX_RESOLUTION, MAX_HEX_RADIUS_MILES, debugHex, false, true);
  };

  /** Download PDF from the DoneBanner — looks up score from cache */
  const handleExportJob = (job: ReportJob) => {
    const name = job.resolvedName ?? job.name;
    const score = scoreCache[name];
    if (score) void exportToPDF(score);
  };

  const handleHoverPrefetch = (name: string) => {
    const debugHex = isVirginiaTechName(name);
    const key = hexCacheKey(name, HEX_RESOLUTION, debugHex, MAX_HEX_RADIUS_MILES);
    if (!hexCache[key]) {
      void loadHexStream(name, [name], HEX_RESOLUTION, MAX_HEX_RADIUS_MILES, debugHex, false, false);
    }
  };

  const handleToggleCompare = () => {
    if (rankingMode) setRankingMode(false);
    setCompareMode((prev) => {
      if (!prev) {
        setCompareNames(selectedName ? [selectedName, null] : [null, null]);
      } else {
        setCompareNames([null, null]);
      }
      return !prev;
    });
  };

  // Toggle ranking mode
  const handleToggleRanking = () => {
    if (compareMode) setCompareMode(false);
    setRankingMode((prev) => !prev);
  };

  // Ranking row click → exit ranking, select university, auto-generate report
  const handleRankingSelect = (name: string) => {
    setSelectedName(name);
    setSearchQuery(name);
    const known = findKnownCoords(name, dynamicUnis, scoreCache);
    if (known) setSelectedCoords(known);
    if (!scoreCache[name]) {
      enqueueReport(name);
    }
  };
  const handleClearCompare = () => {
    setCompareNames([null, null]);
    setSelectedName(null);
    setSelectedCoords(null);
    setSearchQuery("");
  };

  const handleZoomOutMap = () => {
    setSelectedName(null);
    setSelectedCoords(null);
  };

  const compareGuide = compareMode
    ? compareNames[0] === null
      ? "Click a pin or search for first university…"
      : compareNames[1] === null
      ? "Now click or search for the second…"
      : undefined
    : undefined;

  // Derive queue slices for SidePanel
  const activeJob = reportQueue.find(j => j.status === "running") ?? null;
  const queuedJobs = reportQueue.filter(j => j.status === "queued");
  const doneJobs = reportQueue.filter(j => j.status === "done");
  const errorJobs = reportQueue.filter(j => j.status === "error");

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-zinc-950 text-zinc-50">
      <SearchBar
        query={searchQuery}
        onChange={setSearchQuery}
        onSubmit={handleSearch}
        onSelectUniversity={handleSelectUniversity}
        extraUniversities={Object.values(dynamicUnis)}
        disabled={false}
        compareMode={compareMode}
        compareLoading={!!loadingName}
        onToggleCompare={handleToggleCompare}
        compareGuide={compareGuide}
        rankingMode={rankingMode}
        onToggleRanking={handleToggleRanking}
        onHome={handleHome}
      />
      <main className="flex flex-1 min-h-0">
        {rankingMode ? (
          <RankingView
            universities={nationalUniversities}
            onSelect={handleRankingSelect}
            onExitRanking={() => setRankingMode(false)}
          />
        ) : (
          <>
            <APIProvider apiKey={MAPS_API_KEY}>
              <MapView
                selectedName={selectedName}
                selectedCoords={selectedCoords}
                scoreCache={scoreCache}
                dynamicUnis={dynamicUnis}
                activeHexData={activeHexData}
                hexRadiusMiles={hexRadiusMiles}
                onHexRadiusChange={setHexRadiusMiles}
                onPinClick={handleSelectUniversity}
                onZoomOut={handleZoomOutMap}
                onZoomChange={setMapZoom}
                onHoverPrefetch={handleHoverPrefetch}
                isHexLoading={selectedName ? hexLoadingNames.has(selectedName) : false}
                onViewAllParcels={(parcels, label) => setActiveLandParcels({ parcels, label })}
                onHexSelect={setSelectedHexProps}
                focusHexId={focusHexId}
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
                  queuedNames={queuedJobs.map(j => j.name)}
                  activeLogs={activeJob?.logs ?? []}
                />
              </aside>
            ) : (
              <SidePanel
                selectedName={selectedName}
                activeScore={activeScore}
                activeJob={activeJob}
                queuedJobs={queuedJobs}
                doneJobs={doneJobs}
                errorJobs={errorJobs}
                onRecompute={handleRecompute}
                onGenerateReport={handleGenerateReport}
                onDismissJob={dismissJob}
                onViewReport={handleViewReport}
                onSelectNearest={handleSelectUniversity}
                extraUniversities={Object.values(dynamicUnis)}
                hexLoadingName={hexLoadingNames.size > 0 ? [...hexLoadingNames][0] : null}
                hexJustLoaded={hexJustLoaded}
                activeLandParcels={activeLandParcels}
                onDismissLandParcels={() => setActiveLandParcels(null)}
                selectedHexProps={selectedHexProps}
                onUniversityScored={handleUniversityScored}
                onExportJob={handleExportJob}
                onSelectHex={(h3Id) => setFocusHexId(h3Id)}
              />
            )}
          </>
        )}
      </main>
    </div>
  );
}

export default App;
