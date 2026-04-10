import { useRef, useEffect, useState } from "react";
import { Search, X, MapPin, ArrowRight, GitCompareArrows, Trophy, Loader2 } from "lucide-react";
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
  compareLoading?: boolean;
  onToggleCompare?: () => void;
  compareGuide?: string;
  rankingMode?: boolean;
  onToggleRanking?: () => void;
  onHome?: () => void;
}

export function SearchBar({
  query,
  onChange,
  onSubmit,
  onSelectUniversity,
  extraUniversities = [],
  disabled,
  compareMode,
  compareLoading,
  onToggleCompare,
  compareGuide,
  rankingMode,
  onToggleRanking,
  onHome,
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
    <header className="shrink-0 z-10 flex items-center justify-between px-6 py-3 bg-[#080808]/90 backdrop-blur-md border-b border-white/[0.08]">
      {/* Logo — CAMPUS + LENS outline, matches campuslens.html nav */}
      <button
        onClick={onHome}
        className="flex items-center gap-2.5 hover:opacity-70 transition-opacity cursor-pointer shrink-0"
      >
        <img src="/logo.png" alt="CampusLens" className="w-8 h-8 object-contain shrink-0" />
        <h1 className="text-base font-extrabold tracking-[-0.04em] leading-none">
          CAMPUS<span style={{ color: 'transparent', WebkitTextStroke: '1.5px #f0f0f0' }}>LENS</span>
        </h1>
      </button>

      {/* Search form */}
      <form onSubmit={(e) => { setOpen(false); onSubmit(e); }} className="flex-1 max-w-lg mx-8">
        <div ref={containerRef} className="relative">
          <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-zinc-500 pointer-events-none z-10" />

          <input
            ref={inputRef}
            type="text"
            placeholder={compareGuide ?? "Search any US university..."}
            className={`w-full bg-white/[0.04] border text-sm outline-none transition-all disabled:opacity-40 placeholder:text-zinc-600 px-5 py-2.5 pl-11 pr-10 ${
              compareMode ? 'border-blue-500/40 focus:border-blue-400' : 'border-white/[0.1] focus:border-blue-500/60'
            } ${
              open && query.trim().length > 0
                ? "rounded-t-2xl rounded-b-none"
                : "rounded-full"
            }`}
            value={query}
            onChange={(e) => { onChange(e.target.value); setOpen(true); }}
            onFocus={() => { if (query.trim().length > 0) setOpen(true); }}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            autoComplete="off"
          />

          {/* Clear */}
          {query.length > 0 && !disabled && (
            <button
              type="button"
              onClick={() => { onChange(""); setOpen(false); inputRef.current?.focus(); }}
              className="absolute right-4 top-1/2 -translate-y-1/2 text-zinc-600 hover:text-zinc-300 transition-colors z-10"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          )}

          {/* ⌘K hint */}
          {query.length === 0 && (
            <kbd className="absolute right-4 top-1/2 -translate-y-1/2 text-zinc-700 text-[10px] font-mono bg-white/[0.06] rounded px-1.5 py-0.5 pointer-events-none tracking-wide">
              ⌘K
            </kbd>
          )}

          {/* Dropdown */}
          {open && query.trim().length > 0 && (
            <div className="absolute top-full left-0 right-0 bg-[#0d0d0d] border border-white/[0.1] border-t-0 rounded-b-2xl shadow-2xl overflow-hidden z-50">
              {suggestions.map((uni, i) => (
                <button
                  key={`${uni.name}-${uni.city}`}
                  type="button"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => handleSuggestionClick(uni)}
                  onMouseEnter={() => setActiveIdx(i)}
                  className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                    activeIdx === i ? "bg-white/[0.06]" : "hover:bg-white/[0.03]"
                  }`}
                >
                  <MapPin className="w-3 h-3 text-zinc-600 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <HighlightedName name={uni.name} query={query} />
                    <p className="text-[11px] text-zinc-600 mt-0.5 tracking-wide uppercase">{uni.city}, {uni.state}</p>
                  </div>
                  {i === 0 && topIsExact && (
                    <span className="text-[10px] text-zinc-700 ml-1 shrink-0 font-mono">↵</span>
                  )}
                </button>
              ))}

              {suggestions.length > 0 && <div className="h-px bg-white/[0.06] mx-4" />}

              <button
                type="button"
                onMouseDown={(e) => e.preventDefault()}
                onClick={handleLiveSearchClick}
                onMouseEnter={() => setActiveIdx(suggestions.length)}
                className={`w-full flex items-center gap-3 px-4 py-3 text-left transition-colors ${
                  activeIdx === suggestions.length ? "bg-white/[0.06]" : "hover:bg-white/[0.03]"
                }`}
              >
                <div className="w-3 h-3 rounded-full shrink-0 bg-blue-500" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-zinc-300">
                    Search <span className="font-bold text-white">"{query}"</span>
                  </p>
                  <p className="text-[11px] text-zinc-600 mt-0.5 tracking-wide">Live analysis via Gemini</p>
                </div>
                <ArrowRight className="w-3.5 h-3.5 text-zinc-700 shrink-0" />
              </button>
            </div>
          )}
        </div>
      </form>

      {/* Action buttons */}
      <div className="flex items-center gap-2 shrink-0">
        {onToggleRanking && (
          <button
            onClick={onToggleRanking}
            title={rankingMode ? "Exit rankings" : "View market rankings"}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[11px] font-semibold tracking-[0.08em] uppercase transition-all ${
              rankingMode
                ? "text-black shadow-lg"
                : "border border-white/[0.12] text-zinc-400 hover:text-white hover:border-amber-400/50"
            }`}
            style={rankingMode ? { background: '#f59e0b' } : {}}
          >
            <Trophy className="w-3.5 h-3.5" />
            Rankings
          </button>
        )}
        {onToggleCompare && (
          <button
            onClick={onToggleCompare}
            title={compareMode ? "Exit compare mode" : "Compare two universities"}
            className={`flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-[11px] font-semibold tracking-[0.08em] uppercase transition-all ${
              compareMode
                ? "bg-blue-600 text-white shadow-lg shadow-blue-600/20"
                : "border border-white/[0.12] text-zinc-400 hover:text-white hover:border-blue-400/50"
            }`}
          >
            {compareMode && compareLoading
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <GitCompareArrows className="w-3.5 h-3.5" />
            }
            {compareMode ? "Comparing" : "Compare"}
          </button>
        )}
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
