"""
build_parent_rollup.py

Collapse the institutional deed/owner graph into parent-entity buckets,
with explicit evidence tracking and zero name-similarity inference.

OUTPUTS (all in processed_owners/):
  high_confidence_rollup.csv     One row per entity. Bucket = curated keyword.
  candidate_affiliates.csv       Entity pairs with multi-signal evidence.
  counterparty_edges.csv         Raw entity → entity transaction edges.
  warehouse_score.csv            Per-property warehouse score (top first).
  llm_verification_prompts.txt   Gemini Deep Research prompt per bucket.

FALSE-FLAG AVOIDANCE:
  1. Entities are only collapsed into a bucket if they matched a hand-curated
     keyword in scrape_deeds.py. The keyword IS the bucket — no new inference.
  2. The 'verified_parent' column is populated ONLY for buckets whose ultimate
     parent is publicly documented (NYSE filings, SEC EDGAR sponsor, well-known
     M&A). Everything else stays blank and goes into the verification queue.
  3. Candidate affiliate pairs require ALL THREE signals to agree:
       - ≥5 deed cross-transactions
       - identical normalized mailing address
       - mailing cluster of ≥3 corporate entities
  4. Every output row carries its evidence columns. No black-box scoring.
  5. Naming similarity is never used as a signal.
"""

import csv
import os
import re
from collections import defaultdict, Counter

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'processed_owners')

DEEDS_CSV = os.path.join(PROCESSED_DIR, 'institutional_deeds.csv')
OWNERS_CSV = os.path.join(PROCESSED_DIR, 'institutional_owners_2025_deep_clean.csv')
CLUSTERS_CSV = os.path.join(PROCESSED_DIR, 'mailing_address_clusters.csv')

OUT_ROLLUP = os.path.join(PROCESSED_DIR, 'high_confidence_rollup.csv')
OUT_CANDIDATES = os.path.join(PROCESSED_DIR, 'candidate_affiliates.csv')
OUT_EDGES = os.path.join(PROCESSED_DIR, 'counterparty_edges.csv')
OUT_WAREHOUSE = os.path.join(PROCESSED_DIR, 'warehouse_score.csv')
OUT_PROMPTS = os.path.join(PROCESSED_DIR, 'llm_verification_prompts.txt')

CORP_PATTERN = re.compile(
    r'\b(LLC|LP|LTD|INC|CORP|TRUST|HOLDINGS|PARTNERS|REIT|FUND|COMPANY|CO\b)',
    re.IGNORECASE,
)


# ── Verified parent map ──────────────────────────────────────────────────
# ONLY entries where the parent is a matter of public record (SEC filing,
# press release, well-known M&A). If you're not sure, leave it blank — the
# LLM verification queue will pick it up. Adding a guess here defeats the
# whole point of the false-flag avoidance design.
VERIFIED_PARENTS = {
    # Tier 1 — buy-to-rent landlords
    "AMH 2014":                     ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AMH 2015":                     ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AMH TX PROPERTIES":            ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AMH ADDISON":                  ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AMH ROMAN":                    ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AH4R PROPERTIES":              ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AH4R I TX":                    ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AH4R 1 TX":                    ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AH4R GP":                      ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AH4R-TX":                      ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AMERICAN HOMES 4 RENT PROPERTIES EIGHT": ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT PROPERTIES TWO":   ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT PROPERTIES ONE":   ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT PROPERTIES II":    ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT LP":     ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT LLC":    ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT TRS":    ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT 2014":   ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT 2015":   ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN HOMES 4 RENT ADVISOR": ("American Homes 4 Rent", "NYSE: AMH"),
    "ARP 2014":                     ("American Homes 4 Rent", "NYSE: AMH"),
    "AMERICAN RESIDENTIAL LEASING": ("American Homes 4 Rent", "NYSE: AMH (predecessor brand)"),
    # Bare-keyword variants that the deep_scan_prop.py keyword list emits
    "AMERICAN HOMES 4 RENT":        ("American Homes 4 Rent", "NYSE: AMH (10-K)"),
    "AH4R":                         ("American Homes 4 Rent", "NYSE: AMH (10-K)"),

    "PROGRESS RESIDENTIAL":         ("Pretium Partners", "press release"),
    "PROGRESS AUSTIN":              ("Pretium Partners", "press release"),
    "PROGRESS RESIDENTIAL BORROWER": ("Pretium Partners", "press release"),
    "PRETIUM":                      ("Pretium Partners", "press release"),
    "PATHLIGHT PROPERTY":           ("Pretium Partners", "press release"),

    "TRICON RESIDENTIAL":           ("Blackstone (Tricon)", "Blackstone 2024 acquisition"),
    "TRICON AMERICAN":              ("Blackstone (Tricon)", "Blackstone 2024 acquisition"),
    "SFR JV-HD":                    ("Blackstone (Tricon)", "Tricon-Blackstone JV"),
    "SFR JV-2":                     ("Blackstone (Tricon)", "Tricon-Blackstone JV"),

    "HPA TEXAS":                    ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HPA BORROWER":                 ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HPA JV":                       ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HPA US":                       ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HP TEXAS":                     ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HOME PARTNERS OF AMERICA":     ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HOME PARTNERS REALTY":         ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),
    "HPA II BORROWER":              ("Blackstone (Home Partners of America)", "Blackstone 2021 acquisition"),

    "INVH LP":                      ("Invitation Homes", "NYSE: INVH (10-K)"),
    "INVITATION HOMES":             ("Invitation Homes", "NYSE: INVH (10-K)"),
    "IH3 LP":                       ("Invitation Homes", "NYSE: INVH (10-K)"),
    "IH4 LP":                       ("Invitation Homes", "NYSE: INVH (10-K)"),
    "IH5 LP":                       ("Invitation Homes", "NYSE: INVH (10-K)"),
    "IH6 LP":                       ("Invitation Homes", "NYSE: INVH (10-K)"),
    "IH BORROWER":                  ("Invitation Homes", "NYSE: INVH (10-K)"),
    "THR PROPERTY":                 ("Invitation Homes", "Starwood Waypoint merger 2017"),
    "STARWOOD WAYPOINT":            ("Invitation Homes", "Starwood Waypoint merger 2017"),

    "BLACKROCK REALTY":             ("BlackRock", "NYSE: BLK"),

    "MAIN STREET RENEWAL":          ("Amherst Holdings", "Amherst press release"),
    "AMHERST HOLDINGS":             ("Amherst Holdings", "Amherst press release"),
    "AMHERST RESIDENTIAL":          ("Amherst Holdings", "Amherst press release"),

    "FIRSTKEY HOMES":               ("Cerberus Capital Management", "Cerberus portfolio"),
    "CERBERUS":                     ("Cerberus Capital Management", "Cerberus portfolio"),
    "CF REAL ESTATE":               ("Cerberus Capital Management", "Cerberus FirstKey filings"),

    # Tier 3 — historical exiters
    "ZILLOW HOMES":                 ("Zillow (exited 2021)", "Zillow Offers shutdown"),
    "ORCHARD PROPERTY":             ("Orchard (exited)", "Orchard pivot 2023"),
    "REDFINNOW BORROWER":           ("Redfin (exited 2022)", "RedfinNow shutdown"),

    # Tier 4 — fix-flip lender REO
    "LENDINGHOME FUNDING":          ("Kiavi", "Kiavi rebrand 2021"),
    "LENDING HOME FUNDING":         ("Kiavi", "Kiavi rebrand 2021"),
    "KIAVI FUNDING":                ("Kiavi", "Kiavi public branding"),
    "TOORAK CAPITAL PARTNERS":      ("Toorak Capital (KKR-backed)", "KKR portfolio page"),
    "TOORAK REAL ESTATE HOLDINGS":  ("Toorak Capital (KKR-backed)", "KKR portfolio page"),
    "TOORAK CAPITAL":               ("Toorak Capital (KKR-backed)", "KKR portfolio page"),
    "FRONT YARD RESIDENTIAL":       ("Pretium Partners", "Pretium 2021 acquisition press release"),
    "PURCHASING FUND":              ("Kiavi", "deed counterparty analysis: 52 cross-tx with LendingHome Funding Corp"),

    # ── Gemini Deep Research verifications (HIGH confidence) ─────────────
    "ANCHOR LOANS":                 ("Pretium Partners", "https://www.anchorloans.com/blog/anchor-loans-is-acquired-by-pretium (Nov 2021 acquisition)"),
    "HOUSEMAX FUNDING":             ("Hunt Companies, Inc.", "https://www.huntcompanies.com/news/american-community-investor-expands-its-specialty-finance-platform"),
    "CARMA PROPERTIES WESTPORT":    ("Brookfield Residential", "Austin city planning data + Brookfield Residential / Carma Developers historical lineage"),
    "LNV CORPORATION":              ("Beal Financial Corporation", "https://www.sec.gov/Archives/edgar/data/946482/000121390020013958/ea122060-sc13gbeal_uswell.htm (SEC 13G)"),
    "GENESIS CAPITAL":              ("Rithm Capital", "https://genesiscapital.com/wp-content/uploads/2021/10/New-Residential-Investment-Corp.-to-Acquire-Genesis.pdf (NYSE: RITM, formerly New Residential)"),
    "DOMINION FINANCIAL SERVICES":  ("Dominion Group", "https://dominionfinancialservices.com/about/ (founded by Fred Lewis)"),
    "RCN CAPITAL":                  ("RCN Capital LLC (independent)", "https://rcncapital.com/about-rcn-capital (no external parent identified)"),
    "PARK PLACE FINANCE":           ("Park Place Finance LLC (independent)", "https://parkplacefinance.com/about/ (Justin Hubbert, founder)"),
    "CRP/ARGYLE GUTHRIE":           ("The Carlyle Group", "https://www.bafin.de/SharedDocs/Downloads/DE/Angebotsunterlage/SNP2.pdf (BaFin disclosure: CRP = Carlyle Realty Partners)"),
    "GUTHRIE PROPERTY":             ("The Carlyle Group", "BaFin disclosure: Carlyle/Argyle Guthrie joint venture structure"),
    "CALCAP LENDING":               ("California Capital Real Estate Advisors, Inc.", "CALCAP corporate newsletter listing CALCAP Lending as affiliate"),
    "FIREBIRD SFE":                 ("Pretium Partners", "SEC 8-K Altisource acquisition (https://www.sec.gov/Archives/edgar/data/1555039/000119312516728741/d151846d8k.htm); chain: Altisource → Front Yard Residential 2018 → Pretium 2021"),
    "SFR II BORROWER":              ("Blackstone (Home Partners of America)", "https://search.wcad.org/Property-Detail/PropertyQuickRefID=R480238 (tax records map to HPA address)"),
    "SFR BORROWER 2022":            ("Blackstone (Home Partners of America)", "https://hjlawfirm.com/wp-content/uploads/2024/02/DKT-1-Complaint-12-22-23-2-Illinois.pdf (court complaint identifies SPV as HPA)"),

    # ── Gemini Deep Research verifications (MEDIUM confidence) ───────────
    "MERCHANTS FUNDING":            ("Merchants Mortgage & Trust Corporation [MEDIUM]", "Utah/Arizona regulatory abstracts linking DBA"),
    "SFR ACQUISITIONS":             ("Blackstone (Home Partners of America) [MEDIUM]", "Chicago mailing matches HPA HQ; court complaint corroboration"),
    "SFR BORROWER 2021":            ("Blackstone (Home Partners of America) [MEDIUM]", "Naming convention + shared HPA Chicago HQ; court complaint corroboration"),
    "TARBERT LLC":                  ("Invitation Homes [MEDIUM]", "https://caselaw.findlaw.com/court/tx-court-of-appeals/2104003.html (Tarbert LLC and Starwood Waypoint TRS LLC named co-defendant landlords); chain: Starwood Waypoint → Invitation Homes 2017 merger"),
    "HOME OPTION CAPITAL":          ("Capital Management Services, LP [MEDIUM]", "Corporate job postings list Home Option Capital under CMS"),
    "TRANS AM SFE":                 ("Amherst Holdings [MEDIUM]", "Tax records show TRANS AM SFE II LLC operates alongside CPI AMHERST SFR PROGRAM OWNER LLC"),
}


def normalize_addr(addr):
    """Light normalization for cluster matching. Lowercase, collapse whitespace,
    strip 'STE/SUITE' suffixes that vary in formatting."""
    if not addr:
        return ''
    a = re.sub(r'\s+', ' ', addr.upper().strip())
    a = re.sub(r'\b(STE|SUITE|UNIT|#)\s*[\w-]+', '', a).strip()
    a = re.sub(r'\s+', ' ', a)
    return a


def is_corporate(name):
    return bool(CORP_PATTERN.search(name or ''))


def clean_name(name):
    return re.sub(r'\s+', ' ', (name or '').strip())


# ─────────────────────────────────────────────────────────────────────────
# Step 1: Read deeds → counterparty edges
# ─────────────────────────────────────────────────────────────────────────
def load_deeds():
    """Build the deed-side index.

    CRITICAL false-flag rule: an entity is only assigned a keyword bucket if
    the keyword is a substring of the entity's own name. The Search_Keyword
    column reflects the *search query that returned the row*, not what the
    counterparty is. If TOORAK appears as grantor in a deed found by querying
    "PROGRESS RESIDENTIAL", TOORAK is NOT in the PROGRESS bucket — it just
    happens to have transacted with one.
    """
    edges = defaultdict(int)         # (entity_a, entity_b) → tx_count
    keyword_by_entity = {}           # entity → keyword (only if substring match)
    deed_dates_by_entity = defaultdict(list)
    rows = []

    with open(DEEDS_CSV) as f:
        for row in csv.DictReader(f):
            grantee = clean_name(row['Grantee_E']).rstrip(';').strip()
            grantor = clean_name(row['Grantor_R']).rstrip(';').strip()
            kw = row['Search_Keyword']
            kw_upper = kw.upper()
            date = row['Date_Filed']

            for entity in (grantee, grantor):
                if entity and is_corporate(entity):
                    # Only assign the keyword if it actually appears in the
                    # entity's name. Otherwise leave the bucket empty — this
                    # entity is a counterparty, not a member of the bucket.
                    if kw_upper in entity.upper() and entity not in keyword_by_entity:
                        keyword_by_entity[entity] = kw
                    deed_dates_by_entity[entity].append(date)

            if grantee and grantor and is_corporate(grantee) and is_corporate(grantor):
                # Undirected pair (sort for canonical key) — but track direction in row dump
                pair = tuple(sorted([grantee, grantor]))
                edges[pair] += 1

            rows.append({
                'keyword': kw,
                'grantee': grantee,
                'grantor': grantor,
                'date': date,
                'doc_type': row['Document_Type'],
                'instrument': row['Instrument_Number'],
            })

    return edges, keyword_by_entity, deed_dates_by_entity, rows


# ─────────────────────────────────────────────────────────────────────────
# Step 2: Read owners CSV → mailing addresses + property counts
# ─────────────────────────────────────────────────────────────────────────
def load_owners():
    mailing_by_entity = {}        # entity → raw mailing
    norm_by_entity = {}           # entity → normalized mailing
    keyword_by_entity = {}        # entity → match_reason keyword (if any)
    properties_by_entity = defaultdict(list)  # entity → [property_id, ...]
    address_by_property = {}      # property_id → property_address

    with open(OWNERS_CSV) as f:
        for row in csv.DictReader(f):
            entity = clean_name(row['Owner_Name'])
            if not entity:
                continue
            mailing = clean_name(row['Mailing_Address'])
            mailing_by_entity[entity] = mailing
            norm_by_entity[entity] = normalize_addr(mailing)
            properties_by_entity[entity].append(row['Property_ID'])
            address_by_property[row['Property_ID']] = row['Property_Address']

            mr = row.get('Match_Reason', '')
            m = re.match(r'Keyword:\s*(.+)', mr)
            if m:
                keyword_by_entity[entity] = m.group(1).strip()

    return mailing_by_entity, norm_by_entity, keyword_by_entity, properties_by_entity, address_by_property


# ─────────────────────────────────────────────────────────────────────────
# Step 3: Read mailing-cluster sizes
# ─────────────────────────────────────────────────────────────────────────
def load_clusters():
    by_addr = {}
    with open(CLUSTERS_CSV) as f:
        for row in csv.DictReader(f):
            by_addr[normalize_addr(row['Mailing_Address'])] = int(row['Num_Entities'])
    return by_addr


# ─────────────────────────────────────────────────────────────────────────
# Step 4: Write the high-confidence rollup
# ─────────────────────────────────────────────────────────────────────────
def write_rollup(deed_keyword_by_entity, owner_keyword_by_entity, mailing_by_entity,
                 properties_by_entity, deed_dates_by_entity, cluster_sizes, norm_by_entity):
    all_entities = set(deed_keyword_by_entity) | set(owner_keyword_by_entity)

    rollup_rows = []
    for entity in sorted(all_entities):
        kw = owner_keyword_by_entity.get(entity) or deed_keyword_by_entity.get(entity, '')
        verified, source = VERIFIED_PARENTS.get(kw, ('', ''))
        mailing = mailing_by_entity.get(entity, '')
        norm = norm_by_entity.get(entity, '') or normalize_addr(mailing)
        cluster = cluster_sizes.get(norm, 1) if norm else 1
        n_props = len(properties_by_entity.get(entity, []))
        n_deeds = len(deed_dates_by_entity.get(entity, []))

        rollup_rows.append({
            'entity':           entity,
            'bucket_keyword':   kw,
            'verified_parent':  verified,
            'source':           source,
            'n_properties':     n_props,
            'n_deeds':          n_deeds,
            'mailing_address':  mailing,
            'mailing_cluster':  cluster,
        })

    # Sort: known parents first, then by deed volume
    rollup_rows.sort(key=lambda r: (r['verified_parent'] == '', -r['n_deeds'], r['entity']))

    with open(OUT_ROLLUP, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rollup_rows[0].keys()))
        w.writeheader()
        w.writerows(rollup_rows)

    return rollup_rows


# ─────────────────────────────────────────────────────────────────────────
# Step 5: Write candidate affiliates (multi-signal)
# ─────────────────────────────────────────────────────────────────────────
def write_candidates(edges, norm_by_entity, cluster_sizes, owner_keyword_by_entity):
    """A pair is flagged ONLY when all three signals fire:
       - ≥5 cross-transactions
       - identical normalized mailing
       - mailing cluster of ≥3 corporate entities
    """
    candidates = []
    for (a, b), n in edges.items():
        if n < 5:
            continue
        addr_a = norm_by_entity.get(a)
        addr_b = norm_by_entity.get(b)
        if not addr_a or addr_a != addr_b:
            continue
        cluster = cluster_sizes.get(addr_a, 0)
        if cluster < 3:
            continue

        # Heuristic flag: if one side has a known bucket keyword and the other
        # doesn't, the unknown side is the candidate to investigate.
        kw_a = owner_keyword_by_entity.get(a, '')
        kw_b = owner_keyword_by_entity.get(b, '')

        candidates.append({
            'entity_a': a,
            'entity_b': b,
            'cross_transactions': n,
            'shared_mailing': addr_a,
            'mailing_cluster_size': cluster,
            'entity_a_known_bucket': kw_a,
            'entity_b_known_bucket': kw_b,
            'recommendation': 'verify via Texas SOS or Gemini Deep Research',
        })

    candidates.sort(key=lambda r: -r['cross_transactions'])

    with open(OUT_CANDIDATES, 'w', newline='') as f:
        if candidates:
            w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
            w.writeheader()
            w.writerows(candidates)
        else:
            f.write('# No candidate pairs satisfied all three signals.\n')

    return candidates


# ─────────────────────────────────────────────────────────────────────────
# Step 6: Write counterparty edges (raw)
# ─────────────────────────────────────────────────────────────────────────
def write_edges(edges):
    sorted_edges = sorted(edges.items(), key=lambda kv: -kv[1])
    with open(OUT_EDGES, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['entity_a', 'entity_b', 'transaction_count'])
        for (a, b), n in sorted_edges:
            w.writerow([a, b, n])


# ─────────────────────────────────────────────────────────────────────────
# Step 7: Warehouse score per property
# ─────────────────────────────────────────────────────────────────────────
TIER4_KEYWORDS = {
    "TOORAK CAPITAL PARTNERS", "TOORAK REAL ESTATE HOLDINGS", "TOORAK CAPITAL",
    "LENDINGHOME FUNDING", "LENDING HOME FUNDING", "KIAVI FUNDING",
    "TUSKER CAPITAL FUND", "GENESIS CAPITAL", "HOUSEMAX FUNDING",
    "PARK PLACE FINANCE", "PATCH OF LAND LENDING", "RCN CAPITAL",
    "CALCAP LENDING", "ANCHOR LOANS", "DOMINION FINANCIAL SERVICES",
    "MERCHANTS FUNDING", "HOMEWARD PROPERTIES", "PURCHASING FUND",
    "CARMA PROPERTIES WESTPORT",
}


def build_tier4_buyer_set(deed_rows):
    """Return set of entities that ever appeared as a grantee in a deed
    where the grantor's NAME actually contains a Tier 4 keyword. This is
    'bought from a fix-flip lender' — the cleanest warehouse-pipeline signal.

    We check the grantor's name directly (not the deed's Search_Keyword)
    because Search_Keyword reflects the query that returned the row, not
    which side of the deed the keyword refers to.
    """
    buyers = set()
    for row in deed_rows:
        grantor_upper = (row['grantor'] or '').upper()
        if not grantor_upper:
            continue
        if any(kw in grantor_upper for kw in TIER4_KEYWORDS):
            if row['grantee'] and is_corporate(row['grantee']):
                buyers.add(row['grantee'])
    return buyers


def write_warehouse_score(owner_keyword_by_entity, properties_by_entity,
                          mailing_by_entity, norm_by_entity, cluster_sizes,
                          address_by_property, tier4_buyers):
    """Score each property by independent signals (each worth +1):
       1. Current owner is in Tier 4 (lender REO list)
       2. Owner ever bought from a Tier 4 lender (deed graph)
       3. Mailing cluster ≥5 corporate entities
       4. Owner holds ≥5 properties (concentration)
       Max score = 4. Threshold ≥2 = candidate, ≥3 = strong.

       NOTE: developers/homebuilders are flagged separately so they don't
       drown the list — they show up as concentrated owners but aren't
       institutional landlords.
    """
    DEV_PATTERN = re.compile(
        r'\b(DEVELOPMENT|TRACT|HOMEBUILDER|HOMES INC|HOMES LLC|BUILDERS|'
        r'CONSTRUCTION|RANCH|MASTER COMMUNITY|LOT OPTION|SUBDIVISION)\b',
        re.IGNORECASE,
    )

    rows = []
    for entity, prop_ids in properties_by_entity.items():
        kw = owner_keyword_by_entity.get(entity, '')
        norm = norm_by_entity.get(entity, '')
        cluster = cluster_sizes.get(norm, 1) if norm else 1
        is_developer = bool(DEV_PATTERN.search(entity))

        score = 0
        signals = []
        if kw in TIER4_KEYWORDS:
            score += 1
            signals.append(f'tier4-owner:{kw}')
        if entity in tier4_buyers:
            score += 1
            signals.append('bought-from-tier4-lender')
        if cluster >= 5:
            score += 1
            signals.append(f'cluster:{cluster}')
        if len(prop_ids) >= 5:
            score += 1
            signals.append(f'concentration:{len(prop_ids)}')

        if score == 0:
            continue

        for pid in prop_ids:
            rows.append({
                'property_id':       pid,
                'property_address':  address_by_property.get(pid, ''),
                'owner':             entity,
                'bucket_keyword':    kw,
                'warehouse_score':   score,
                'signals':           '; '.join(signals),
                'is_developer_likely': 'YES' if is_developer else '',
                'mailing_address':   mailing_by_entity.get(entity, ''),
            })

    # Sort: non-developers first (institutional), then by score, then owner
    rows.sort(key=lambda r: (r['is_developer_likely'] == 'YES', -r['warehouse_score'], r['owner']))

    with open(OUT_WAREHOUSE, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    return rows


# ─────────────────────────────────────────────────────────────────────────
# Step 8: LLM verification prompts
# ─────────────────────────────────────────────────────────────────────────
def write_llm_prompts(rollup_rows):
    """Emit ONE consolidated Gemini Deep Research prompt that asks for all
    unverified buckets in a single batch and demands a parseable table back.
    The single-prompt format is more token-efficient and lets Deep Research
    treat the whole thing as one research task with N sub-targets.
    """
    by_bucket = defaultdict(list)
    for r in rollup_rows:
        if not r['bucket_keyword']:
            continue
        by_bucket[r['bucket_keyword']].append(r)

    unverified = [(kw, rs) for kw, rs in by_bucket.items()
                  if not VERIFIED_PARENTS.get(kw)]
    unverified.sort(key=lambda kv: -sum(int(r['n_deeds'] or 0) for r in kv[1]))

    with open(OUT_PROMPTS, 'w') as f:
        # ── Header / context ─────────────────────────────────────────
        f.write("# CONTEXT\n\n")
        f.write("I am building a public-interest dataset on institutional ownership of\n")
        f.write("single-family homes in Travis County, Texas (Austin). I have scraped\n")
        f.write("the county clerk's deed records and grouped corporate entities into\n")
        f.write(f"buckets by name pattern. The {len(unverified)} buckets below need to be linked\n")
        f.write("to their ultimate corporate parent — the publicly-traded REIT, PE firm,\n")
        f.write("fund, or operating company that controls them. Each bucket represents a\n")
        f.write("group of LLCs/LPs that appear to be coordinated based on naming and\n")
        f.write("counterparty patterns in deed records.\n\n")

        # ── Rules (stated once) ───────────────────────────────────────
        f.write("# RULES\n\n")
        f.write("1. For each bucket, identify the ultimate corporate parent.\n")
        f.write("2. CITE A SOURCE for every answer. Acceptable sources, in order of\n")
        f.write("   preference:\n")
        f.write("     - SEC EDGAR filings (10-K, 10-Q, S-1, ABS-EE, prospectus)\n")
        f.write("     - Company press release\n")
        f.write("     - Major news outlet (WSJ, Bloomberg, Reuters, FT, NYT)\n")
        f.write("     - Crunchbase, Pitchbook, or PE firm portfolio page (lower confidence)\n")
        f.write("3. If you cannot find a citable source, write 'UNKNOWN' for the parent\n")
        f.write("   and 'no_public_source' for the URL. DO NOT GUESS based on naming\n")
        f.write("   similarity. A wrong answer is worse than no answer.\n")
        f.write("4. For securitization SPVs (e.g., 'BORROWER 2021-1' style names), the\n")
        f.write("   sponsor is named in the EDGAR ABS-EE filing — that is the parent.\n")
        f.write("5. Confidence rating: HIGH (SEC filing or press release), MEDIUM (news\n")
        f.write("   article or PE portfolio page), LOW (only Crunchbase / unconfirmed).\n\n")

        # ── Output format ─────────────────────────────────────────────
        f.write("# OUTPUT FORMAT\n\n")
        f.write("Return a single markdown table with these columns and nothing else\n")
        f.write("after the table (no commentary, no preamble):\n\n")
        f.write("| bucket | parent | confidence | source_url | notes |\n")
        f.write("|---|---|---|---|---|\n")
        f.write("| EXAMPLE BUCKET | Example Parent Inc | HIGH | https://www.sec.gov/... | brief context |\n\n")
        f.write("- One row per bucket, in the same order I list them below.\n")
        f.write("- If a bucket has multiple plausible parents, pick the most likely and\n")
        f.write("  list the alternatives in the notes column.\n")
        f.write("- Keep notes under 25 words.\n\n")

        # ── Buckets table ─────────────────────────────────────────────
        f.write("# BUCKETS TO RESEARCH\n\n")
        for i, (kw, rs) in enumerate(unverified, 1):
            sample_entities = [r['entity'] for r in rs[:6]]
            sample_mailings = list({r['mailing_address'] for r in rs if r['mailing_address']})[:3]
            n_deeds_total = sum(int(r['n_deeds'] or 0) for r in rs)

            f.write(f"## {i}. `{kw}`\n")
            f.write(f"   - {len(rs)} entities, {n_deeds_total} deed events\n")
            f.write(f"   - Sample entities:\n")
            for e in sample_entities:
                f.write(f"     - {e}\n")
            if sample_mailings:
                f.write(f"   - Mailing addresses observed:\n")
                for m in sample_mailings:
                    f.write(f"     - {m}\n")
            f.write("\n")

        f.write("# END OF BUCKETS\n\n")
        f.write("Now produce the markdown table per the OUTPUT FORMAT rules above.\n")
        f.write("Remember: cite a source for every row, write UNKNOWN if you cannot,\n")
        f.write("and never guess based on naming similarity.\n")

    return len(unverified)


# ─────────────────────────────────────────────────────────────────────────
def main():
    print("Loading deeds...")
    edges, deed_kw, deed_dates, deed_rows = load_deeds()
    print(f"  {len(edges):,} unique entity pairs, {len(deed_kw):,} corporate entities")

    print("Loading owners...")
    mailing, norm, owner_kw, properties, addresses = load_owners()
    print(f"  {len(mailing):,} entities with current property ownership")

    print("Loading mailing clusters...")
    cluster_sizes = load_clusters()
    print(f"  {len(cluster_sizes):,} cluster addresses")

    print("\nWriting high-confidence rollup...")
    rollup = write_rollup(deed_kw, owner_kw, mailing, properties, deed_dates, cluster_sizes, norm)
    verified_count = sum(1 for r in rollup if r['verified_parent'])
    print(f"  {len(rollup):,} entities → {OUT_ROLLUP}")
    print(f"  {verified_count:,} have a publicly verified parent")

    print("\nFinding candidate affiliates (3-signal)...")
    candidates = write_candidates(edges, norm, cluster_sizes, owner_kw)
    print(f"  {len(candidates):,} candidate pairs → {OUT_CANDIDATES}")

    print("\nWriting raw counterparty edges...")
    write_edges(edges)
    print(f"  → {OUT_EDGES}")

    print("\nScoring properties for warehousing...")
    tier4_buyers = build_tier4_buyer_set(deed_rows)
    print(f"  {len(tier4_buyers):,} entities ever bought from a Tier 4 lender")
    warehouse = write_warehouse_score(owner_kw, properties, mailing, norm, cluster_sizes,
                                      addresses, tier4_buyers)
    high = sum(1 for r in warehouse if r['warehouse_score'] >= 2 and not r['is_developer_likely'])
    strong = sum(1 for r in warehouse if r['warehouse_score'] >= 3 and not r['is_developer_likely'])
    print(f"  {len(warehouse):,} properties scored, {high:,} candidates (≥2), {strong:,} strong (≥3)")
    print(f"  → {OUT_WAREHOUSE}")

    print("\nGenerating LLM verification prompts...")
    n_prompts = write_llm_prompts(rollup)
    print(f"  {n_prompts:,} buckets need parent verification → {OUT_PROMPTS}")

    print("\nDone.")


if __name__ == '__main__':
    main()
