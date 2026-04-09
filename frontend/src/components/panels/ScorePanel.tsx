import { TrendingUp, Building2, DollarSign, MapPin, RefreshCw, BedDouble, Home, CloudRain, GraduationCap, Warehouse } from "lucide-react";
import { ScoreGauge } from "../ui/ScoreGauge";
import { EnrollmentChart } from "../charts/EnrollmentChart";
import { RentChart } from "../charts/RentChart";
import { PermitChart } from "../charts/PermitChart";
import type { HousingPressureScore } from "../../lib/api";

// "high" pressure score = good developer opportunity (undersupplied market).
// We keep the internal label keys (high/medium/low) so cached scores still
// resolve, but flip the colors and copy so the UI reads as opportunity rather
// than pressure.
const LABEL_COLORS = {
  high: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  medium: "text-amber-400 bg-amber-500/10 border-amber-500/20",
  low: "text-red-400 bg-red-500/10 border-red-500/20",
} as const;

const LABEL_TEXT = {
  high: "Strong Opportunity",
  medium: "Emerging Market",
  low: "Saturated Market",
} as const;

function getLabel(score: number): "high" | "medium" | "low" {
  return score >= 70 ? "high" : score >= 40 ? "medium" : "low";
}

function ChartSection({
  title,
  accent,
  children,
}: {
  title: string;
  accent: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-zinc-900/50 rounded-xl p-4 border border-zinc-800/50">
      <p className={`text-xs font-semibold uppercase tracking-wider mb-3 ${accent}`}>{title}</p>
      {children}
    </div>
  );
}

export function ScorePanel({ score, onRecompute }: { score: HousingPressureScore; onRecompute?: () => void }) {
  const label = getLabel(score.score);

  const latestEnrollment = score.enrollment_trend.at(-1)?.total_enrollment;
  const earliestEnrollment = score.enrollment_trend.at(0)?.total_enrollment;
  const enrollmentChange =
    latestEnrollment && earliestEnrollment
      ? (((latestEnrollment - earliestEnrollment) / earliestEnrollment) * 100).toFixed(1)
      : null;

  const latestRent = score.rent_history.at(-1)?.median_rent;
  const earliestRent = score.rent_history.at(0)?.median_rent;
  const rentChange =
    latestRent && earliestRent
      ? (((latestRent - earliestRent) / earliestRent) * 100).toFixed(1)
      : null;

  const totalPermits = score.permit_history.reduce((s, p) => s + p.permits, 0);

  return (
    <div className="p-6 space-y-5">
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold text-blue-400 mb-1 tracking-widest uppercase">
            {score.university.city}, {score.university.state}
          </p>
          <h2 className="text-xl font-bold leading-tight">{score.university.name}</h2>
          {score.university.enrollment && (
            <p className="text-xs text-zinc-500 mt-1">
              {score.university.enrollment.toLocaleString()} students enrolled
            </p>
          )}
        </div>
        {onRecompute && (
          <button
            onClick={onRecompute}
            title="Re-run live analysis"
            className="shrink-0 mt-1 flex items-center gap-1.5 px-3 py-1.5 rounded-lg
                       bg-zinc-800 border border-zinc-700 hover:border-blue-500
                       text-zinc-400 hover:text-white text-xs font-medium transition-all"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Recompute
          </button>
        )}
      </div>

      {/* Score card */}
      <div className="bg-zinc-900 rounded-2xl p-5 border border-zinc-800 relative overflow-hidden">
        <div className="absolute top-0 right-0 w-40 h-40 bg-blue-500/5 blur-3xl rounded-full translate-x-1/2 -translate-y-1/2" />
        <div className="flex items-start justify-between mb-4">
          <h3 className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
            Housing Pressure Score
          </h3>
          <span
            className={`text-xs font-bold px-2.5 py-1 rounded-full border ${LABEL_COLORS[label]}`}
          >
            {LABEL_TEXT[label]}
          </span>
        </div>

        <div className="flex justify-center">
          <ScoreGauge score={score.score} label={label} />
        </div>
      </div>

      {/* Gemini summary */}
      {score.gemini_summary && (
        <div className="bg-zinc-900/50 rounded-xl p-5 border border-zinc-800/50">
          <div className="flex items-center gap-2 mb-3">
            <div className="w-4 h-4 rounded-full bg-blue-500/20 flex items-center justify-center">
              <div className="w-2 h-2 rounded-full bg-blue-400" />
            </div>
            <span className="text-xs font-semibold text-blue-400 uppercase tracking-wider">
              Gemini Market Brief
            </span>
          </div>
          <p className="text-sm text-zinc-300 leading-relaxed">{score.gemini_summary}</p>
        </div>
      )}

      {/* 2×2 stats grid */}
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <TrendingUp className="w-3.5 h-3.5 text-blue-400" />
            <p className="text-xs text-zinc-500 font-medium">Enrollment</p>
          </div>
          <p className="text-lg font-bold tabular-nums">
            {latestEnrollment?.toLocaleString() ?? "N/A"}
          </p>
          {enrollmentChange && (
            <p
              className={`text-xs mt-0.5 ${
                parseFloat(enrollmentChange) >= 0 ? "text-green-400" : "text-red-400"
              }`}
            >
              {parseFloat(enrollmentChange) >= 0 ? "+" : ""}
              {enrollmentChange}% over period
            </p>
          )}
        </div>

        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <DollarSign className="w-3.5 h-3.5 text-rose-400" />
            <p className="text-xs text-zinc-500 font-medium">Median Rent</p>
          </div>
          <p className="text-lg font-bold tabular-nums">
            {latestRent ? `$${latestRent.toLocaleString()}` : "N/A"}
          </p>
          {rentChange && (
            <p
              className={`text-xs mt-0.5 ${
                parseFloat(rentChange) >= 0 ? "text-red-400" : "text-green-400"
              }`}
            >
              {parseFloat(rentChange) >= 0 ? "+" : ""}
              {rentChange}% over period
            </p>
          )}
        </div>

        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <Building2 className="w-3.5 h-3.5 text-purple-400" />
            <p className="text-xs text-zinc-500 font-medium">Permits Filed</p>
          </div>
          <p className="text-lg font-bold tabular-nums">
            {totalPermits > 0 ? totalPermits.toLocaleString() : "N/A"}
          </p>
          <p className="text-xs text-zinc-600 mt-0.5">residential units (5yr)</p>
        </div>

        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <MapPin className="w-3.5 h-3.5 text-zinc-400" />
            <p className="text-xs text-zinc-500 font-medium">Housing Stock</p>
          </div>
          <p className="text-lg font-bold tabular-nums">
            {score.nearby_housing_units && score.nearby_housing_units > 0
              ? score.nearby_housing_units.toLocaleString()
              : "N/A"}
          </p>
          <p className="text-xs text-zinc-600 mt-0.5">county total (ACS)</p>
        </div>

        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <BedDouble className="w-3.5 h-3.5 text-emerald-400" />
            <p className="text-xs text-zinc-500 font-medium">Beds / Student</p>
          </div>
          {score.housing_capacity?.beds_per_student != null ? (
            <p
              className={`text-lg font-bold tabular-nums ${
                score.housing_capacity.beds_per_student < 0.25
                  ? "text-red-400"
                  : score.housing_capacity.beds_per_student > 0.75
                  ? "text-emerald-400"
                  : "text-zinc-50"
              }`}
            >
              {score.housing_capacity.beds_per_student.toFixed(2)}
            </p>
          ) : (
            <p className="text-lg font-bold text-zinc-600">N/A</p>
          )}
          <p className="text-xs text-zinc-600 mt-0.5">on-campus dorm ratio</p>
        </div>

        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <Home className="w-3.5 h-3.5 text-amber-400" />
            <p className="text-xs text-zinc-500 font-medium">Vacancy Rate</p>
          </div>
          {score.demographics?.vacancy_rate_pct != null ? (
            <p
              className={`text-lg font-bold tabular-nums ${
                score.demographics.vacancy_rate_pct < 3.0
                  ? "text-red-400"
                  : score.demographics.vacancy_rate_pct > 10.0
                  ? "text-emerald-400"
                  : "text-zinc-50"
              }`}
            >
              {score.demographics.vacancy_rate_pct.toFixed(1)}%
            </p>
          ) : (
            <p className="text-lg font-bold text-zinc-600">N/A</p>
          )}
          <p className="text-xs text-zinc-600 mt-0.5">renter market (ACS)</p>
        </div>

        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50">
          <div className="flex items-center gap-1.5 mb-2">
            <CloudRain className="w-3.5 h-3.5 text-sky-400" />
            <p className="text-xs text-zinc-500 font-medium">Weather Disasters</p>
          </div>
          {score.disaster_risk?.weather_disasters != null ? (
            <p
              className={`text-lg font-bold tabular-nums ${
                score.disaster_risk.weather_disasters >= 10
                  ? "text-red-400"
                  : "text-zinc-50"
              }`}
            >
              {score.disaster_risk.weather_disasters}
            </p>
          ) : (
            <p className="text-lg font-bold text-zinc-600">N/A</p>
          )}
          <p className="text-xs text-zinc-600 mt-0.5">
            FEMA, last {score.disaster_risk?.window_years ?? 10}yr
          </p>
        </div>

        {/* Institutional Strength — Scorecard finance signal */}
        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50 col-span-2">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <GraduationCap className="w-3.5 h-3.5 text-indigo-400" />
              <p className="text-xs text-zinc-500 font-medium">Institutional Strength</p>
            </div>
            {score.institutional_strength?.strength_label && (
              <span
                className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                  score.institutional_strength.strength_label === "strong"
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                    : score.institutional_strength.strength_label === "watch"
                    ? "text-red-400 bg-red-500/10 border-red-500/20"
                    : "text-zinc-300 bg-zinc-500/10 border-zinc-500/20"
                }`}
              >
                {score.institutional_strength.strength_label}
              </span>
            )}
          </div>

          {score.institutional_strength ? (
            <>
              {score.institutional_strength.strength_score != null && (
                <p className="text-lg font-bold tabular-nums">
                  {score.institutional_strength.strength_score.toFixed(0)}
                  <span className="text-xs text-zinc-500 font-normal">/100</span>
                </p>
              )}
              <div className="grid grid-cols-3 gap-2 mt-2 text-xs">
                <div>
                  <p className="text-zinc-600">Retention</p>
                  <p className="text-zinc-300 font-semibold tabular-nums">
                    {score.institutional_strength.retention_rate != null
                      ? `${(score.institutional_strength.retention_rate * 100).toFixed(0)}%`
                      : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-zinc-600">Endow/Stu</p>
                  <p className="text-zinc-300 font-semibold tabular-nums">
                    {score.institutional_strength.endowment_per_student
                      ? score.institutional_strength.endowment_per_student >= 1000
                        ? `$${(score.institutional_strength.endowment_per_student / 1000).toFixed(0)}k`
                        : `$${score.institutional_strength.endowment_per_student}`
                      : "—"}
                  </p>
                </div>
                <div>
                  <p className="text-zinc-600">Admit</p>
                  <p className="text-zinc-300 font-semibold tabular-nums">
                    {score.institutional_strength.admission_rate != null
                      ? `${(score.institutional_strength.admission_rate * 100).toFixed(0)}%`
                      : "—"}
                  </p>
                </div>
              </div>
              {score.institutional_strength.ownership_label && (
                <p className="text-xs text-zinc-600 mt-2 capitalize">
                  {score.institutional_strength.ownership_label}
                </p>
              )}
            </>
          ) : (
            <p className="text-lg font-bold text-zinc-600">N/A</p>
          )}
        </div>

        {/* Existing Housing Stock — OSM building footprint within 1.5mi */}
        <div className="bg-zinc-900/50 p-4 rounded-xl border border-zinc-800/50 col-span-2">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1.5">
              <Warehouse className="w-3.5 h-3.5 text-orange-400" />
              <p className="text-xs text-zinc-500 font-medium">Existing Housing Stock</p>
            </div>
            {score.existing_housing?.saturation_label && (
              <span
                className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                  score.existing_housing.saturation_label === "low"
                    ? "text-emerald-400 bg-emerald-500/10 border-emerald-500/20"
                    : score.existing_housing.saturation_label === "high"
                    ? "text-red-400 bg-red-500/10 border-red-500/20"
                    : "text-amber-400 bg-amber-500/10 border-amber-500/20"
                }`}
              >
                {score.existing_housing.saturation_label} saturation
              </span>
            )}
          </div>

          {score.existing_housing ? (
            <>
              <div className="grid grid-cols-3 gap-2 mt-1 text-xs">
                <div>
                  <p className="text-zinc-600">Apartments</p>
                  <p className="text-zinc-100 font-bold tabular-nums text-base">
                    {score.existing_housing.apartment_buildings.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-zinc-600">Dormitories</p>
                  <p className="text-zinc-100 font-bold tabular-nums text-base">
                    {score.existing_housing.dormitory_buildings.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-zinc-600">Houses</p>
                  <p className="text-zinc-100 font-bold tabular-nums text-base">
                    {score.existing_housing.house_buildings.toLocaleString()}
                  </p>
                </div>
              </div>
              <p className="text-xs text-zinc-600 mt-2">
                {score.existing_housing.apartment_density_per_km2.toFixed(1)} multifamily / km²
                · {score.existing_housing.radius_miles}mi radius
              </p>
            </>
          ) : (
            <p className="text-lg font-bold text-zinc-600">N/A</p>
          )}
        </div>
      </div>

      {/* Trend charts */}
      {score.enrollment_trend.length > 1 && (
        <ChartSection title="Enrollment Trend" accent="text-blue-400">
          <EnrollmentChart data={score.enrollment_trend} />
        </ChartSection>
      )}

      {score.rent_history.length > 1 && (
        <ChartSection title="Median Rent" accent="text-rose-400">
          <RentChart data={score.rent_history} />
        </ChartSection>
      )}

      {score.permit_history.length > 1 && (
        <ChartSection title="Building Permits (Annual)" accent="text-purple-400">
          <PermitChart data={score.permit_history} />
        </ChartSection>
      )}

      {/* Timestamp */}
      {score.scored_at && (
        <p className="text-xs text-zinc-700 text-center pb-2">
          Scored {new Date(score.scored_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}
