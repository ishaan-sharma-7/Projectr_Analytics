// ── Core domain types ─────────────────────────────────────────────────────────

export type ParentEntity =
  | 'INVITATION_HOMES'
  | 'AMH'
  | 'PROGRESS'
  | 'TRICON'
  | 'BLACKROCK'
  | 'FIRSTKEY'
  | 'MAIN_STREET'
  | 'OTHER';

export type PipelineStage = 'ingest' | 'resolve' | 'geocode' | 'normalize' | 'concentration';

export type PipelineStatus = 'pending' | 'running' | 'complete' | 'failed';

export type MapAction = 'highlight_tracts' | 'filter_properties' | 'zoom_to';

export type ActiveLayer =
  | 'heatmap'
  | 'concentration'
  | 'rent_change'
  | 'home_price'
  | 'eviction_rate'
  | 'demographic_shift'
  | 'permit_activity'
  | 'individual_properties';

// ── Data Transfer Objects (API response shapes) ────────────────────────────────

export interface PropertyDTO {
  id: string;
  propertyAddress: string;
  mailingAddress: string | null;
  ownerName: string;
  matchReason: string;
  parentEntity: ParentEntity;
  subsidiaryChain: string[];
  confidenceScore: number;
  lat: number | null;
  lng: number | null;
  fipsTract: string | null;
  zipCode: string | null;
  acquisitionYear: number | null;
  purchasePrice: number | null;
  city: string;
  state: string;
}

export interface HeatmapPoint {
  lat: number;
  lng: number;
  weight: number;
}

export interface TractMetricsDTO {
  fipsTract: string;
  year: number;
  medianIncome: number | null;
  pctRenter: number | null;
  pctWhite: number | null;
  pctBlack: number | null;
  pctHispanic: number | null;
  pctAsian: number | null;
  homeownershipRate: number | null;
  totalHousingUnits: number | null;
  city: string | null;
  county: string | null;
  state: string | null;
}

export interface ConcentrationScoreDTO {
  fipsTract: string;
  city: string | null;
  state: string | null;
  totalSfrUnits: number | null;
  blackrockOwnedUnits: number;
  concentrationPct: number;
  computedAt: string;
}

export interface EvictionRateDTO {
  fipsTract: string;
  year: number;
  evictionRate: number | null;
  evictionFilingRate: number | null;
  evictions: number | null;
  evictionFilings: number | null;
}

export interface PriceIndexDTO {
  zipCode: string;
  year: number;
  month: number | null;
  zhvi: number | null;
  zori: number | null;
  fmr: number | null;
  city: string | null;
  state: string | null;
}

export interface SubsidiaryEntityDTO {
  id: string;
  llcName: string;
  parentEntity: ParentEntity;
  confidence: number;
  source: 'seed_list' | 'gemini' | 'opencorporates';
  registeredState: string | null;
}

export interface PipelineJobDTO {
  id: string;
  stage: PipelineStage;
  status: PipelineStatus;
  city: string | null;
  startedAt: string | null;
  completedAt: string | null;
  errorMsg: string | null;
  rowsProcessed: number | null;
  createdAt: string;
}

// ── Request / filter types ─────────────────────────────────────────────────────

export interface PropertyFilters {
  city?: string;
  minYear?: number;
  maxYear?: number;
  entity?: ParentEntity;
  minConfidence?: number;
  bbox?: [number, number, number, number]; // [west, south, east, north]
}

export interface NLQueryRequest {
  question: string;
  city?: string;
}

export interface NLQueryResponse {
  answer: string;
  filters: Partial<PropertyFilters>;
  mapAction: MapAction;
  targetFips: string[];
  sqlIntent: string;
}

// ── Aggregated / computed types ────────────────────────────────────────────────

export interface TractDetail {
  fipsTract: string;
  tractName: string | null;
  city: string | null;
  county: string | null;
  state: string | null;
  concentration: ConcentrationScoreDTO | null;
  metricsHistory: TractMetricsDTO[];
  evictionHistory: EvictionRateDTO[];
  priceHistory: PriceIndexDTO[];
  properties: PropertyDTO[];
  cityAvgConcentration: number | null;
}

export interface MarketSummary {
  city: string;
  state: string;
  totalProperties: number;
  byEntity: Record<ParentEntity, number>;
  avgConcentration: number;
  topTracts: Array<{
    fipsTract: string;
    tractName: string | null;
    concentrationPct: number;
    propertyCount: number;
  }>;
  yearRange: { min: number; max: number };
}

export interface TractComparison {
  tractA: TractDetail;
  tractB: TractDetail;
}

// ── Report types ───────────────────────────────────────────────────────────────

export interface ReportData {
  fipsTract: string;
  tractName: string | null;
  city: string;
  state: string;
  generatedAt: string;
  narrative: string;
  headline: string;
  keyStats: string[];
  concentration: ConcentrationScoreDTO;
  metrics2019: TractMetricsDTO | null;
  metrics2023: TractMetricsDTO | null;
  evictionLatest: EvictionRateDTO | null;
  countyEvictionMedian: number | null;
  priceHistory: PriceIndexDTO[];
  topEntities: Array<{ entity: ParentEntity; count: number; llcNames: string[] }>;
  properties: PropertyDTO[];
  mapImageBase64: string | null;
}

// ── Gemini internal types ──────────────────────────────────────────────────────

export interface GeminiLLCResolution {
  parentEntity: ParentEntity;
  confidence: number;
  reasoning: string;
  subsidiaryChain: string[];
}

export interface GeminiNarrative {
  narrative: string;
  headline: string;
  keyStats: string[];
}

export interface GeminiQueryTranslation {
  filters: Partial<PropertyFilters>;
  mapAction: MapAction;
  targetFips: string[];
  explanation: string;
  sqlIntent: string;
}
