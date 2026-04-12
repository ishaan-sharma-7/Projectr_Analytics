/**
 * University abbreviation utility.
 *
 * Priority order:
 *   1. Known mappings table (curated, unambiguous)
 *   2. Pattern-based inference  ("University of X Y" → UXY, "Name University" → Name)
 *   3. Initials of significant words as last resort
 *
 * `resolveCompareLabels` picks abbreviations for a pair and disambiguates
 * if both would produce the same string (e.g., UW for Washington vs Wyoming).
 */

// ── Lookup table ──────────────────────────────────────────────────────────────
// Keys are lowercase, stripped of punctuation. Values are the display abbreviation.

const KNOWN: Record<string, string> = {
  // ── Flagship / well-known ──
  "virginia polytechnic institute and state university": "VT",
  "virginia tech": "VT",
  "massachusetts institute of technology": "MIT",
  "california institute of technology": "Caltech",
  "georgia institute of technology": "GT",
  "rensselaer polytechnic institute": "RPI",
  "florida institute of technology": "FIT",
  "illinois institute of technology": "IIT",
  "new jersey institute of technology": "NJIT",

  // ── University of [State] ──
  "university of alabama": "UA",
  "university of alaska fairbanks": "UAF",
  "university of alaska": "UAF",
  "university of arizona": "UArizona",
  "university of arkansas": "UArkansas",
  "university of california los angeles": "UCLA",
  "university of california berkeley": "UC Berkeley",
  "university of california san diego": "UCSD",
  "university of california davis": "UC Davis",
  "university of california santa barbara": "UCSB",
  "university of california irvine": "UCI",
  "university of california santa cruz": "UCSC",
  "university of colorado boulder": "CU Boulder",
  "university of colorado": "CU",
  "university of connecticut": "UConn",
  "university of delaware": "UDel",
  "university of florida": "UF",
  "university of georgia": "UGA",
  "university of hawaii at manoa": "UH Manoa",
  "university of hawaii": "UH",
  "university of idaho": "UI",
  "university of illinois urbana-champaign": "UIUC",
  "university of illinois at urbana-champaign": "UIUC",
  "university of illinois chicago": "UIC",
  "university of iowa": "Iowa",
  "university of kansas": "KU",
  "university of kentucky": "UK",
  "university of louisiana at lafayette": "ULL",
  "university of louisville": "UofL",
  "university of maine": "UMaine",
  "university of maryland college park": "UMD",
  "university of maryland": "UMD",
  "university of massachusetts amherst": "UMass",
  "university of massachusetts": "UMass",
  "university of miami": "UM Miami",
  "university of michigan ann arbor": "U-M",
  "university of michigan": "U-M",
  "university of minnesota twin cities": "UMN",
  "university of minnesota": "UMN",
  "university of mississippi": "Ole Miss",
  "university of missouri": "Mizzou",
  "university of montana": "UM",
  "university of nebraska lincoln": "UNL",
  "university of nebraska": "UNL",
  "university of nevada las vegas": "UNLV",
  "university of nevada reno": "UNR",
  "university of new hampshire": "UNH",
  "university of new mexico": "UNM",
  "university of north carolina at chapel hill": "UNC",
  "university of north carolina chapel hill": "UNC",
  "university of north carolina": "UNC",
  "university of north dakota": "UND",
  "university of oklahoma": "OU",
  "university of oregon": "UO",
  "university of pennsylvania": "UPenn",
  "university of rhode island": "URI",
  "university of south carolina": "USC",
  "university of south dakota": "USD",
  "university of south florida": "USF",
  "university of southern california": "USC",
  "university of tennessee knoxville": "UTK",
  "university of tennessee": "UTK",
  "university of texas at austin": "UT Austin",
  "university of texas": "UT",
  "university of utah": "U of U",
  "university of vermont": "UVM",
  "university of virginia": "UVA",
  "university of washington": "UW",
  "university of wisconsin madison": "UW–Mad.",
  "university of wisconsin-madison": "UW–Mad.",
  "university of wisconsin": "UW–Mad.",
  "university of wyoming": "UWyo",

  // ── [State] State University ──
  "arizona state university": "ASU",
  "boise state university": "BSU",
  "colorado state university": "CSU",
  "florida state university": "FSU",
  "iowa state university": "ISU",
  "kansas state university": "K-State",
  "kentucky state university": "KSU",
  "michigan state university": "MSU",
  "mississippi state university": "Miss. State",
  "montana state university": "MSU-MT",
  "north carolina state university": "NC State",
  "north dakota state university": "NDSU",
  "ohio state university": "OSU",
  "the ohio state university": "OSU",
  "oklahoma state university": "Okla. State",
  "oregon state university": "OSU-OR",
  "pennsylvania state university": "Penn State",
  "san diego state university": "SDSU",
  "san jose state university": "SJSU",
  "south dakota state university": "SDSU-SD",
  "utah state university": "USU",
  "washington state university": "WSU",
  "west virginia university": "WVU",

  // ── Ivy League & elite private ──
  "brown university": "Brown",
  "carnegie mellon university": "CMU",
  "columbia university": "Columbia",
  "cornell university": "Cornell",
  "dartmouth college": "Dartmouth",
  "duke university": "Duke",
  "emory university": "Emory",
  "georgetown university": "Georgetown",
  "harvard university": "Harvard",
  "johns hopkins university": "JHU",
  "new york university": "NYU",
  "northwestern university": "NU",
  "notre dame university": "ND",
  "university of notre dame": "ND",
  "princeton university": "Princeton",
  "rice university": "Rice",
  "stanford university": "Stanford",
  "tufts university": "Tufts",
  "tulane university": "Tulane",
  "vanderbilt university": "Vanderbilt",
  "wake forest university": "WFU",
  "yale university": "Yale",

  // ── Other named schools ──
  "american university": "AU",
  "auburn university": "Auburn",
  "baylor university": "Baylor",
  "boston college": "BC",
  "boston university": "BU",
  "brigham young university": "BYU",
  "clark university": "Clark",
  "clemson university": "Clemson",
  "drexel university": "Drexel",
  "fordham university": "Fordham",
  "george mason university": "GMU",
  "george washington university": "GWU",
  "gonzaga university": "Gonzaga",
  "harvey mudd college": "HMC",
  "indiana university": "IU",
  "lehigh university": "Lehigh",
  "louisiana state university": "LSU",
  "loyola university chicago": "LUC",
  "marquette university": "Marquette",
  "miami university": "Miami-OH",
  "michigan technological university": "MTU",
  "missouri university of science and technology": "Missouri S&T",
  "naval postgraduate school": "NPS",
  "northeastern university": "NEU",
  "purdue university": "Purdue",
  "rutgers university new brunswick": "Rutgers",
  "rutgers university": "Rutgers",
  "rutgers the state university of new jersey": "Rutgers",
  "santa clara university": "SCU",
  "southern methodist university": "SMU",
  "stony brook university": "Stony Brook",
  "syracuse university": "Syracuse",
  "temple university": "Temple",
  "texas a&m university": "TAMU",
  "texas tech university": "TTU",
  "united states military academy": "West Point",
  "united states naval academy": "USNA",
  "university at buffalo": "UB",
  "virginia commonwealth university": "VCU",
  "william & mary": "W&M",
  "college of william and mary": "W&M",
  "college of william & mary": "W&M",
};

// ── Normalizer ────────────────────────────────────────────────────────────────

/** Lowercase + strip punctuation for consistent table lookup. */
function normalize(name: string): string {
  return name
    .toLowerCase()
    .replace(/[,.\-–—]/g, " ") // commas, dashes → space
    .replace(/\s+/g, " ")
    .trim();
}

// ── Fallback inference ────────────────────────────────────────────────────────

const STOP = new Set(["of", "the", "and", "at", "in", "for", "a", "an"]);
const GENERIC_STARTS = new Set([
  "university",
  "college",
  "institute",
  "school",
]);

function inferAbbrev(name: string): string {
  const words = normalize(name).split(" ").filter(Boolean);
  if (words.length === 0) return name.slice(0, 4).toUpperCase();

  const significant = words.filter((w) => !STOP.has(w));

  // "University/College/Institute of X Y Z" → initials of X Y Z prefixed by U/C/I
  if (GENERIC_STARTS.has(significant[0]) && significant[1] !== undefined) {
    const rest = significant.slice(1).filter((w) => !STOP.has(w));
    if (rest.length === 0) return significant[0].slice(0, 4).toUpperCase();
    const initials = rest.map((w) => w[0].toUpperCase()).join("");
    // Prefix with first letter of institution type only if 2+ remaining words
    return rest.length >= 2 ? initials.slice(0, 5) : rest[0].slice(0, 6);
  }

  // "Harvard University", "Duke University" — distinctive word first
  if (!GENERIC_STARTS.has(significant[0]) && !STOP.has(significant[0])) {
    const first = significant[0];
    // Capitalize first letter, rest lowercase, max 8 chars
    return first.charAt(0).toUpperCase() + first.slice(1, 8);
  }

  // Fallback: initials of all significant words
  return significant
    .map((w) => w[0].toUpperCase())
    .join("")
    .slice(0, 5);
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * Return a short, recognizable abbreviation for a university name.
 * Tries the curated table first, then infers from name structure.
 */
export function getAbbrev(name: string): string {
  const key = normalize(name);
  if (KNOWN[key]) return KNOWN[key];

  // Partial match: check if the normalized name contains a known key as a prefix
  for (const [k, v] of Object.entries(KNOWN)) {
    if (key.startsWith(k) || k.startsWith(key)) return v;
  }

  return inferAbbrev(name);
}

/**
 * Resolve abbreviations for a comparison pair.
 * If both universities would get the same abbreviation, falls back to
 * "Abbrev (City)" for both to disambiguate.
 */
export function resolveCompareLabels(
  nameA: string,
  cityA: string,
  nameB: string,
  cityB: string,
): [string, string] {
  const abbA = getAbbrev(nameA);
  const abbB = getAbbrev(nameB);

  if (abbA.toLowerCase() === abbB.toLowerCase()) {
    return [`${abbA} (${cityA})`, `${abbB} (${cityB})`];
  }

  return [abbA, abbB];
}
