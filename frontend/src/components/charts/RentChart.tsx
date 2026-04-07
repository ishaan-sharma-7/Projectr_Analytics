import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
} from "recharts";
import { darkTooltipStyle } from "../../lib/chartTheme";
import type { RentData } from "../../lib/api";

function normalizeRent(data: RentData[]): { year: string; rent: number }[] {
  const byYear = new Map<number, number[]>();
  data.forEach((d) => {
    if (!byYear.has(d.year)) byYear.set(d.year, []);
    byYear.get(d.year)!.push(d.median_rent);
  });
  return Array.from(byYear.entries())
    .sort(([a], [b]) => a - b)
    .map(([year, rents]) => ({
      year: String(year),
      rent: Math.round(rents.reduce((s, r) => s + r, 0) / rents.length),
    }));
}

export function RentChart({ data }: { data: RentData[] }) {
  const chartData = normalizeRent(data);

  return (
    <ResponsiveContainer width="100%" height={120}>
      <AreaChart data={chartData} margin={{ top: 4, right: 8, left: -20, bottom: 0 }}>
        <defs>
          <linearGradient id="rentGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%" stopColor="#f43f5e" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#f43f5e" stopOpacity={0} />
          </linearGradient>
        </defs>
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
          tickFormatter={(v: number) => `$${v}`}
        />
        <Tooltip
          contentStyle={darkTooltipStyle}
          formatter={(v) => [typeof v === "number" ? `$${v.toLocaleString()}` : String(v), "Median Rent"]}
        />
        <Area
          dataKey="rent"
          stroke="#f43f5e"
          strokeWidth={2}
          fill="url(#rentGrad)"
          dot={false}
          activeDot={{ r: 4, fill: "#f43f5e" }}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}
