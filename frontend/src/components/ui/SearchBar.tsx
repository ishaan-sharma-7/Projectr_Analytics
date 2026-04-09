import { useRef, useEffect, useState } from "react";
import { Search, X, MapPin, ArrowRight, GitCompareArrows, Trophy } from "lucide-react";
import { UNIVERSITIES } from "../../lib/universityList";
import type { UniversitySuggestion } from "../../lib/universityList";

interface SearchBarProps {
  query: string;
  onChange: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onSelectUniversity: (name: string, coords?: { lat: number; lng: number }) => void;
  extraUniversities?: UniversitySuggestion[];
  disabled?: boolean;
  compareMode?: boolean;
  onToggleCompare?: () => void;
  compareGuide?: string;
  rankingMode?: boolean;
  onToggleRanking?: () => void;
}

export function SearchBar({
  query,
  onChange,
  onSubmit,
  onSelectUniversity,
  extraUniversities = [],
  disabled,
  compareMode,
  onToggleCompare,
  compareGuide,
  rankingMode,
  onToggleRanking,
}: SearchBarProps) {
  // Merge static list + previously searched universities, deduplicated by name
  const staticNames = new Set(UNIVERSITIES.map((u) => u.name));
  const allUniversities = [
    ...UNIVERSITIES,
    ...extraUniversities.filter((e) => !staticNames.has(e.name)),
  ];
  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [activeIdx, setActiveIdx] = useState(-1);

  // Filter combined university list by query
  const suggestions =
    query.trim().length > 0
      ? allUniversities.filter((u) =>
          [u.name, u.city, u.state].some((s) =>
            s.toLowerCase().includes(query.toLowerCase())
          )
        ).slice(0, 5)
      : [];

  // Whether the top suggestion is a strong prefix match (shows ↵ hint)
  const topIsExact =
    suggestions.length > 0 &&
    suggestions[0].name.toLowerCase().startsWith(query.toLowerCase());

  // ⌘K / / shortcut to focus
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        inputRef.current?.select();
      }
      if (e.key === "/" && document.activeElement?.tagName !== "INPUT") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  // Close dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setActiveIdx(-1);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  // Reset active index when suggestions change
  useEffect(() => {
    setActiveIdx(-1);
  }, [suggestions.length]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    const total = suggestions.length + 1; // +1 for "live search" row
    if (!open || total === 0) return;

    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIdx((prev) => (prev + 1) % total);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIdx((prev) => (prev - 1 + total) % total);
    } else if (e.key === "Escape") {
      setOpen(false);
      setActiveIdx(-1);
    } else if (e.key === "Enter" && activeIdx >= 0) {
      e.preventDefault();
      if (activeIdx < suggestions.length) {
        const uni = suggestions[activeIdx];
        onChange(uni.name);
        onSelectUniversity(uni.name, { lat: uni.lat, lng: uni.lon });
        setOpen(false);
        setActiveIdx(-1);
      } else {
        setOpen(false);
        inputRef.current?.form?.requestSubmit();
      }
    }
  };

  const handleSuggestionClick = (uni: UniversitySuggestion) => {
    onChange(uni.name);
    onSelectUniversity(uni.name, { lat: uni.lat, lng: uni.lon });
    setOpen(false);
    setActiveIdx(-1);
  };

  const handleLiveSearchClick = () => {
    setOpen(false);
    inputRef.current?.form?.requestSubmit();
  };

  return (
    <header className="shrink-0 z-10 flex items-center justify-between px-6 py-4 bg-zinc-950/80 backdrop-blur-md border-b border-zinc-800">
      {/* Logo */}
      <div className="flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-blue-600 flex items-center justify-center">
          <span className="font-bold text-lg">C</span>
        </div>
        <h1 className="text-xl font-bold tracking-tight">CampusLens</h1>
      </div>

      {/* Search form */}
      <form onSubmit={(e) => { setOpen(false); onSubmit(e); }} className="flex-1 max-w-md mx-8">
        <div ref={containerRef} className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-zinc-400 pointer-events-none z-10" />

          <input
            ref={inputRef}
            type="text"
            placeholder={compareGuide ?? "Search any US university..."}
            className={`w-full bg-zinc-900 border ${compareMode ? 'border-blue-500/50' : 'border-zinc-700'} focus:border-blue-500 px-5 py-2.5 pl-11 pr-10 outline-none text-sm transition-colors disabled:opacity-50 ${
              open && query.trim().length > 0
                ? "rounded-t-2xl rounded-b-none border-b-zinc-800"
                : "rounded-full"
            }`}
            value={query}
            onChange={(e) => { onChange(e.target.value); setOpen(true); }}
            onFocus={() => { if (query.trim().length > 0) setOpen(true); }}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            autoComplete="off"
          />

          {/* Clear button */}
          {query.length > 0 && !disabled && (
            <button
              type="button"
              onClick={() => { onChange(""); setOpen(false); inputRef.current?.focus(); }}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-zinc-500 hover:text-zinc-300 transition-colors z-10"
            >
              <X className="w-4 h-4" />
            </button>
          )}

          {/* ⌘K hint */}
          {query.length === 0 && (
            <kbd className="absolute right-4 top-1/2 -translate-y-1/2 text-zinc-600 text-xs font-mono bg-zinc-800 rounded px-1.5 py-0.5 pointer-events-none">
              ⌘K
            </kbd>
          )}

          {/* Dropdown */}
          {open && query.trim().length > 0 && (
            <div className="absolute top-full left-0 right-0 bg-zinc-900 border border-zinc-700 border-t-zinc-800 rounded-b-2xl shadow-2xl overflow-hidden z-50">

              {/* Static list suggestions */}
              {suggestions.map((uni, i) => (
                <button
                  key={`${uni.name}-${uni.city}`}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => handleSuggestionClick(uni)}
                  onMouseEnter={() => setActiveIdx(i)}
                  className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                    activeIdx === i ? "bg-zinc-800" : "hover:bg-zinc-800/60"
                  }`}
                >
                  <MapPin className="w-3.5 h-3.5 text-zinc-500 shrink-0" />

                  <div className="flex-1 min-w-0">
                    <HighlightedName name={uni.name} query={query} />
                    <p className="text-xs text-zinc-500 mt-0.5">
                      {uni.city}, {uni.state}
                    </p>
                  </div>

                  {i === 0 && topIsExact && (
                    <span className="text-xs text-zinc-600 ml-1 shrink-0">↵</span>
                  )}
                </button>
              ))}

              {/* Divider */}
              {suggestions.length > 0 && (
                <div className="h-px bg-zinc-800 mx-4" />
              )}

              {/* Live search fallback row */}
              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={handleLiveSearchClick}
                onMouseEnter={() => setActiveIdx(suggestions.length)}
                className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                  activeIdx === suggestions.length ? "bg-zinc-800" : "hover:bg-zinc-800/60"
                }`}
              >
                <div className="w-3.5 h-3.5 rounded-full shrink-0 bg-blue-500" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-zinc-300">
                    Search for{" "}
                    <span className="font-semibold text-white">"{query}"</span>
                  </p>
                  <p className="text-xs text-zinc-500 mt-0.5">Live analysis via Gemini</p>
                </div>
                <ArrowRight className="w-4 h-4 text-zinc-600 shrink-0" />
              </button>
            </div>
          )}
        </div>
      </form>

      <div className="flex items-center gap-2">
        {onToggleRanking && (
          <button
            onClick={onToggleRanking}
            title={rankingMode ? "Exit rankings" : "View market rankings"}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              rankingMode
                ? "bg-amber-500 text-black shadow-lg shadow-amber-500/25"
                : "bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-white hover:border-amber-500"
            }`}
          >
            <Trophy className="w-3.5 h-3.5" />
            Rankings
          </button>
        )}
        {onToggleCompare && (
          <button
            onClick={onToggleCompare}
            title={compareMode ? "Exit compare mode" : "Compare two universities"}
            className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              compareMode
                ? "bg-blue-600 text-white shadow-lg shadow-blue-600/25"
                : "bg-zinc-800 border border-zinc-700 text-zinc-400 hover:text-white hover:border-blue-500"
            }`}
          >
            <GitCompareArrows className="w-3.5 h-3.5" />
            {compareMode ? "Comparing" : "Compare"}
          </button>
        )}
        <span className="text-sm text-zinc-400 font-medium">vt-2026</span>
      </div>
    </header>
  );
}

function HighlightedName({ name, query }: { name: string; query: string }) {
  const idx = name.toLowerCase().indexOf(query.toLowerCase());
  if (idx === -1) {
    return <p className="text-sm text-zinc-200 truncate">{name}</p>;
  }
  return (
    <p className="text-sm text-zinc-200 truncate">
      {name.slice(0, idx)}
      <span className="text-white font-semibold">{name.slice(idx, idx + query.length)}</span>
      {name.slice(idx + query.length)}
    </p>
  );
}
