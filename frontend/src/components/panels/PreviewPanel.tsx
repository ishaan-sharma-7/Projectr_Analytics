import { Zap, MapPin } from "lucide-react";
import { UNIVERSITIES } from "../../lib/universityList";

// Derive 2–3 letter initials from a university name
function getInitials(name: string): string {
  const skip = new Set(["of", "the", "at", "and", "for", "in", "a"]);
  const words = name.split(/[\s\-&]+/).filter((w) => w.length > 0 && !skip.has(w.toLowerCase()));
  return words
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

// Deterministic accent color from name
function nameToColor(name: string): string {
  const palette = [
    "#3b82f6", // blue
    "#8b5cf6", // violet
    "#f59e0b", // amber
    "#10b981", // emerald
    "#f43f5e", // rose
    "#06b6d4", // cyan
    "#84cc16", // lime
    "#f97316", // orange
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = (hash * 31 + name.charCodeAt(i)) & 0x7fffffff;
  }
  return palette[hash % palette.length];
}

interface PreviewPanelProps {
  name: string;
  onGenerateReport: (name: string) => void;
}

export function PreviewPanel({ name, onGenerateReport }: PreviewPanelProps) {
  const uni = UNIVERSITIES.find((u) => u.name === name);
  const initials = getInitials(name);
  const color = nameToColor(name);

  return (
    <div className="flex flex-col h-full">
      {/* Hero section */}
      <div className="flex flex-col items-center justify-center px-8 py-12 border-b border-zinc-800 text-center">
        {/* Initials avatar */}
        <div
          className="w-20 h-20 rounded-2xl flex items-center justify-center mb-5 shadow-lg"
          style={{ background: `${color}20`, border: `1.5px solid ${color}40` }}
        >
          <span
            className="text-2xl font-black tracking-tight"
            style={{ color }}
          >
            {initials}
          </span>
        </div>

        <h2 className="text-xl font-bold text-zinc-50 leading-snug mb-1">{name}</h2>

        {uni ? (
          <div className="flex items-center gap-1 text-sm text-zinc-400 mt-1">
            <MapPin className="w-3.5 h-3.5 shrink-0" />
            {uni.city}, {uni.state}
          </div>
        ) : (
          <p className="text-sm text-zinc-500 mt-1">United States</p>
        )}
      </div>

      {/* Generate report CTA */}
      <div className="flex flex-col items-center justify-center flex-1 px-8 gap-5">
        <p className="text-sm text-zinc-400 text-center leading-relaxed max-w-xs">
          Run a live housing market analysis — enrollment trends, building permits,
          rent data, and an AI-generated market brief from Gemini.
        </p>

        <button
          onClick={() => onGenerateReport(name)}
          className="flex items-center gap-2.5 px-6 py-3 rounded-xl font-semibold text-sm
                     bg-blue-600 hover:bg-blue-500 text-white transition-colors shadow-lg
                     shadow-blue-600/25 active:scale-95"
        >
          <Zap className="w-4 h-4" />
          Generate Report
        </button>

        <p className="text-xs text-zinc-600 text-center">
          Pulls live data from 5 sources · takes ~15 seconds
        </p>
      </div>
    </div>
  );
}
