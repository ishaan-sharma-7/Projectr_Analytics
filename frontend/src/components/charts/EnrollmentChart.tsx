import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { darkTooltipStyle } from "../../lib/chartTheme";
import type { EnrollmentTrend } from "../../lib/api";

export function EnrollmentChart({ data }: { data: EnrollmentTrend[] }) {
  const chartData = data.map((d) => ({
    year: String(d.year),
    enrollment: d.total_enrollment,
  }));

  return (
    <ResponsiveContainer width="100%" height={120}>
      <LineChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
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
          tickFormatter={(v: number) => `${(v / 1000).toFixed(0)}k`}
        />
        <Tooltip
          contentStyle={darkTooltipStyle}
          formatter={(v) => [typeof v === "number" ? v.toLocaleString() : String(v), "Enrollment"]}
        />
        <Line
          dataKey="enrollment"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
          activeDot={{ r: 4, fill: "#3b82f6" }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
