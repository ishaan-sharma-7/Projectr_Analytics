import { useState } from "react";
import { Zap, MapPin } from "lucide-react";
import { UNIVERSITIES } from "../../lib/universityList";

function getInitials(name: string): string {
  const skip = new Set(["of", "the", "at", "and", "for", "in", "a"]);
  const words = name.split(/[\s\-&]+/).filter((w) => w.length > 0 && !skip.has(w.toLowerCase()));
  return words
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

function nameToColor(name: string): string {
  const palette = ["#3b82f6", "#8b5cf6", "#f59e0b", "#10b981", "#f43f5e", "#06b6d4", "#84cc16", "#f97316"];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) & 0x7fffffff;
  return palette[hash % palette.length];
}

// Try sources in order: Clearbit (high-quality logos) → Google favicon (always works) → initials
function UniversityLogo({ name, domain }: { name: string; domain?: string }) {
  const [srcIndex, setSrcIndex] = useState(0);
  const color = nameToColor(name);

  const sources = domain
    ? [
        `https://logo.clearbit.com/${domain}`,
        `https://www.google.com/s2/favicons?domain=${domain}&sz=128`,
      ]
    : [];

  const currentSrc = sources[srcIndex];

  if (currentSrc) {
    return (
      <div className="w-20 h-20 rounded-2xl bg-zinc-800 border border-zinc-700 flex items-center justify-center shadow-lg overflow-hidden">
        <img
          src={currentSrc}
          alt={`${name} logo`}
          className="w-14 h-14 object-contain"
          onError={() => setSrcIndex((i) => i + 1)}
        />
      </div>
    );
  }

  // All sources exhausted — initials avatar
  return (
    <div
      className="w-20 h-20 rounded-2xl flex items-center justify-center shadow-lg"
      style={{ background: `${color}20`, border: `1.5px solid ${color}40` }}
    >
      <span className="text-2xl font-black tracking-tight" style={{ color }}>
        {getInitials(name)}
      </span>
    </div>
  );
}

interface PreviewPanelProps {
  name: string;
  onGenerateReport: (name: string) => void;
}

export function PreviewPanel({ name, onGenerateReport }: PreviewPanelProps) {
  const uni = UNIVERSITIES.find((u) => u.name === name);

  return (
    <div className="flex flex-col h-full" style={{ borderLeft: "1px solid rgba(240,240,240,0.08)" }}>
      {/* Header eyebrow */}
      <div className="px-7 pt-7 pb-5" style={{ borderBottom: "1px solid rgba(240,240,240,0.08)" }}>
        <p className="text-[10px] font-semibold tracking-[0.15em] uppercase mb-4" style={{ color: "rgba(240,240,240,0.3)" }}>
          University Profile
        </p>

        {/* Logo + name editorial block */}
        <div className="flex items-start gap-4">
          <UniversityLogo name={name} domain={uni?.domain} />
          <div className="flex-1 min-w-0 pt-1">
            <h2
              className="font-extrabold tracking-[-0.03em] leading-[0.95] break-words"
              style={{ fontSize: "clamp(1.4rem, 2.2vw, 2rem)" }}
            >
              {name}
            </h2>
            {uni ? (
              <div className="flex items-center gap-1 mt-2">
                <MapPin className="w-3 h-3 shrink-0" style={{ color: "rgba(240,240,240,0.4)" }} />
                <p className="text-[11px] tracking-[0.1em] uppercase font-medium" style={{ color: "rgba(240,240,240,0.4)" }}>
                  {uni.city}, {uni.state}
                </p>
              </div>
            ) : (
              <p className="text-[11px] tracking-[0.1em] uppercase font-medium mt-2" style={{ color: "rgba(240,240,240,0.3)" }}>
                United States
              </p>
            )}
          </div>
        </div>
      </div>

      {/* CTA section */}
      <div className="flex flex-col flex-1 px-7 py-7 justify-between">
        <p className="text-sm leading-relaxed font-light" style={{ color: "rgba(240,240,240,0.45)", maxWidth: "260px" }}>
          Run a live housing market analysis — enrollment trends, building permits, rent data, and an AI-generated brief from Gemini.
        </p>

        <div>
          <button
            onClick={() => onGenerateReport(name)}
            className="w-full flex items-center justify-center gap-2.5 py-3 rounded-full font-bold text-sm tracking-[-0.01em] transition-all active:scale-95 bg-blue-600 hover:bg-blue-500 text-white shadow-lg shadow-blue-600/20"
          >
            <Zap className="w-4 h-4" />
            Generate Report
          </button>

          <div className="h-px my-5" style={{ background: "rgba(240,240,240,0.08)" }} />

          <p className="text-[10px] tracking-[0.1em] uppercase font-medium text-center" style={{ color: "rgba(240,240,240,0.28)" }}>
            5 live sources · ~15 seconds
          </p>
        </div>
      </div>
    </div>
  );
}
