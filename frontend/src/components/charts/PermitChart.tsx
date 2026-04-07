import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { darkTooltipStyle } from "../../lib/chartTheme";
import type { PermitData } from "../../lib/api";

export function PermitChart({ data }: { data: PermitData[] }) {
  const chartData = data.map((d) => ({ year: String(d.year), permits: d.permits }));

  return (
    <ResponsiveContainer width="100%" height={100}>
      <BarChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#27272a" vertical={false} />
        <XAxis
          dataKey="year"
          tick={{ fill: "#71717a", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: "#71717a", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          width={52}
        />
        <Tooltip
          contentStyle={darkTooltipStyle}
          formatter={(v) => [typeof v === "number" ? v.toLocaleString() : String(v), "Units Permitted"]}
        />
        <Bar dataKey="permits" fill="#a855f7" radius={[3, 3, 0, 0]} maxBarSize={24} />
      </BarChart>
    </ResponsiveContainer>
  );
}
