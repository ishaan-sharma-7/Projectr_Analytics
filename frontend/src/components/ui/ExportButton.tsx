import { useState, useRef, useEffect } from "react";
import { ChevronDown, Loader2 } from "lucide-react";
import type { HousingPressureScore } from "../../lib/api";
import {
  exportToPDF,
  exportToDocx,
  exportToJSON,
} from "../../lib/exportReport";

interface ExportButtonProps {
  score: HousingPressureScore;
}

export function ExportButton({ score }: ExportButtonProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState<"pdf" | "docx" | null>(null);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [open]);

  async function handle(format: "pdf" | "docx" | "json") {
    setOpen(false);
    if (format === "json") {
      exportToJSON(score);
      return;
    }
    setLoading(format);
    try {
      if (format === "pdf") await exportToPDF(score);
      else await exportToDocx(score);
    } finally {
      setLoading(null);
    }
  }

  const isLoading = loading !== null;

  return (
    <div ref={ref} className="relative shrink-0">
      <button
        onClick={() => !isLoading && setOpen((v) => !v)}
        disabled={isLoading}
        className="btn-ql btn-ql-secondary disabled:opacity-50"
      >
        {isLoading ? "Exporting..." : "Export"}
        <span className="btn-icon">
          {isLoading ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <ChevronDown
              className={`w-3 h-3 transition-transform ${open ? "rotate-180" : ""}`}
            />
          )}
        </span>
      </button>

      {open && (
        <div
          className="absolute right-0 top-full mt-1.5 w-44 rounded-xl shadow-2xl z-50 overflow-hidden"
          style={{
            background: "var(--surface-2)",
            border: "1px solid var(--border)",
          }}
        >
          {(
            [
              { key: "pdf", label: "Download PDF", sub: "Text-searchable report" },
              { key: "docx", label: "Download Word", sub: ".docx, fully editable" },
              { key: "json", label: "Download JSON", sub: "Raw data export" },
            ] as const
          ).map(({ key, label, sub }) => (
            <button
              key={key}
              onClick={() => handle(key)}
              className="w-full text-left px-4 py-3 transition-colors"
              style={{ borderBottom: "1px solid var(--border)" }}
              onMouseEnter={(e) =>
                (e.currentTarget.style.background = "rgba(255,255,255,0.04)")
              }
              onMouseLeave={(e) =>
                (e.currentTarget.style.background = "transparent")
              }
            >
              <p
                className="text-xs font-medium"
                style={{ color: "var(--text)" }}
              >
                {label}
              </p>
              <p className="text-[10px] mt-0.5" style={{ color: "var(--text-3)" }}>
                {sub}
              </p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
