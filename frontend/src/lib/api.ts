export interface UniversityMeta {
  unitid: number;
  name: string;
  city: string;
  state: string;
  lat: number;
  lon: number;
  enrollment: number;
  url: string | null;
}

export interface EnrollmentTrend {
  year: number;
  total_enrollment: number;
}

export interface PermitData {
  year: number;
  permits: number;
  fips_place: string;
}

export interface RentData {
  city: string;
  state: string;
  year: number;
  month: number | null;
  median_rent: number;
  source: string;
}

export interface MarketDemographics {
  median_household_income: number | null;
  median_home_value: number | null;
  median_gross_rent: number | null;
  median_year_built: number | null;
  vacancy_rate_pct: number | null;
  pct_bachelors_or_higher: number | null;
  pct_renter_occupied: number | null;
  total_housing_units: number | null;
}

export interface HousingCapacity {
  year: number;
  dormitory_capacity: number;
  typical_room_charge: number | null;
  typical_board_charge: number | null;
  beds_per_student: number | null;
}

export interface DisasterRisk {
  window_years: number;
  total_disasters: number;
  weather_disasters: number;
  by_type: Record<string, number>;
  most_recent_year: number | null;
}

export interface InstitutionalStrength {
  ownership: number | null;
  ownership_label: string | null;
  endowment_end: number | null;
  endowment_per_student: number | null;
  pell_grant_rate: number | null;
  admission_rate: number | null;
  retention_rate: number | null;
  strength_score: number | null;
  strength_label: "strong" | "stable" | "watch" | null;
}

export interface ExistingHousingStock {
  radius_miles: number;
  apartment_buildings: number;
  dormitory_buildings: number;
  residential_buildings: number;
  house_buildings: number;
  total_buildings: number;
  apartment_density_per_km2: number;
  saturation_label: "low" | "moderate" | "high";
}

export interface ScoreComponents {
  enrollment_pressure: number;
  permit_gap: number;
  rent_pressure: number;
}

export interface HousingPressureScore {
  university: UniversityMeta;
  score: number;
  components: ScoreComponents;
  enrollment_trend: EnrollmentTrend[];
  permit_history: PermitData[];
  rent_history: RentData[];
  nearby_housing_units: number;
  demographics: MarketDemographics | null;
  housing_capacity: HousingCapacity | null;
  disaster_risk: DisasterRisk | null;
  institutional_strength: InstitutionalStrength | null;
  existing_housing: ExistingHousingStock | null;
  gemini_summary: string | null;
  scored_at: string;
}

export interface UniversityListItem {
  unitid: number;
  name: string;
  city: string;
  state: string;
  lat: number;
  lon: number;
  score: number;
  score_label: "high" | "medium" | "low";
}

const API_BASE = "http://localhost:8000";

export async function fetchUniversities(): Promise<UniversityListItem[]> {
  const res = await fetch(`${API_BASE}/universities`);
  if (!res.ok) throw new Error("Failed to fetch universities");
  return res.json();
}

export async function computeScore(name: string): Promise<HousingPressureScore> {
  const res = await fetch(`${API_BASE}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ university_name: name })
  });
  
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Failed to compute score");
  return data;
}

export async function computeScoreById(unitid: number): Promise<HousingPressureScore> {
  const res = await fetch(`${API_BASE}/score`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ unitid })
  });

  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "Failed to compute score");
  return data;
}

export type StreamEvent =
  | { type: "log"; message: string }
  | { type: "result"; data: HousingPressureScore }
  | { type: "error"; message: string };

export async function* streamScore(name: string): AsyncGenerator<StreamEvent> {
  const res = await fetch(`${API_BASE}/score/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ university_name: name }),
  });

  if (!res.ok || !res.body) throw new Error("Stream request failed");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        try {
          yield JSON.parse(line.slice(6)) as StreamEvent;
        } catch {
          // skip malformed lines
        }
      }
    }
  }
}
