import type { ParentEntity } from './types.js';

// ── Entity keyword matching ────────────────────────────────────────────────────
// Used by ingest handler to classify properties without Gemini

export const PARENT_ENTITY_KEYWORDS: Record<Exclude<ParentEntity, 'OTHER'>, string[]> = {
  INVITATION_HOMES: [
    'INVITATION HOMES',
    'INVH',
    'THR PROPERTY',
    'IH BORROWER',
    'IH2 LP',
    'IH3 LP',
    'IH4 LP',
    'IH5 LP',
    'IH6 LP',
    'IH4 PROPERTY',
    'SFR JV-1',
    'SFR JV-HD',
    'STARWOOD WAYPOINT',
    'COLONY AMERICAN',
    'PREEMINENT HOLDINGS',
    'BUNGALOW AVENUE',
  ],
  AMH: [
    'AMERICAN HOMES 4 RENT',
    'AMH 2014',
    'AMH 2015',
    'AMH 2016',
    'AMH 2017',
    'AMH 2018',
    'AH4R',
    'AMH TX PROPERTIES',
    'AMH TX',
    'AMH ADDISON',
    'AMH BORROWER',
  ],
  PROGRESS: [
    'PROGRESS RESIDENTIAL',
    'PROGRESS AUSTIN',
    'PROGRESS BORROWER',
    'PRETIUM',
    'FRONT YARD RESIDENTIAL',
    'AMHERST RESIDENTIAL',
  ],
  TRICON: [
    'TRICON RESIDENTIAL',
    'TRICON AMERICAN HOMES',
    'SFR JV-HD',
    'TCAM',
  ],
  BLACKROCK: [
    'BLACKROCK REALTY ADVISORS',
    'BLACKROCK REAL ESTATE',
    'GUTHRIE PROPERTY OWNER',
    'BR PROPERTY',
  ],
  FIRSTKEY: [
    'FIRSTKEY HOMES',
    'FIRST KEY HOMES',
    'CERBERUS',
    'FIRSTKEY',
  ],
  MAIN_STREET: [
    'MAIN STREET RENEWAL',
    'MSR',
    'HOME PARTNERS OF AMERICA',
    'HPA BORROWER',
  ],
};

// Flat list of all known seed keywords (for fast lookup)
export const ALL_KNOWN_KEYWORDS: string[] = Object.values(PARENT_ENTITY_KEYWORDS).flat();

// Known BlackRock subsidiary mailing address ZIP codes
// Used as a secondary classification signal
export const KNOWN_HQ_ZIPS: Record<string, ParentEntity> = {
  '75201': 'INVITATION_HOMES', // Dallas, TX — Invitation Homes HQ
  '75202': 'INVITATION_HOMES',
  '75203': 'INVITATION_HOMES',
  '75204': 'INVITATION_HOMES',
  '85256': 'PROGRESS',         // Scottsdale, AZ — Progress Residential HQ
  '91302': 'AMH',              // Calabasas, CA — AMH HQ
  '91301': 'AMH',              // Agoura Hills, CA — AMH alternate
  '89119': 'AMH',              // Las Vegas, NV — AMH office
  '30328': 'PROGRESS',         // Atlanta, GA — Progress/FirstKey
  '30004': 'FIRSTKEY',         // Alpharetta, GA — FirstKey
  '60606': 'BLACKROCK',        // Chicago, IL — Cerberus/BlackRock
};

// ── Confidence scoring ─────────────────────────────────────────────────────────

export const CONFIDENCE_THRESHOLD = 0.7;

export const CONFIDENCE_BY_MATCH_TYPE: Record<string, number> = {
  keyword_direct: 0.98,    // e.g. "Keyword: INVITATION HOMES"
  keyword_subsidiary: 0.95, // e.g. "Keyword: AMH 2015"
  keyword_generic: 0.90,   // e.g. "Keyword: INVH"
  hq_zip: 0.75,            // e.g. "HQ Zip: 75201 (TX)"
  cluster: 0.70,           // e.g. "Cluster: 42 entities at PO BOX 99141"
  gemini_high: 0.85,       // Gemini returned confidence >= 0.8
  gemini_medium: 0.65,     // Gemini returned confidence 0.5-0.8
  opencorporates_boost: 0.15, // Added to gemini_medium when OC confirms
};

// ── Entity display metadata ────────────────────────────────────────────────────

export const ENTITY_DISPLAY: Record<
  ParentEntity,
  { label: string; color: string; shortLabel: string }
> = {
  INVITATION_HOMES: { label: 'Invitation Homes', color: '#e74c3c', shortLabel: 'INVH' },
  AMH: { label: 'American Homes 4 Rent', color: '#e67e22', shortLabel: 'AMH' },
  PROGRESS: { label: 'Progress Residential', color: '#f39c12', shortLabel: 'PRG' },
  TRICON: { label: 'Tricon Residential', color: '#9b59b6', shortLabel: 'TRC' },
  BLACKROCK: { label: 'BlackRock', color: '#c0392b', shortLabel: 'BLK' },
  FIRSTKEY: { label: 'FirstKey Homes', color: '#2980b9', shortLabel: 'FKH' },
  MAIN_STREET: { label: 'Main Street Renewal', color: '#27ae60', shortLabel: 'MSR' },
  OTHER: { label: 'Other Institutional', color: '#7f8c8d', shortLabel: 'OTH' },
};

// ── Target cities ──────────────────────────────────────────────────────────────

export const SUPPORTED_CITIES = ['Austin', 'Atlanta'] as const;
export type SupportedCity = (typeof SUPPORTED_CITIES)[number];

export const CITY_CONFIG: Record<
  SupportedCity,
  { lat: number; lng: number; zoom: number; state: string; fipsCounty: string }
> = {
  Austin: { lat: 30.2672, lng: -97.7431, zoom: 11, state: 'TX', fipsCounty: '48453' },
  Atlanta: { lat: 33.749, lng: -84.388, zoom: 11, state: 'GA', fipsCounty: '13121' },
};

// ── Cache TTLs (seconds) ───────────────────────────────────────────────────────

export const CACHE_TTL = {
  HEATMAP: 300,           // 5 minutes
  TRACT_METRICS: 3600,    // 1 hour
  CONCENTRATION: 21600,   // 6 hours
  GEMINI_RESPONSE: 86400, // 24 hours
  LLC_RESOLUTION: 604800, // 7 days
  GEOCODE: 2592000,       // 30 days
  FIPS_LOOKUP: 7776000,   // 90 days
  MARKETS_SUMMARY: 3600,  // 1 hour
} as const;

// ── Timeline ───────────────────────────────────────────────────────────────────

export const TIMELINE_MIN_YEAR = 2012;
export const TIMELINE_MAX_YEAR = 2024;
