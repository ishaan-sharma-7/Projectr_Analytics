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
