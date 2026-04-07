import { useEffect, useRef } from "react";

interface LogEntry {
  message: string;
  ts: Date;
}

const isHighlight = (msg: string) => /score|complete|summary|gemini/i.test(msg);

export function AgentLogPanel({ logs }: { logs: LogEntry[] }) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs]);

  return (
    <div className="flex-1 flex flex-col p-6">
      <div className="flex items-center gap-3 mb-5">
        <div className="w-5 h-5 border-2 border-blue-500/40 border-t-blue-500 rounded-full animate-spin" />
        <span className="text-sm font-medium text-blue-400">Running market analysis...</span>
      </div>

      <div className="flex-1 bg-zinc-900/60 rounded-xl border border-zinc-800 p-4 font-mono text-xs overflow-y-auto space-y-1.5">
        {logs.map((entry, i) => (
          <div
            key={i}
            className={`flex gap-2 leading-relaxed ${
              isHighlight(entry.message) ? "text-blue-300 font-medium" : "text-zinc-400"
            }`}
          >
            <span className="text-zinc-600 tabular-nums shrink-0">
              {entry.ts.toLocaleTimeString("en", {
                hour12: false,
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
            <span className={isHighlight(entry.message) ? "text-blue-400" : "text-blue-500"}>›</span>
            <span>{entry.message}</span>
          </div>
        ))}
        {logs.length > 0 && (
          <div className="flex items-center gap-1.5 pt-1">
            <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
            <span className="text-zinc-600 text-xs">waiting...</span>
          </div>
        )}
        <div ref={endRef} />
      </div>
    </div>
  );
}
