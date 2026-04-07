# Institutional Parent Rollup — Methodology

This document explains how the Travis County institutional ownership dataset was reduced from ~1,400 corporate shell entities into ~24 verifiable parent operators, the discipline used to avoid false attributions, and how the LLM-based verification step works. It is the reference for anyone reviewing, validating, or extending the rollup.

---

## 1. Problem statement

The Travis County Clerk and TCAD (Travis County Appraisal District) record property ownership at the level of the *legal owner*. For institutional owners, the legal owner is almost never the parent firm — it's a special-purpose vehicle (SPV), a securitization borrower, a state-level holding LLC, or a sub-fund. American Homes 4 Rent owns thousands of Austin houses but the deeds are held by `AMH 2014-1 BORROWER LLC`, `AH4R-TX I LLC`, `AMH TX PROPERTIES LP`, etc.

For any kind of analysis or visualization that talks about "Blackstone" or "Pretium" or "AMH" the way a reader expects, we need to collapse those shell entities back to their actual operators. Doing this naively (regex on names, address clustering, etc.) generates false matches in both directions:

- **False merges**: collapsing two unrelated companies that happen to share a generic name fragment (`CAPITAL PARTNERS LLC`, `HOLDINGS INC`)
- **False splits**: failing to recognize that two entities with totally different names share the same parent (`PURCHASING FUND 2020-1 LLC` and `LENDINGHOME FUNDING CORP` are both Kiavi)

The methodology below is built specifically to avoid both failure modes by separating *what we observe in the data* from *what we infer about parentage*, and by requiring an external public source for any inference.

---

## 2. Source data

All inputs live in `processed_owners/`. The pipeline reads three files.

### `institutional_deeds.csv` — 6,313 rows
Travis County Clerk deed records, scraped via Playwright from `tccsearch.org` using the keyword tiers in `scripts/scrape_deeds.py`. Each row is a recorded instrument (deed, deed of trust, substitute trustee deed, release, etc.) with grantee, grantor, instrument number, date filed, and document type. Crucially, every row carries the `Search_Keyword` field — the keyword that surfaced that row from the clerk's search interface. **`Search_Keyword` reflects the query, not what the parties are.** If you searched "PROGRESS RESIDENTIAL" and the result was a deed where Toorak sold to Pretium, the row's `Search_Keyword` is `PROGRESS RESIDENTIAL` — but Toorak is not a Pretium entity. This distinction is the source of the most dangerous bug class in the pipeline (more on this in §4).

### `institutional_owners_2025_deep_clean.csv` — 3,608 rows
Current ownership snapshot, derived from the 2025 TCAD PROP.TXT export by `scripts/deep_scan_prop.py`. One row per property currently held by an institutional entity, with `Owner_Name`, `Mailing_Address`, `Property_Address`, `Property_ID`, and `Match_Reason` (which keyword triggered the match, or which mailing-address cluster). Addresses were post-processed by `scripts/fix_addresses.py` to fill in situs addresses from the EARS CSVs.

### `mailing_address_clusters.csv` — 61 rows
A precomputed list of mailing addresses with ≥10 distinct corporate entities mailing to them. Each cluster is a strong signal of either (a) a parent operator's corporate office, (b) a registered agent / law firm mail drop, or (c) a property management hub. Cluster size is one of the three independent signals used in the candidate-affiliate detector.

---

## 3. Pipeline overview

```
                ┌──────────────────────────────┐
                │  institutional_deeds.csv     │
                │  6,313 rows (4,915 unique)   │
                └──────────────┬───────────────┘
                               │
                               ▼
                ┌──────────────────────────────┐
                │  build_parent_rollup.py      │
                │  ─ counterparty edge graph   │
                │  ─ entity → bucket map       │
                │  ─ verified parent lookup    │◄──┐
                │  ─ candidate affiliate scan  │   │ VERIFIED_PARENTS
                │  ─ warehouse score           │   │ (curated dict
                │  ─ LLM prompt generator      │   │  of public
                └──────────────┬───────────────┘   │  parent → source)
                               │                   │
                               ▼                   │
   processed_owners/                               │
   ├── high_confidence_rollup.csv                  │
   ├── candidate_affiliates.csv                    │
   ├── counterparty_edges.csv                      │
   ├── warehouse_score.csv                         │
   └── llm_verification_prompts.txt ───────────────┘
                                  paste into Gemini
                                  Deep Research → table
                                  → manually merge
                                    into VERIFIED_PARENTS
```

The single script is `scripts/build_parent_rollup.py`. It is deterministic — re-running with the same inputs always produces the same outputs. There is no machine learning, clustering, or fuzzy matching anywhere in the pipeline.

---

## 4. False-flag avoidance — the discipline

This is the core of the methodology. Every rule below exists because there's a specific failure mode it prevents.

### Rule 1: Entities are only collapsed via the curated keyword list

The "buckets" we collapse entities into are not derived from the data — they are taken directly from `TIER1_KEYWORDS`, `TIER2_FEEDERS`, `TIER3_OTHER`, and `TIER4_LENDER_REO` in `scripts/scrape_deeds.py`. These keyword lists are hand-curated. Each one came from one of three places:

- A known operator brand or filing (`AMH 2014`, `INVITATION HOMES`, `PURCHASING FUND`)
- A counterparty that surfaced in a prior deed scan and was investigated (`SFR ACQUISITIONS`, `CARMA PROPERTIES WESTPORT`)
- A securitization series naming pattern observed in EDGAR or news (`HPA BORROWER 2020-2`, `IH BORROWER`)

The script never invents a new bucket. It can only assign entities to buckets a human already wrote down.

### Rule 2: Substring match against the entity's own name, not the search keyword

This is the most important defensive rule and the one that almost shipped a bug. In the deed CSV, every row carries `Search_Keyword` — the query that returned the row. If you search "PROGRESS RESIDENTIAL" you get back deeds where Pretium is one of the parties, but the *other party* (grantor or grantee) can be anyone — a flipper, a homeowner, a competing lender, or another institutional landlord that happens to have transacted with Pretium.

The first version of `build_parent_rollup.py` assigned each entity the first `Search_Keyword` that surfaced it. That produced this:

```
TOORAK CAPITAL PARTNERS LLC → Pretium Partners        ❌ (wrong)
ANCHOR LOANS LP → Kiavi                               ❌ (wrong)
CARMA PROPERTIES WESTPORT LLC → American Homes 4 Rent ❌ (wrong)
```

These are all wrong. Toorak appeared as a counterparty in a deed surfaced by searching Pretium-related keywords, so the script labeled it Pretium. The fix is in `load_deeds()` at `scripts/build_parent_rollup.py:104`:

> An entity is only assigned a keyword bucket if the keyword is a substring of the entity's own name. The Search_Keyword reflects which query returned the row, not which side of the deed the keyword refers to.

Same fix applies to `build_tier4_buyer_set()` at `scripts/build_parent_rollup.py:298` — for the warehouse-pipeline signal, we check the *grantor's name* directly for Tier 4 keywords, not the deed's `Search_Keyword`.

### Rule 3: The verified-parent map only contains publicly documented parents

`VERIFIED_PARENTS` in `scripts/build_parent_rollup.py:42` is a Python dictionary that maps `bucket_keyword → (parent_name, source_citation)`. The strict rule for adding an entry: **the parent must be a matter of public record.** Acceptable sources, in order of preference:

1. SEC EDGAR filing (10-K, 10-Q, S-1, ABS-EE, S-3, prospectus)
2. Company press release
3. Major news outlet (WSJ, Bloomberg, Reuters, FT, NYT)
4. PE firm portfolio page or government regulatory filing (BaFin, Federal Reserve, state SOS)

If the parent isn't in one of those, the entry is left blank and the bucket goes into the LLM verification queue. **Adding a guess to `VERIFIED_PARENTS` defeats the entire methodology.** This is a non-negotiable rule. If you can't cite it, don't add it.

### Rule 4: Candidate affiliate detection requires three independent signals

For pairs of entities the keyword list doesn't already group, the candidate-affiliate detector at `scripts/build_parent_rollup.py:230` uses three signals that must all agree before flagging:

1. **≥5 deed cross-transactions** between the two entities (counterparty graph)
2. **Identical normalized mailing address** (after suite-number stripping)
3. **Mailing cluster of ≥3 corporate entities** at that address (filters out attorney mail drops)

Even when all three fire, the output is labeled `candidate — verify via Texas SOS or Gemini Deep Research`. It is never auto-merged into the rollup. This is a discovery tool, not a classifier.

The current run produces exactly **one** candidate pair: `HP TEXAS I LLC ↔ HPA TEXAS SUB 2018-1 MS LLC`, both already known HPA/Blackstone entities mailing to `120 S RIVERSIDE PLZ CHICAGO IL` (Blackstone Chicago). The methodology correctly flagged a real affiliate pair we'd already labeled — that's the validation. The strictness is the point. A looser threshold would generate noise.

### Rule 5: Naming similarity is never used as a signal

Not for grouping, not as a tiebreaker, not as a fallback. Two entities with similar name fragments are treated as unrelated until a verified source proves otherwise. Naming similarity is only ever displayed as a column in the LLM verification prompt for the human reviewer.

### Rule 6: Unknown is a valid answer

If a bucket has no public parent, it stays in the rollup with `verified_parent` blank. It is not deleted, not merged, not guessed at. The pipeline is honest about what it doesn't know.

---

## 5. The keyword tier system

The keyword lists in `scripts/scrape_deeds.py` are organized into four tiers that reflect different types of institutional behavior. Understanding which tier a bucket belongs to is essential for interpreting the rollup.

### Tier 1 — Buy-to-rent landlords
The mega-REIT and PE-backed firms that acquire scattered-site single-family homes for long-term rental income. American Homes 4 Rent, Invitation Homes, Progress Residential (Pretium), Tricon (Blackstone), Home Partners of America (Blackstone), FirstKey Homes (Cerberus), Amherst's Main Street Renewal. These are the "they're buying up all the houses" headline operators.

### Tier 2 — Feeder / flipper LLCs
LLCs that don't appear to be permanent landlords but show up as repeat sellers to Tier 1 operators. Discovered by scanning the grantor side of Tier 1 deeds and looking for LLCs with ≥5 transactions. Examples: `RH PARTNERS OWNERCO`, `CARMA PROPERTIES WESTPORT`, `KAISER PROPERTIES BLUE`. Some turn out to be Tier 1 sub-vehicles, some are independent flippers, some are developers.

### Tier 3 — Other institutional SFR + historical exiters
Smaller SFR operators (VineBrook, Sylvan, Pathlight) plus iBuyers and REO pools that have since exited the market (Zillow Homes, Orchard, RedfinNow, HPA II BORROWER, Firebird SFE). Historical exiters are still important because the deeds they left behind affect *current* ownership of those specific houses.

### Tier 4 — Fix-and-flip lender REO
This is functionally a different category from Tier 1. These firms originate hard-money loans to local property flippers (the kind of investor who buys a distressed house, renovates, and resells). When a flipper defaults, the lender forecloses and ends up holding REO. Toorak, Kiavi, LendingHome, HouseMax, Park Place Finance, Anchor Loans, Genesis Capital, RCN Capital, etc. The displacement story is different from buy-to-rent: these entities don't *want* to own the houses, but they cycle through them as the by-product of distressed lending.

Why the tier distinction matters for analysis: the *story* about Tier 1 ("Wall Street is buying up Austin neighborhoods") and the *story* about Tier 4 ("predatory bridge lenders are taking houses through foreclosure") are different policy and journalism arguments. Mixing them produces a confused narrative.

---

## 6. Output files

All in `processed_owners/`.

### `high_confidence_rollup.csv` — 329 rows
The primary artifact. One row per corporate entity that the script can confidently bucket. Columns:

| Column | Meaning |
|---|---|
| `entity` | The exact LLC/LP name as it appears in the deed or owner records |
| `bucket_keyword` | The curated keyword that matched this entity's name |
| `verified_parent` | The publicly documented parent operator, or blank if unknown |
| `source` | URL or citation supporting the parent attribution |
| `n_properties` | How many Travis County properties this entity currently owns (from TCAD 2025) |
| `n_deeds` | How many deed records mention this entity (from clerk scrape) |
| `mailing_address` | Current mailing address from TCAD |
| `mailing_cluster` | How many other corporate entities mail to that same normalized address |

Sorted with verified parents first, then by deed volume. The presence of a `verified_parent` value means a human or Deep Research reviewed it against a public source. The absence of one means it's in the verification queue.

### `candidate_affiliates.csv`
Pairs that satisfy all three rule-4 signals. Currently 1 pair. Each row is `entity_a, entity_b, cross_transactions, shared_mailing, mailing_cluster_size, entity_a_known_bucket, entity_b_known_bucket, recommendation`. If the file ever has many rows, that's a signal worth investigating — it would mean the keyword list is missing a parent entirely.

### `counterparty_edges.csv` — 1,191 pairs
The raw entity → entity transaction graph from the deeds CSV. Each row is `entity_a, entity_b, transaction_count`, sorted by frequency. This is the input you'd feed to a graph visualization tool. No inference applied — just the raw counts.

### `warehouse_score.csv` — 3,285 properties
Per-property warehousing score, from 1 to 4. Each property gets +1 for each independent signal that fires:

1. Current owner is in the Tier 4 keyword set (lender REO list)
2. Current owner ever bought from a Tier 4 lender (deed graph signal — see `build_tier4_buyer_set()` at `scripts/build_parent_rollup.py:298`)
3. Mailing cluster ≥5 entities
4. Owner holds ≥5 properties (concentration)

Properties are also marked `is_developer_likely` if the owner name matches a regex of homebuilder/developer terms (`DEVELOPMENT|TRACT|HOMES INC|HOMES LLC|BUILDERS|CONSTRUCTION|RANCH|MASTER COMMUNITY|LOT OPTION|SUBDIVISION`). Developers tend to dominate the concentration signal but aren't institutional landlords — flagging them prevents the warehouse list from being drowned in tract homebuilders.

Sorted with non-developers first, then by score descending.

### `llm_verification_prompts.txt`
A single consolidated Gemini Deep Research prompt that asks for parents on all currently-unverified buckets and demands a parseable markdown table back. Regenerated every run from whatever buckets are still missing from `VERIFIED_PARENTS`. After the most recent verification round this is down to 9 buckets.

### `_capped_keywords.md`
A static reference of which keywords hit the 300-record server cap on the clerk site. These need to be re-scraped with year-by-year date filters to get the full historical record. See the file for the suggested split plan.

---

## 7. The Deep Research workflow

This is how the LLM verification step works. It's a one-shot batch operation, not a per-bucket loop, and it has strict guardrails.

### Why use an LLM at all?

The verified-parent map is hand-curated and only contains parents we already know about. After the script runs, anything not in the map appears in `llm_verification_prompts.txt`. Looking up each unknown bucket manually means searching SEC EDGAR, news, press releases, court records, and PE firm portfolio pages. That's exactly what Gemini Deep Research / Claude Research are good at — directed multi-source web research with citations.

What an LLM is *not* good at: ground-truthing private LLC ownership without public traces. For those, the LLM should answer UNKNOWN, not guess. The prompt enforces this.

### What the prompt looks like

`processed_owners/llm_verification_prompts.txt` is regenerated every time the script runs. Structure:

1. **Context block** — explains what the dataset is and what the buckets are
2. **Rules block** — the citation hierarchy (SEC > press release > news > PE portfolio > UNKNOWN), confidence levels (HIGH/MEDIUM/LOW), and the explicit instruction *do not guess based on naming similarity*
3. **Output format block** — demands a markdown table with columns `bucket | parent | confidence | source_url | notes` and nothing else
4. **Buckets to research** — numbered list with sample entities and observed mailing addresses for each unverified bucket, sorted by deed volume so the heavy ones get more research budget
5. **Closing instruction** — re-anchors on the rules

The whole file is 12 KB / 250 lines. It's designed to be pasted as a single prompt into Gemini Deep Research (or Claude Research). The single-prompt format is more token-efficient than running each bucket as a separate query, and it lets the research engine treat the whole thing as one task with N sub-targets, allocating proportional effort.

### How to actually run it

1. Open `processed_owners/llm_verification_prompts.txt`
2. Copy the entire file
3. Paste into Gemini Deep Research at `gemini.google.com` (model: 2.5 Pro Deep Research or equivalent)
4. Wait for it to run (typically 5–15 minutes for 20–30 buckets)
5. The output will be a markdown table plus a long narrative report
6. **Read the narrative.** Deep Research often surfaces useful chain information that doesn't fit in the table — e.g., "this entity was acquired by X in 2018, then X was renamed Y, then Y was taken private by Z in 2021." That chain matters for understanding current vs. historical ownership.
7. Paste the output table back to whoever maintains `VERIFIED_PARENTS` for manual integration

### What to trust and what to discard

For each row in the response:

- **HIGH confidence + SEC EDGAR or press release URL** — accept as-is, add to `VERIFIED_PARENTS`
- **HIGH confidence + corporate website URL** — accept, but verify the URL actually loads and says what the LLM claims (LLMs occasionally invent plausible-looking URLs)
- **MEDIUM confidence + court / regulatory / tax source** — accept with the `[MEDIUM]` tag in the parent name, so downstream consumers know there's a confidence cliff
- **MEDIUM confidence + Crunchbase or job-board source** — accept with a healthy skepticism, double-check before publishing externally
- **LOW confidence** — do not accept. Leave blank.
- **UNKNOWN with `no_public_source`** — do not accept. Leave blank.
- **Anything without a citation URL** — do not accept, regardless of confidence label.

The most recent Deep Research run resolved 14 buckets at HIGH and 6 at MEDIUM, leaving 9 correctly classified as UNKNOWN. It correctly refused to attribute Patch of Land Lending to Toorak even though Toorak buys their loans — a clean demonstration of the discipline holding under temptation.

### Why this works (and why it could fail)

Deep Research works for this problem because corporate parentage in regulated industries leaves a public trail:

- Public REITs file 10-Ks listing their subsidiaries
- Securitizations file ABS-EE with their sponsors named
- M&A activity above a threshold generates press releases and news coverage
- PE firms publish portfolio pages

It fails when:

- The entity is purely private and never tapped public capital markets (most local fix-flippers)
- The entity is a one-off SPV created for a single deal that never went public
- The parent is intentionally obscured behind nominee structures (rare but exists)

For those cases, the only authoritative source is **state SOS officer filings** (Texas Secretary of State for Texas LLCs). LLMs can't reliably reach these — they're not consistently crawled. If you need parents for the remaining 9 unknown buckets, the path is to manually pull SOS filings for the entities and look at the listed officers/managers.

---

## 8. Current results

### Parent landscape, sorted by deed activity

| Deed events | Entities | Parent | Source |
|---:|---:|---|---|
| 1,554 | 54 | American Homes 4 Rent | NYSE: AMH (10-K) |
| 1,014 | 39 | Kiavi (formerly LendingHome) | Kiavi 2021 rebrand; PURCHASING FUND SPV confirmed via 52 cross-tx with LendingHome Funding Corp |
| 633 | 7 | Toorak Capital | KKR portfolio page |
| 622 | 73 | Blackstone (Home Partners of America) | Blackstone 2021 acquisition; SFR BORROWER series confirmed via court complaint |
| 466 | 5 | Park Place Finance LLC (independent) | parkplacefinance.com (Justin Hubbert, founder) |
| 439 | 34 | Pretium Partners | Multiple brands: Progress Residential, Pathlight, Anchor Loans (2021 acquisition), Front Yard Residential / Firebird SFE |
| 300 | 10 | Hunt Companies, Inc. | American Community Investor / Hunt Companies acquisition of HouseMax |
| 297 | 2 | Brookfield Residential | Carma Properties Westport — Easton Park master-planned community |
| 245 | 8 | Orchard (exited) | Orchard pivot 2023 |
| 216 | 2 | Redfin (exited) | RedfinNow shutdown 2022 |
| 207 | 6 | Beal Financial Corporation | SEC 13G — LNV Corporation is wholly-owned subsidiary; ultimate control by D. Andrew Beal |
| 199 | 5 | Zillow (exited) | Zillow Offers shutdown 2021 |
| 187 | 9 | Rithm Capital | Genesis Capital acquisition 2021 from Goldman Sachs (NYSE: RITM, formerly New Residential) |
| 115 | 2 | Merchants Mortgage & Trust Corporation | State regulatory abstracts |
| 82 | 18 | Blackstone (Tricon) | Blackstone 2024 acquisition |
| 75 | 4 | Dominion Group | dominionfinancialservices.com (founded by Fred Lewis) |
| 56 | 8 | Cerberus Capital Management | FirstKey Homes parent |
| 54 | 8 | The Carlyle Group | BaFin disclosure: CRP = Carlyle Realty Partners; Argyle Guthrie joint venture |
| 45 | 3 | RCN Capital LLC (independent) | rcncapital.com |
| 24 | 7 | Amherst Holdings | Main Street Renewal parent; TRANS AM SFE via tax records |
| 17 | 4 | Invitation Homes | Includes legacy Tarbert/Starwood Waypoint via 2017 merger |
| 9 | 2 | California Capital Real Estate Advisors, Inc. | CALCAP corporate newsletter |
| 6 | 2 | Capital Management Services, LP | Job posting attribution |
| 5 | 1 | BlackRock | NYSE: BLK |

**313 of 329 entities verified (95%)** across **24 distinct parent operators**. 16 entities across 9 buckets remain in the unknown queue.

### Notable findings from the verification round

1. **Pretium Partners is bigger than the headline number suggests.** They control four distinct brands in Travis County: Progress Residential (Tier 1 buy-to-rent), Pathlight Property Management, Anchor Loans (acquired Nov 2021), and Front Yard Residential / Firebird SFE (acquired 2021 after the Altisource→Front Yard rebrand). Combined: 439 deed events across 34 entities.

2. **Hunt Companies, Inc. is an under-reported player.** El Paso–based diversified holding firm with no profile in SFR press coverage, owns HouseMax via American Community Investor. 300 deeds, 10 entities. Worth investigating further for the journalism layer.

3. **Brookfield Residential's Carma Properties = Easton Park.** Two entities account for 297 deeds, all tied to the Easton Park master-planned community in southeast Austin. For map visualization, this becomes a single labeled polygon. The "Carma" name is a legacy holdover from Brookfield's acquisition of Carma Developers.

4. **Blackstone HPA collapsed six buckets into one parent.** The SFR BORROWER 2021/2022, SFR II BORROWER, SFR ACQUISITIONS, HPA TEXAS, HPA BORROWER, HPA JV, HPA US, HP TEXAS, HOME PARTNERS OF AMERICA, HOME PARTNERS REALTY, and HPA II BORROWER buckets all roll up to Blackstone HPA. 73 entities total — second-largest by entity count after AMH itself.

5. **Carlyle Realty Partners is in Travis County via JVs, not SFR.** CRP/Argyle Guthrie and Guthrie Property are development joint ventures, not buy-to-rent landlords. Different mechanism, same underlying capital pool. Worth tracking separately in the analysis.

6. **Beal Financial / D. Andrew Beal represents the legacy distressed-debt model.** LNV Corporation is the most active distressed-mortgage acquirer in the dataset. Different displacement story from fix-flip lender REO — Beal buys non-performing first mortgages from servicers and forecloses directly. 207 deeds.

7. **Patch of Land Lending stayed UNKNOWN — and that was correct.** Toorak Capital buys Patch of Land's loans, but acquiring a loan portfolio is not acquiring the originating company. Deep Research correctly distinguished these and refused to attribute. This is the false-flag avoidance discipline holding up under exactly the kind of temptation it was designed to resist.

---

## 9. Open items

### Re-scrape capped keywords with date splits
Seven Tier 4 keywords hit the 300-record server cap on the clerk site (`HOUSEMAX FUNDING`, `LENDINGHOME FUNDING`, `KIAVI FUNDING`, `CARMA PROPERTIES WESTPORT`, `PARK PLACE FINANCE`, `TOORAK CAPITAL`, `TOORAK CAPITAL PARTNERS`). See `processed_owners/_capped_keywords.md` for the suggested year-by-year split plan. Filling these in will likely double the size of the relevant parent buckets.

### Resolve the remaining 9 unknown buckets
`TUSKER CAPITAL FUND`, `KAISER PROPERTIES BLUE`, `HOMEWARD PROPERTIES`, `RH PARTNERS OWNERCO`, `PATCH OF LAND LENDING`, `GREEN TREE HE/HI BORROWER`, `SFR INVESTMENTS V`, `3105 ETHEREDGE`, `SOUTH LAMAR VENTURE`. These are all genuinely opaque private LLCs. The next step for any of them is a manual Texas Secretary of State officer search. Tusker Capital Fund is the most worth investigating because it had 36 cross-transactions with Kiavi-related entities in our deed graph — there's likely a real connection there but no public source confirms it yet.

### Property → instrument linkage
The deeds CSV has `Legal_Description` but not `Property_ID`. There is currently no clean way to join "this specific Austin house" to "the specific Tier 4 deed that put it into a flip pipeline." Building that join would require parsing legal descriptions or matching on grantor/grantee + date. With it, the warehouse score could become "this exact property was warehoused" instead of "this owner has warehouse-pattern signals."

### Counterparty graph visualization
`counterparty_edges.csv` is ready to feed a graph viz (Gephi, Cytoscape, or a D3 force-directed layout). Each node would be a corporate entity, sized by deed volume and colored by parent operator. The clusters in the visualization should match the parent groupings — if they don't, that's a data quality signal.

### Warehouse score refinement
The current warehouse score is coarse (1–4 from independent +1 signals). It surfaces useful candidates but doesn't yet incorporate holding period (the deed dates are available, just not joined to current ownership). Adding holding period would distinguish "owned briefly then sold" (warehouse) from "owned long-term" (true landlord).

---

## 10. Files referenced

- `scripts/scrape_deeds.py` — keyword tier definitions, clerk scraper
- `scripts/deep_scan_prop.py` — TCAD PROP.TXT scanner
- `scripts/fix_addresses.py` — situs address backfill from EARS CSVs
- `scripts/build_parent_rollup.py` — the rollup pipeline (this document's subject)
- `processed_owners/institutional_deeds.csv` — deed records source
- `processed_owners/institutional_owners_2025_deep_clean.csv` — current ownership source
- `processed_owners/mailing_address_clusters.csv` — clustered mailings
- `processed_owners/high_confidence_rollup.csv` — primary output
- `processed_owners/candidate_affiliates.csv` — multi-signal candidates
- `processed_owners/counterparty_edges.csv` — raw graph
- `processed_owners/warehouse_score.csv` — scored properties
- `processed_owners/llm_verification_prompts.txt` — Gemini batch prompt
- `processed_owners/_capped_keywords.md` — capped-keyword reference
