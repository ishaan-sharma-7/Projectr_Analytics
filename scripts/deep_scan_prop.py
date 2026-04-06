"""
Deep scan of PROP.TXT for institutional SFR ownership.

Two-pass approach:
  Pass 1 — Scan all lines. Apply expanded keyword matching AND collect every
           (mailing_address_hash → set of owner names) for all LLC/LP entities.
           Identify mailing addresses that cluster 10+ different entities.
  Pass 2 — Re-scan. Flag properties that match expanded keywords OR whose
           mailing address was identified as an institutional cluster.

Streams line-by-line. Never loads the full file into memory.
Run, extract, then delete PROP.TXT.

Usage:
  python3 deep_scan_prop.py [path_to_PROP.TXT]
  Default: ../raw_tcad_data/PROP.TXT
"""

import csv
import re
import sys
import os
import time
from collections import defaultdict, Counter

# ============================================================
# CONFIGURATION
# ============================================================

# --- Layer A: Expanded keyword list ---
KEYWORDS = [
    # American Homes 4 Rent
    "AMERICAN HOMES 4 RENT",
    "AMH 2014", "AMH 2015", "AMH 2016", "AMH 2017", "AMH 2018",
    "AMH TX PROPERTIES", "AMH ADDISON",
    "AH4R",
    "AMERICAN HOMES 4 RENT PROPERTIES",
    "AMERICAN HOMES 4 RENT TRS",

    # Invitation Homes (primary gap — should catch many more)
    "INVITATION HOMES",
    "INVH",                         # Their primary LLC prefix in Texas
    "IH PROPERTY",                  # IH Property Texas LP
    "IH BORROWER",                  # Securitization trust entities
    "IH2 LP", "IH3 LP", "IH4 LP", "IH5 LP", "IH6 LP",
    "THR PROPERTY",                 # Pre-merger Starwood entity
    "STARWOOD WAYPOINT",            # Legacy name
    "PREEMINENT HOLDINGS",
    "INVITATION HOMES OPERATING",

    # Progress Residential
    "PROGRESS RESIDENTIAL",
    "PROGRESS AUSTIN",
    "PRETIUM",                      # Parent company
    "FRONT YARD RESIDENTIAL",       # Legacy name

    # Tricon
    "TRICON RESIDENTIAL",
    "TRICON AMERICAN HOMES",
    "SFR JV-HD",                    # Their borrower LLC pattern

    # FirstKey Homes (Cerberus Capital — currently finding zero)
    "FIRSTKEY HOMES",
    "FIRST KEY HOMES",
    "CERBERUS",
    "CF REAL ESTATE",

    # BlackRock
    "BLACKROCK REALTY ADVISORS",
    "GUTHRIE PROPERTY OWNER",

    # Main Street Renewal
    "MAIN STREET RENEWAL",

    # Home Partners of America (Blackstone) — 2025 Q4 deed scrape confirmed
    "HPA TEXAS",                    # HPA TEXAS SUB 2017-1 LLC etc.
    "HPA BORROWER",
    "HOME PARTNERS OF AMERICA",

    # New institutional owners discovered in deed records
    "RH PARTNERS OWNERCO",          # buying from Main Street Renewal
    "SOUTH LAMAR VENTURE",          # c/o BlackRock Realty Advisors

    # Amherst Holdings (institutional SFR)
    "AMHERST HOLDINGS",
    "AMHERST RESIDENTIAL",

    # Other known institutional SFR operators
    "VINEBROOK HOMES",
    "MYND MANAGEMENT",
    "PATHLIGHT PROPERTY",
    "SYLVAN HOMES",
    "FUNDRISE",
    "ARRIVED HOMES",
    "ROOFSTOCK",
]

# --- Layer B: Mailing address ZIP clusters (known HQs) ---
# Format: (zip, state_abbrev) — require state match to avoid substring false positives
KNOWN_HQ_ZIPS = {
    ("75201", "TX"),   # Invitation Homes — Dallas
    ("75202", "TX"),   # Invitation Homes — Dallas (alternate)
    ("75204", "TX"),   # Invitation Homes — Dallas (alternate)
    ("85256", "AZ"),   # Progress Residential — Scottsdale
    ("91302", "CA"),   # American Homes 4 Rent — Calabasas
    ("91301", "CA"),   # AMH — Agoura Hills
    ("89119", "NV"),   # AMH — Las Vegas
    ("30328", "GA"),   # Pretium/Progress — Atlanta
    ("30004", "GA"),   # FirstKey Homes — Alpharetta
    ("30009", "GA"),   # FirstKey Homes — Alpharetta (alternate)
    ("60606", "IL"),   # Cerberus — Chicago
}

# Corporate entity pattern — required for zip-based matches
CORP_PATTERN = re.compile(r'\b(LLC|L\.?P\.?|BORROWER|INC|CORP|TRUST|HOLDINGS|PROPERTIES|PARTNERS)\b', re.IGNORECASE)

# False positive filters
FALSE_POS_NAMES = re.compile(
    r'AMHERST\s+(DR|AVE|ST|CT|LN|RD|BND|CIR|WAY|BLVD)|'
    r'BLACK\s+ROCK\s+(BND|DR|LN|CT|WAY|TRL)|'
    r'IH\s*35|IH-35|'
    r'PERSONAL PROPERTY|'
    r'WELLS FARGO|7-ELEVEN|BAPTIST CHURCH',
    re.IGNORECASE
)

# ============================================================
# PROP.TXT FIELD POSITIONS (fixed-width)
# ============================================================
# Verified positions from TCAD 2025 certified export:
#   0-12:     Property ID (numeric + "R" suffix)
#   596-607:  Owner entity number (numeric, skip)
#   608-677:  Owner name (70 chars)
#   678-692:  Flag field ("F000000000000", skip)
#   693-752:  Mailing line 1
#   753-872:  Mailing line 2
#   873-922:  Mailing city
#   923-977:  Mailing state
#   978-988:  Mailing zip (5+4 digits)
#   989-990:  Flag ("FF", skip)
#   1011:     Situs flag (Y/N)
#   1039-1048: Situs direction prefix (S, N, E, W)
#   1049-1094: Situs street name
#   1095-1138: Situs suffix (BLVD, ST, DR, etc.)
#   1139-1144: Situs zip
# NOTE: Situs house number is NOT in PROP.TXT. Use EARS CSV for full addresses.
def parse_line(line):
    """Extract key fields from a PROP.TXT fixed-width line."""
    if len(line) < 700:
        return None

    # Property ID: positions 0-12, strip "R" suffix and leading zeros
    prop_id_raw = line[0:13].strip().replace("R", "").lstrip("0")
    if not prop_id_raw:
        prop_id_raw = line[0:13].strip()

    # Owner name: positions 608-677 (after entity number, before flag field)
    owner_name = re.sub(r'\s+', ' ', line[608:678]).strip()

    # Mailing address fields
    mail_line1 = line[693:753].strip()
    mail_line2 = line[753:873].strip()
    mail_city = line[873:923].strip()
    mail_state = line[923:978].strip()
    mail_zip_raw = line[978:989].strip()

    mailing_full = re.sub(r'\s+', ' ', f"{mail_line1} {mail_line2} {mail_city} {mail_state} {mail_zip_raw}").strip()

    # Extract just the 5-digit zip
    mail_zip5 = mail_zip_raw[:5] if len(mail_zip_raw) >= 5 else ""

    # Extract state abbreviation (first 2 non-space chars)
    mail_state_clean = mail_state.strip()[:2]

    # Property address: direction + street + suffix + zip (no house number available)
    situs_dir = line[1039:1049].strip()
    situs_street = line[1049:1095].strip()
    situs_suffix = line[1095:1139].strip()
    situs_zip = line[1139:1145].strip()
    prop_addr = re.sub(r'\s+', ' ', f"{situs_dir} {situs_street} {situs_suffix} {situs_zip}").strip()

    return {
        'prop_id': prop_id_raw,
        'owner_name': owner_name,
        'mailing_full': mailing_full,
        'mail_zip5': mail_zip5,
        'mail_state': mail_state_clean,
        'prop_address': prop_addr,
        'line_upper': line.upper(),
    }


# ============================================================
# PASS 1: Keyword scan + mailing address collection
# ============================================================
def pass1(filepath):
    """First pass: keyword matches + build mailing address clusters."""
    print(f"[Pass 1] Scanning {filepath} for keywords + building address clusters...")
    start = time.time()

    keyword_matches = {}       # prop_id → (owner, mailing, prop_addr, reason)
    mail_clusters = defaultdict(set)  # mail_address_key → {owner_names}
    total_lines = 0
    keyword_count = 0

    with open(filepath, 'r', encoding='latin1') as f:
        for line in f:
            total_lines += 1

            parsed = parse_line(line)
            if not parsed:
                continue

            line_upper = parsed['line_upper']
            owner_upper = parsed['owner_name'].upper()

            # --- Skip known false positives ---
            if FALSE_POS_NAMES.search(line_upper):
                # But still allow if a strong keyword matches in the owner name specifically
                strong_match = False
                for kw in KEYWORDS:
                    if kw in owner_upper:
                        strong_match = True
                        break
                if not strong_match:
                    continue

            # --- Layer A: Keyword matching ---
            match_reason = None
            for kw in KEYWORDS:
                if kw in line_upper:
                    match_reason = f"Keyword: {kw}"
                    break

            # --- Layer B: Known HQ zip matching ---
            if not match_reason and parsed['mail_zip5'] and parsed['mail_state']:
                for hz, hs in KNOWN_HQ_ZIPS:
                    if parsed['mail_zip5'] == hz and parsed['mail_state'].upper().startswith(hs[:2]):
                        if CORP_PATTERN.search(parsed['owner_name']):
                            match_reason = f"HQ Zip: {hz} ({hs})"
                            break

            if match_reason:
                keyword_matches[parsed['prop_id']] = (
                    parsed['owner_name'],
                    parsed['mailing_full'],
                    parsed['prop_address'],
                    match_reason,
                )
                keyword_count += 1

            # --- Collect mailing clusters for ALL corporate entities ---
            if CORP_PATTERN.search(parsed['owner_name']) and parsed['mailing_full']:
                # Key by mailing address (normalized: uppercase, stripped)
                mail_key = re.sub(r'\s+', ' ', parsed['mailing_full'].upper()).strip()
                if len(mail_key) > 10:  # ignore garbage/empty
                    mail_clusters[mail_key].add(parsed['owner_name'].upper())

            if total_lines % 500000 == 0:
                print(f"  ...scanned {total_lines:,} lines, {keyword_count:,} keyword matches so far")

    elapsed = time.time() - start
    print(f"[Pass 1] Done. {total_lines:,} lines in {elapsed:.1f}s. {keyword_count:,} keyword matches.")
    return keyword_matches, mail_clusters, total_lines


# ============================================================
# IDENTIFY INSTITUTIONAL CLUSTERS
# ============================================================
def find_clusters(mail_clusters, min_entities=10):
    """Find mailing addresses receiving tax bills for 10+ different entities."""
    clusters = {}
    for mail_key, owners in mail_clusters.items():
        if len(owners) >= min_entities:
            clusters[mail_key] = owners
    return clusters


# ============================================================
# PASS 2: Catch properties mailing to institutional clusters
# ============================================================
def pass2(filepath, keyword_matches, cluster_addresses):
    """Second pass: flag properties whose mailing address matches a cluster."""
    print(f"[Pass 2] Re-scanning for cluster address matches...")
    start = time.time()

    cluster_matches = {}
    total_lines = 0
    new_matches = 0

    with open(filepath, 'r', encoding='latin1') as f:
        for line in f:
            total_lines += 1

            parsed = parse_line(line)
            if not parsed:
                continue

            # Skip if already caught by keywords
            if parsed['prop_id'] in keyword_matches:
                continue

            # Skip false positives
            if FALSE_POS_NAMES.search(parsed['line_upper']):
                continue

            # Check if mailing address matches a cluster
            mail_key = re.sub(r'\s+', ' ', parsed['mailing_full'].upper()).strip()
            if mail_key in cluster_addresses:
                num_entities = len(cluster_addresses[mail_key])
                cluster_matches[parsed['prop_id']] = (
                    parsed['owner_name'],
                    parsed['mailing_full'],
                    parsed['prop_address'],
                    f"Cluster: {num_entities} entities at this mailing address",
                )
                new_matches += 1

            if total_lines % 500000 == 0:
                print(f"  ...scanned {total_lines:,} lines, {new_matches:,} new cluster matches")

    elapsed = time.time() - start
    print(f"[Pass 2] Done in {elapsed:.1f}s. {new_matches:,} additional cluster matches.")
    return cluster_matches


# ============================================================
# OUTPUT
# ============================================================
def write_output(keyword_matches, cluster_matches, cluster_addresses, output_dir):
    """Write results to CSV files."""
    # Combined output
    all_matches = {}
    all_matches.update(keyword_matches)
    all_matches.update(cluster_matches)

    output_file = os.path.join(output_dir, 'institutional_owners_2025_deep.csv')
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Property_ID', 'Owner_Name', 'Mailing_Address', 'Property_Address', 'Match_Reason'])
        for prop_id, (owner, mailing, prop_addr, reason) in sorted(all_matches.items()):
            writer.writerow([prop_id, owner, mailing, prop_addr, reason])

    print(f"\nWrote {len(all_matches):,} properties to {output_file}")

    # Cluster report
    cluster_file = os.path.join(output_dir, 'mailing_address_clusters.csv')
    with open(cluster_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Mailing_Address', 'Num_Entities', 'Sample_Entities'])
        for addr, entities in sorted(cluster_addresses.items(), key=lambda x: -len(x[1])):
            sample = '; '.join(list(entities)[:5])
            writer.writerow([addr, len(entities), sample])

    print(f"Wrote {len(cluster_addresses)} address clusters to {cluster_file}")

    # Summary
    print(f"\n{'='*60}")
    print(f"DEEP SCAN RESULTS")
    print(f"{'='*60}")
    print(f"  Keyword matches:  {len(keyword_matches):,}")
    print(f"  Cluster matches:  {len(cluster_matches):,}")
    print(f"  Total unique:     {len(all_matches):,}")
    print(f"  Address clusters: {len(cluster_addresses)}")

    # Breakdown by reason
    reasons = Counter()
    for _, (_, _, _, reason) in all_matches.items():
        # Simplify reason for grouping
        if reason.startswith("Keyword:"):
            kw = reason.split(":", 1)[1].strip()
            # Group by parent company
            if any(x in kw for x in ["AMH", "AH4R", "AMERICAN HOMES"]):
                reasons["American Homes 4 Rent"] += 1
            elif any(x in kw for x in ["INVH", "INVITATION", "IH ", "IH BORROWER", "IH PROPERTY", "THR PROPERTY", "STARWOOD", "PREEMINENT"]):
                reasons["Invitation Homes"] += 1
            elif any(x in kw for x in ["PROGRESS", "PRETIUM", "FRONT YARD"]):
                reasons["Progress Residential"] += 1
            elif any(x in kw for x in ["TRICON", "SFR JV"]):
                reasons["Tricon"] += 1
            elif any(x in kw for x in ["FIRSTKEY", "FIRST KEY", "CERBERUS", "CF REAL"]):
                reasons["FirstKey Homes"] += 1
            elif any(x in kw for x in ["BLACKROCK", "GUTHRIE"]):
                reasons["BlackRock"] += 1
            elif any(x in kw for x in ["MAIN STREET"]):
                reasons["Main Street Renewal"] += 1
            else:
                reasons[f"Other ({kw})"] += 1
        elif reason.startswith("HQ Zip:"):
            reasons["HQ Zip Match"] += 1
        elif reason.startswith("Cluster:"):
            reasons["Address Cluster (Layer C)"] += 1

    print(f"\nProperties by parent company:")
    for company, count in reasons.most_common():
        print(f"  {company}: {count:,}")


# ============================================================
# MAIN
# ============================================================
def main():
    filepath = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(__file__), '..', 'raw_tcad_data', 'PROP.TXT'
    )

    if not os.path.exists(filepath):
        print(f"ERROR: {filepath} not found.")
        print(f"Download PROP.TXT from https://www.traviscad.org/publicinformation/")
        print(f"Place it in raw_tcad_data/ and run this script again.")
        sys.exit(1)

    output_dir = os.path.join(os.path.dirname(__file__), '..', 'processed_owners')
    os.makedirs(output_dir, exist_ok=True)

    # Pass 1: Keywords + cluster collection
    keyword_matches, mail_clusters, total = pass1(filepath)

    # Identify institutional clusters (10+ different entities at same address)
    cluster_addresses = find_clusters(mail_clusters, min_entities=10)

    print(f"\n[Clusters] Found {len(cluster_addresses)} mailing addresses with 10+ entities:")
    for addr, entities in sorted(cluster_addresses.items(), key=lambda x: -len(x[1]))[:15]:
        print(f"  {len(entities):3d} entities → {addr[:80]}")

    # Pass 2: Catch cluster-based matches
    cluster_matches = pass2(filepath, keyword_matches, cluster_addresses)

    # Write results
    write_output(keyword_matches, cluster_matches, cluster_addresses, output_dir)

    print(f"\nYou can now delete PROP.TXT to free up space.")


if __name__ == '__main__':
    main()
