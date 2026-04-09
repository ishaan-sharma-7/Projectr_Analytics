// "high" pressure score = good investment opportunity → green.
// "low" = saturated/limited → red. The keys stay the same so cached scores
// continue to resolve.
const GAUGE_COLORS = {
  high: "#22c55e",
  medium: "#f59e0b",
  low: "#ef4444",
} as const;

interface ScoreGaugeProps {
  score: number;
  label: "high" | "medium" | "low";
}

export function ScoreGauge({ score, label }: ScoreGaugeProps) {
  const r = 52;
  const cx = 60;
  const cy = 68;
  const C = 2 * Math.PI * r;
  const arcLen = C / 2; // semicircle ≈ 163.4
  const fill = (score / 100) * arcLen;
  const color = GAUGE_COLORS[label];

  return (
    <div className="relative flex flex-col items-center">
      <svg viewBox="0 0 120 72" className="w-44 h-24 overflow-visible">
        {/* Track */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke="#27272a"
          strokeWidth={10}
          strokeDasharray={`${arcLen} ${C}`}
          strokeLinecap="round"
          transform={`rotate(-180 ${cx} ${cy})`}
        />
        {/* Fill — CSS transition animates the arc on score change */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={10}
          strokeDasharray={`${fill} ${C}`}
          strokeLinecap="round"
          transform={`rotate(-180 ${cx} ${cy})`}
          style={{ transition: "stroke-dasharray 0.8s cubic-bezier(0.4,0,0.2,1)" }}
        />
      </svg>
      <div className="absolute bottom-0 flex flex-col items-center pointer-events-none">
        <span className="text-4xl font-black tabular-nums tracking-tighter" style={{ color }}>
          {score.toFixed(1)}
        </span>
        <span className="text-xs text-zinc-500 -mt-1">/ 100</span>
      </div>
    </div>
  );
}
