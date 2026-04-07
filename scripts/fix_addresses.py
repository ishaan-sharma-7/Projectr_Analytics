"""
Post-process institutional_owners_2025_deep_clean.csv to fix:
1. Property_ID — strip trailing garbage from PROP.TXT parsing
2. Owner_Name — strip trailing "F000000000000" field bleed
3. Property_Address — replace broken fragments with real addresses from EARS CSV

The PROP.TXT export doesn't include situs house numbers, so property addresses
were truncated (e.g. "Y S LAMAR B" instead of "1201 S LAMAR BLVD 78704").
The EARS CSV has full situs addresses — we join on property ID.
"""

import csv
import os
import re
import sys

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'processed_owners')
RAW_DIR = os.path.join(os.path.dirname(__file__), '..', 'raw_tcad_data')

# EARS CSV files to build address lookup (most recent first)
EARS_FILES = [
    '227EARS082824.csv',   # 2024
    '227EARS083023.csv',   # 2023
    '227EARS092822.csv',   # 2022
    '20210925_000416_PTD.csv',  # 2021
]


def build_address_lookup():
    """Build property_id → situs_address from EARS CSV files."""
    lookup = {}

    for ears_file in EARS_FILES:
        filepath = os.path.join(RAW_DIR, ears_file)
        if not os.path.exists(filepath):
            print(f"  Skipping {ears_file} (not found)")
            continue

        print(f"  Reading {ears_file}...")
        count = 0
        with open(filepath, 'r', encoding='latin1') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) < 10:
                    continue
                prop_id = row[7].strip()
                situs = row[9].strip()
                if prop_id and situs and prop_id not in lookup:
                    lookup[prop_id] = situs
                    count += 1

        print(f"    Added {count:,} new addresses (total: {len(lookup):,})")

    return lookup


def clean_prop_id(raw_id):
    """Extract just the numeric property ID, stripping PROP.TXT format garbage."""
    m = re.match(r'(\d+)', raw_id.strip())
    return m.group(1) if m else raw_id.strip()


def clean_owner_name(raw_owner):
    """Remove the trailing F000... field that bled into the owner name."""
    return re.sub(r'\s+F0{6,}.*$', '', raw_owner).strip()


def clean_mailing_address(raw_mailing):
    """Remove trailing flag character(s) that bled from the next field."""
    # Strip trailing " F" or " FF" from end of mailing address
    return re.sub(r'\s+F{1,2}\s*$', '', raw_mailing).strip()


def build_proptxt_fallback(unmatched_ids):
    """For properties not in EARS, extract partial addresses from PROP.TXT."""
    proptxt = os.path.join(RAW_DIR, 'PROP.TXT')
    if not os.path.exists(proptxt):
        return {}

    print(f"  Looking up {len(unmatched_ids)} remaining IDs in PROP.TXT...")
    target_ids = set(unmatched_ids)
    found = {}

    with open(proptxt, 'r', encoding='latin1') as f:
        for line in f:
            if len(line) < 1145:
                continue
            prop_id = line[0:13].strip().replace('R', '').lstrip('0')
            if not prop_id or prop_id not in target_ids or prop_id in found:
                continue

            situs_dir = line[1039:1049].strip()
            situs_street = line[1049:1095].strip()
            situs_suffix = line[1095:1139].strip()
            situs_zip = line[1139:1145].strip()

            parts = [p for p in [situs_dir, situs_street, situs_suffix, situs_zip] if p]
            addr = ' '.join(parts)
            if addr:
                found[prop_id] = addr

    print(f"    Found {len(found)} partial addresses from PROP.TXT")
    return found


def main():
    input_file = os.path.join(PROCESSED_DIR, 'institutional_owners_2025_deep.csv')
    output_file = os.path.join(PROCESSED_DIR, 'institutional_owners_2025_deep_clean.csv')

    if not os.path.exists(input_file):
        print(f"ERROR: {input_file} not found")
        sys.exit(1)

    # Step 1: Build address lookup from EARS files
    print("Building address lookup from EARS CSV files...")
    address_lookup = build_address_lookup()
    print(f"Total addresses in lookup: {len(address_lookup):,}\n")

    # Step 2: Read and fix the deep_clean CSV (first pass — IDs, names, EARS addresses)
    print("Fixing deep_clean CSV...")
    rows = []
    matched = 0
    unmatched_ids = []

    with open(input_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Fix Property_ID
            row['Property_ID'] = clean_prop_id(row['Property_ID'])

            # Fix Owner_Name
            row['Owner_Name'] = clean_owner_name(row['Owner_Name'])

            # Fix Mailing_Address
            row['Mailing_Address'] = clean_mailing_address(row['Mailing_Address'])

            # Fix Property_Address from EARS lookup
            ears_addr = address_lookup.get(row['Property_ID'], '')
            if ears_addr:
                row['Property_Address'] = ears_addr
                matched += 1
            else:
                unmatched_ids.append(row['Property_ID'])

            rows.append(row)

    # Step 3: For remaining unmatched, try PROP.TXT partial addresses
    if unmatched_ids:
        fallback = build_proptxt_fallback(unmatched_ids)
        fallback_matched = 0
        for row in rows:
            if row['Property_ID'] in fallback and (
                row['Property_Address'].startswith('Y ') or len(row['Property_Address']) < 10
            ):
                row['Property_Address'] = fallback[row['Property_ID']]
                fallback_matched += 1
        matched += fallback_matched
        still_unmatched = len(unmatched_ids) - fallback_matched
    else:
        still_unmatched = 0

    # Step 4: Clean any remaining broken addresses (strip leading "Y " situs flag)
    for row in rows:
        if row['Property_Address'].startswith('Y '):
            row['Property_Address'] = row['Property_Address'][2:].strip()

    # Step 5: Write fixed output
    fieldnames = ['Property_ID', 'Owner_Name', 'Mailing_Address', 'Property_Address', 'Match_Reason']
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nResults:")
    print(f"  Total properties:    {len(rows):,}")
    print(f"  Full addresses:      {matched:,}")
    print(f"  Partial (no house#): {still_unmatched:,}")

    # Show sample output
    print(f"\nSample fixed rows:")
    for row in rows[:10]:
        print(f"  {row['Property_ID']:>10s}  {row['Owner_Name'][:35]:35s}  {row['Property_Address'][:45]}")


if __name__ == '__main__':
    main()
