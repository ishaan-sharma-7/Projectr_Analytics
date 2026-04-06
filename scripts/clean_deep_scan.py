"""
Cleanup for deep_scan_prop.py output.

The deep scan found 3,514 properties but Layer C (address clustering) and
HQ zip matching caught significant noise:
  - HOA management companies (Goodwin Management, neighborhood associations)
  - Commercial REITs (Cousins Properties, Brandywine, Link Logistics)
  - Nonprofits (Foundation Communities)
  - Small local investors sharing a registered agent address
  - Individual homeowners who happen to live near a corporate HQ zip

This script filters to confirmed institutional SFR entities only.
"""

import pandas as pd
import re
import os

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'processed_owners')

# ============================================================
# PATTERNS TO REMOVE
# ============================================================

# HOA / community associations — not investors
HOA_PATTERN = re.compile(
    r'HOMEOWNER|HOME OWNER|HOA\b|ASSOCIATION\b|NEIGHBORHOOD ASSOC|'
    r'COMMUNITY SERVICE|COMMUNITY ASSOC|CIVIC ASSOC|PROPERTY OWNER.*ASSOC',
    re.IGNORECASE
)

# Individual person names (trusts/individuals at HQ zip codes)
# Pattern: First Last (no LLC/LP/INC) — these are individuals, not companies
INDIVIDUAL_PATTERN = re.compile(
    r'^[A-Z]+\s+[A-Z]+\s+(FAMILY|LIFETIME|LIVING|SURVIVORS?)\s+TRUST',
    re.IGNORECASE
)

# Known non-SFR companies that slip through
NON_SFR_COMPANIES = [
    "FIBERLIGHT",
    "WELLS FARGO",
    "7-ELEVEN",
    "BAPTIST CHURCH",
    "MISSIONARY",
    "FOUNDATION COMMUNITIES",
    "HABITAT FOR HUMANITY",
    "COUSINS PROPERTIES",
    "BRANDYWINE REALTY",
    "LINK LOGISTICS",
    "DELL EQUIPMENT",
    "XEROX",
    "PITNEY BOWES",
    "COCA COLA",
    "REDBOX",
    "PENSKE",
    "GRAYHAWK LEASING",
    "NUCO2",
    "ADT LLC",
    "ADP LLC",
    "HEB BEVERAGE",
    "HALLMARK MARKETING",
    "LOOMIS ARMORED",
    "MILESTONE COMMUNITY BUILDERS",
    "MILESTONE DEVELOPMENT",
]

# Cluster addresses that are NOT institutional SFR
# (shared registered agent offices, HOA managers, commercial developers)
NOISE_CLUSTERS = [
    "5900 BALCONES DR STE 100 AUSTIN",      # Shared registered agent, local flippers
    "GOODWIN MANAGEMENT",                     # HOA management company
    "GOODWIN & COMPANY",                      # HOA management company
    "2100 NORTHLAND DR AUSTIN",               # Milestone — homebuilder, not SFR investor
    "COUSINS PROPERTIES",                     # Commercial office REIT
    "BRANDYWINE REALTY",                      # Commercial office REIT
    "LINK LOGISTICS",                         # Industrial warehouse REIT
    "3000 S INTERSTATE 35 STE 300 AUSTIN",   # Foundation Communities — nonprofit
    "5900 BALCONES DR STE 100 AUSTIN TX USA", # Alternate format of same address
]

# Known institutional SFR cluster addresses (KEEP regardless of entity name)
CONFIRMED_SFR_CLUSTERS = [
    "PO BOX 4090 SCOTTSDALE AZ",             # Progress Residential
    "120 S RIVERSIDE PLZ STE 2000 CHICAGO",   # Home Partners of America (Blackstone)
    "23975 PARK SORRENTO",                    # American Homes 4 Rent
    "280 PILOT RD",                           # AMH Las Vegas
    "PO BOX B KINGSVILLE TX",                 # Institutional SFR (property-named LLCs)
    "PO BOX 8127 ROUND ROCK TX",             # Institutional SFR (random-named LLCs)
    "1717 MAIN ST",                           # Invitation Homes Dallas
]

# Corporate entity pattern
CORP_PATTERN = re.compile(r'\b(LLC|L\.?P\.?|BORROWER|INC|CORP|TRUST|HOLDINGS|PROPERTIES)\b', re.IGNORECASE)


def classify_row(row):
    """
    Returns: 'keep', 'remove', or 'review'
    """
    owner = str(row.get('Owner_Name', '')).upper()
    mailing = str(row.get('Mailing_Address', '')).upper()
    reason = str(row.get('Match_Reason', ''))

    # --- Always keep keyword matches (these were directly identified) ---
    if reason.startswith('Keyword:'):
        # But still filter known non-SFR
        for company in NON_SFR_COMPANIES:
            if company.upper() in owner:
                return 'remove'
        return 'keep'

    # --- Filter HOAs ---
    if HOA_PATTERN.search(owner):
        return 'remove'

    # --- Filter known non-SFR companies ---
    for company in NON_SFR_COMPANIES:
        if company.upper() in owner or company.upper() in mailing:
            return 'remove'

    # --- Filter noise clusters ---
    for noise_addr in NOISE_CLUSTERS:
        if noise_addr.upper() in mailing:
            return 'remove'

    # --- Keep confirmed SFR clusters ---
    for sfr_addr in CONFIRMED_SFR_CLUSTERS:
        if sfr_addr.upper() in mailing:
            return 'keep'

    # --- For HQ zip matches, filter individuals ---
    if reason.startswith('HQ Zip:'):
        # Remove individual/family trusts
        if INDIVIDUAL_PATTERN.search(owner):
            return 'remove'
        # Remove if owner doesn't look corporate
        if not CORP_PATTERN.search(owner):
            return 'remove'
        return 'keep'

    # --- For remaining cluster matches, keep if owner is corporate entity ---
    if reason.startswith('Cluster:'):
        if not CORP_PATTERN.search(owner):
            return 'remove'
        if INDIVIDUAL_PATTERN.search(owner):
            return 'remove'
        return 'keep'

    return 'keep'


def main():
    input_file = os.path.join(PROCESSED_DIR, 'institutional_owners_2025_deep.csv')
    output_file = os.path.join(PROCESSED_DIR, 'institutional_owners_2025_deep_clean.csv')

    df = pd.read_csv(input_file, dtype=str)
    original_count = len(df)

    print(f"Input: {original_count:,} properties")

    # Classify each row
    df['_action'] = df.apply(classify_row, axis=1)

    removed = df[df['_action'] == 'remove']
    kept = df[df['_action'] != 'remove'].drop(columns=['_action'])

    # Deduplicate by Property_ID
    before_dedup = len(kept)
    kept = kept.drop_duplicates(subset=['Property_ID'], keep='first')
    dupes = before_dedup - len(kept)

    # Write cleaned output
    kept.to_csv(output_file, index=False)

    print(f"Removed:     {len(removed):,} (noise)")
    print(f"Duplicates:  {dupes}")
    print(f"Clean total: {len(kept):,} properties → {os.path.basename(output_file)}")

    # Breakdown by match type
    print(f"\nBy match reason:")
    for reason_prefix in ['Keyword:', 'HQ Zip:', 'Cluster:']:
        subset = kept[kept['Match_Reason'].str.startswith(reason_prefix)]
        print(f"  {reason_prefix:12s} {len(subset):,}")

    # Parent company estimation
    print(f"\nBy parent company (estimated):")
    companies = {
        'American Homes 4 Rent': ['AMH', 'AH4R', 'AMERICAN HOMES 4 RENT', 'CALABASAS', '91302', '91301'],
        'Home Partners of America (Blackstone)': ['HPA', 'HEP II', 'SFR ACQUISITIONS', '120 S RIVERSIDE', '60606'],
        'Progress Residential': ['PROGRESS RESIDENTIAL', 'PROGRESS AUSTIN', 'PRETIUM', 'SCOTTSDALE AZ 8526'],
        'Invitation Homes': ['INVH', 'INVITATION HOMES', 'IH BORROWER', 'IH PROPERTY', 'THR PROPERTY', 'STARWOOD'],
        'Tricon': ['TRICON', 'SFR JV-HD'],
        'BlackRock': ['BLACKROCK', 'GUTHRIE PROPERTY'],
        'Main Street Renewal': ['MAIN STREET RENEWAL'],
        'FirstKey Homes': ['FIRSTKEY', 'FIRST KEY', 'CERBERUS'],
    }

    classified = 0
    for company, patterns in companies.items():
        count = 0
        for _, row in kept.iterrows():
            row_text = f"{row.get('Owner_Name','')} {row.get('Mailing_Address','')} {row.get('Match_Reason','')}".upper()
            if any(p.upper() in row_text for p in patterns):
                count += 1
        if count > 0:
            print(f"  {company}: {count:,}")
            classified += count

    unclassified = len(kept) - classified
    if unclassified > 0:
        print(f"  Other/Unclassified: {unclassified:,}")


if __name__ == '__main__':
    main()
