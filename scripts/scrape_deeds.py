"""
Semi-automated Travis County Clerk deed scraper.

Launches a VISIBLE browser so you can solve the Cloudflare check once,
then automates searching every institutional keyword and scraping all results.

Key features:
  - Tiered keyword list (active owners + feeder companies + missing parents)
  - Sub-searches to break the 300-record server cap on generic keywords
  - Incremental CSV writes (can be interrupted and resumed)
  - Dedupes against existing CSV on re-run
  - Proper detection of the disabled Next button (via src attribute)

Usage:
    python3 scripts/scrape_deeds.py                  # Run all keywords
    python3 scripts/scrape_deeds.py --test            # Run with just 2 test keywords
    python3 scripts/scrape_deeds.py --keywords "AMH 2014" "PROGRESS AUSTIN"  # Custom
    python3 scripts/scrape_deeds.py --skip-existing   # Skip keywords already in CSV
    python3 scripts/scrape_deeds.py --dump-search-page  # Dump search entry HTML for field inspection
"""

import csv
import os
import re
import time
import argparse
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

PROCESSED_DIR = os.path.join(os.path.dirname(__file__), '..', 'processed_owners')
OUTPUT_FILE = os.path.join(PROCESSED_DIR, 'institutional_deeds.csv')

# ============================================================
# KEYWORD TIERS
# ============================================================
# The site caps results at 300 per search. Any keyword that hits the cap
# must be broken into narrower sub-searches. That's why AH4R is listed as
# AH4R PROPERTIES, AH4R I TX, etc. instead of just "AH4R".

# --- Tier 1: Primary institutional operators (narrow sub-searches) ---
TIER1_KEYWORDS = [
    # American Homes 4 Rent — broken into sub-searches (was hitting 300 cap)
    "AMH 2014",
    "AMH 2015",
    "AMH TX PROPERTIES",
    "AMH ADDISON",
    "AMH ROMAN",
    "AH4R PROPERTIES",
    "AH4R I TX",
    "AH4R 1 TX",
    "AH4R GP",
    "AH4R-TX",
    "AMERICAN HOMES 4 RENT PROPERTIES EIGHT",
    "AMERICAN HOMES 4 RENT PROPERTIES TWO",
    "AMERICAN HOMES 4 RENT PROPERTIES ONE",
    "AMERICAN HOMES 4 RENT PROPERTIES II",
    "AMERICAN HOMES 4 RENT LP",
    "AMERICAN HOMES 4 RENT LLC",
    "AMERICAN HOMES 4 RENT TRS",
    "AMERICAN HOMES 4 RENT 2014",
    "AMERICAN HOMES 4 RENT 2015",
    "AMERICAN HOMES 4 RENT ADVISOR",
    "ARP 2014",
    "AMERICAN RESIDENTIAL LEASING",

    # Progress Residential
    "PROGRESS RESIDENTIAL",
    "PROGRESS AUSTIN",
    "PROGRESS RESIDENTIAL BORROWER",
    "PRETIUM",

    # Tricon
    "SFR JV-HD",
    "SFR JV-2",
    "TRICON RESIDENTIAL",
    "TRICON AMERICAN",

    # Home Partners of America (Blackstone) — was missing entirely
    "HPA TEXAS",
    "HPA BORROWER",
    "HOME PARTNERS OF AMERICA",

    # Invitation Homes (previously returned zero — may not operate here)
    "INVH LP",
    "INVITATION HOMES",
    "IH3 LP",
    "IH4 LP",
    "IH5 LP",
    "IH6 LP",
    "IH BORROWER",
    "THR PROPERTY",
    "STARWOOD WAYPOINT",
    "PREEMINENT HOLDINGS",

    # BlackRock direct
    "BLACKROCK REALTY",
    "GUTHRIE PROPERTY",
    "CRP/ARGYLE GUTHRIE",
    "SOUTH LAMAR VENTURE",

    # Main Street Renewal
    "MAIN STREET RENEWAL",

    # FirstKey Homes (Cerberus) — returned zero before, expand keywords
    "FIRSTKEY HOMES",
    "CERBERUS",
    "CF REAL ESTATE",
]

# --- Tier 2: Feeder/flipper LLCs discovered in prior deed scrape ---
# These companies SOLD to known institutional buyers. They may have flipped
# many more properties we haven't mapped yet.
TIER2_FEEDERS = [
    "RH PARTNERS OWNERCO",
    "TARBERT LLC",
    "REDFINNOW BORROWER",
    "CARMA PROPERTIES WESTPORT",
    "KAISER PROPERTIES BLUE",
    "SFR INVESTMENTS V",
    "3105 ETHEREDGE",
    "LNV CORPORATION",
]

# --- Tier 3: Other known institutional SFR operators ---
TIER3_OTHER = [
    "VINEBROOK HOMES",
    "MYND MANAGEMENT",
    "PATHLIGHT PROPERTY",
    "SYLVAN HOMES",
    "FRONT YARD RESIDENTIAL",
    "AMHERST HOLDINGS",
    "AMHERST RESIDENTIAL",
]

ALL_KEYWORDS = TIER1_KEYWORDS + TIER2_FEEDERS + TIER3_OTHER

TEST_KEYWORDS = [
    "AMH ADDISON",
    "RH PARTNERS OWNERCO",
]

SEARCH_URL = "https://tccsearch.org/RealEstate/SearchEntry.aspx"
PARTY_NAME_INPUT_ID = "cphNoMargin_f_txtParty"
SEARCH_BUTTON_ID = "cphNoMargin_SearchButtons1_btnSearch"

# ── Grid column mapping (from actual HTML inspection) ──
# Each data row is a <tr> inside <tbody class="ig_ElectricBlueItem">.
# Row has 38 <td> cells, mapped as:
COL_ROW_NUM = 0
COL_INSTRUMENT = 3
COL_DATE_FILED = 8
COL_DOC_TYPE = 9
COL_PARTY_TYPE = 12       # "E" or "R" — who is the first party
COL_FIRST_PARTY = 14
COL_SECOND_PARTY = 17
COL_LEGAL_DESC = 19
COL_STATUS = 20


def wait_for_grid(page, timeout=12):
    """Wait for the Infragistics grid rows to render."""
    print("    Waiting for grid...", end="", flush=True)
    start = time.time()
    while time.time() - start < timeout:
        count = page.locator("tbody.ig_ElectricBlueItem tr").count()
        if count > 1:  # Header row + at least 1 data row
            print(f" loaded ({count - 1} data rows)")
            return True
        time.sleep(0.5)
    print(" timed out")
    return False


def next_button_enabled(page):
    """Check if the Next page button is actually clickable (not disabled).

    The site swaps the button's src image between /nextsmall.gif (enabled)
    and /disabled/nextsmall.gif (disabled). The old scraper only checked
    is_visible() which returns True for both states.
    """
    next_btn = page.locator("#OptionsBar2_imgNext")
    if not next_btn.count():
        return False
    try:
        src = next_btn.first.get_attribute("src") or ""
        return "/disabled/" not in src
    except Exception:
        return False


def scrape_results_page(page, keyword):
    """Parse result rows from the current page by reading the grid's <td> cells."""
    html = page.content()
    soup = BeautifulSoup(html, 'html.parser')
    records = []

    tbody = soup.find('tbody', class_='ig_ElectricBlueItem')
    if not tbody:
        print("    No results grid found on page.")
        return records

    trs = tbody.find_all('tr', recursive=False)
    
    for tr in trs:
        tds = tr.find_all('td', recursive=False)
        if len(tds) < 21:
            continue  # Skip header row or malformed rows

        inst = tds[COL_INSTRUMENT].get_text(strip=True)
        if not re.match(r'^\d{7,10}$', inst):
            continue  # Not a data row

        party_type = tds[COL_PARTY_TYPE].get_text(strip=True)  # "E" or "R"
        first_party = tds[COL_FIRST_PARTY].get_text(strip=True)
        second_party = tds[COL_SECOND_PARTY].get_text(strip=True).rstrip('(+)').strip()

        # Determine who is Grantee [E] and Grantor [R]
        if party_type == 'E':
            grantee = first_party
            grantor = second_party
        else:
            grantor = first_party
            grantee = second_party

        record = {
            'Search_Keyword': keyword,
            'Instrument_Number': inst,
            'Date_Filed': tds[COL_DATE_FILED].get_text(strip=True),
            'Document_Type': tds[COL_DOC_TYPE].get_text(strip=True),
            'Grantee_E': grantee,
            'Grantor_R': grantor,
            'Legal_Description': tds[COL_LEGAL_DESC].get_text(strip=True),
            'Status': tds[COL_STATUS].get_text(strip=True),
        }
        records.append(record)

    return records


def scrape_keyword(page, keyword, all_records):
    """Search for a single keyword and scrape all paginated results."""
    print(f"\n{'='*60}")
    print(f"  Searching: {keyword}")
    print(f"{'='*60}")

    try:
        # Navigate to search page and wait for it to fully load
        page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Wait for the Party Name input to be visible and enabled
        party_input = page.locator(f"#{PARTY_NAME_INPUT_ID}")
        party_input.wait_for(state="visible", timeout=10000)
        time.sleep(1)

        # Clear and fill — retry up to 3 times if the value doesn't stick
        for attempt in range(3):
            party_input.click(timeout=5000)
            time.sleep(0.3)
            party_input.fill("")
            time.sleep(0.3)
            party_input.fill(keyword)
            time.sleep(0.5)

            # Verify the keyword was actually typed
            actual_value = party_input.input_value()
            if actual_value.strip() == keyword:
                break
            print(f"    Retry fill (attempt {attempt+1}, got '{actual_value}')...")
            time.sleep(1)
        else:
            print(f"  WARNING: Could not fill keyword '{keyword}' after 3 attempts.")
            return

        print(f"  Field value confirmed: '{party_input.input_value()}'")


        # Click Search via JS to avoid navigation timeout
        page.evaluate(f"document.getElementById('{SEARCH_BUTTON_ID}').click()")

        # Wait for postback — poll for the results count text (can take 5-10 seconds)
        print("  Waiting for search results...", end="", flush=True)
        total_records = 0
        page_text = ""
        for _ in range(30):  # Up to 15 seconds
            time.sleep(0.5)
            page_text = page.inner_text("body")
            count_match = re.search(r'(\d+)\s+records?\s+found', page_text)
            if count_match:
                total_records = int(count_match.group(1))
                break
            # Also check if we got a "no records" message
            if 'no records' in page_text.lower() or 'no results' in page_text.lower():
                break
        
        print(f" {total_records} records found.")

        if total_records == 0:
            # Debug: dump the page text so we can see what happened
            debug_path = os.path.join(PROCESSED_DIR, f'_debug_norecords_{keyword.replace(" ", "_")}.txt')
            with open(debug_path, 'w', encoding='utf-8') as f:
                f.write(page_text)
            print(f"  No records for this keyword. (debug saved to {debug_path})")
            return

        # Wait for grid to render
        if not wait_for_grid(page, timeout=12):
            print("  WARNING: Grid didn't load, trying anyway...")

        # Scrape all pages
        page_num = 1
        keyword_records = []
        while True:
            print(f"  Scraping page {page_num}...")

            records = scrape_results_page(page, keyword)
            keyword_records.extend(records)
            print(f"    Extracted {len(records)} records from page {page_num}.")

            # Warn if we're about to hit the 300-record server cap
            if len(keyword_records) >= 300:
                print(f"  WARNING: hit 300-record cap for '{keyword}'.")
                print(f"  There may be more records — split this into narrower sub-searches.")
                break

            # Check if Next is actually enabled (src must not contain /disabled/)
            if next_button_enabled(page):
                try:
                    page.locator("#OptionsBar2_imgNext").first.click()
                    time.sleep(3)
                    page.wait_for_load_state("networkidle", timeout=15000)
                    wait_for_grid(page, timeout=10)
                    page_num += 1
                except Exception as e:
                    print(f"  Pagination click failed: {e}")
                    break
            else:
                print("  No more pages (Next button disabled).")
                break

        all_records.extend(keyword_records)

        # Incremental save after each keyword
        save_results(all_records, silent=True)
        print(f"  Saved {len(keyword_records)} new records (total CSV: {len(all_records)}).")

    except Exception as e:
        print(f"  ERROR processing '{keyword}': {e}")
        # Still save what we have so far
        save_results(all_records, silent=True)


def load_existing_records():
    """Load existing CSV to enable resume + merge-on-rerun."""
    if not os.path.exists(OUTPUT_FILE):
        return [], set()

    records = []
    seen_keys = set()
    with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            records.append(row)
            # Key: (keyword, instrument) — same instrument under different
            # keywords is still worth keeping for attribution
            seen_keys.add((row.get('Search_Keyword', ''), row.get('Instrument_Number', '')))
    return records, seen_keys


def save_results(records, silent=False):
    """Save all scraped records to CSV, deduped by (keyword, instrument)."""
    if not records:
        if not silent:
            print("\nNo records to save.")
        return

    fieldnames = [
        'Search_Keyword', 'Instrument_Number', 'Date_Filed', 'Document_Type',
        'Grantee_E', 'Grantor_R', 'Legal_Description', 'Status'
    ]

    # Dedupe
    seen = set()
    unique = []
    for r in records:
        key = (r.get('Search_Keyword', ''), r.get('Instrument_Number', ''))
        if key in seen:
            continue
        seen.add(key)
        unique.append(r)

    with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique)

    if not silent:
        print(f"\nSaved {len(unique)} records to {OUTPUT_FILE}")


def dump_search_page(page):
    """Dump the search entry page HTML so we can find date filter field IDs."""
    page.goto(SEARCH_URL, wait_until="networkidle", timeout=30000)
    time.sleep(2)
    html = page.content()
    debug_path = os.path.join(PROCESSED_DIR, '_debug_search_entry_page.html')
    with open(debug_path, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  Search entry page HTML saved to {debug_path}")
    print(f"  Inspect for date filter field IDs (look for 'dtFrom', 'dtTo', 'DateFiled').")


def main():
    parser = argparse.ArgumentParser(description='Scrape Travis County Clerk deed records')
    parser.add_argument('--test', action='store_true', help='Run with only 2 test keywords')
    parser.add_argument('--keywords', nargs='+', help='Custom list of keywords to search')
    parser.add_argument('--skip-existing', action='store_true',
                        help='Skip keywords already present in existing CSV')
    parser.add_argument('--dump-search-page', action='store_true',
                        help='Dump search entry page HTML and exit (for date-field discovery)')
    args = parser.parse_args()

    if args.keywords:
        keywords = args.keywords
    elif args.test:
        keywords = TEST_KEYWORDS
    else:
        keywords = ALL_KEYWORDS

    # Resume / merge with existing CSV
    all_records, existing_keys = load_existing_records()
    existing_keywords = set(r['Search_Keyword'] for r in all_records)

    if args.skip_existing:
        before = len(keywords)
        keywords = [k for k in keywords if k not in existing_keywords]
        print(f"Skipping {before - len(keywords)} keywords already in CSV.")

    print(f"Will search {len(keywords)} keywords.")
    print(f"Starting CSV size: {len(all_records)} records")
    print("A browser window will open. Please:")
    print("  1. Solve the Cloudflare check if prompted")
    print("  2. The script will wait for you, then take over automatically")
    print()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=200)
        context = browser.new_context(viewport={'width': 1280, 'height': 900})
        page = context.new_page()

        print("Opening tccsearch.org...")
        page.goto("https://tccsearch.org/", wait_until="load", timeout=60000)

        print("\n>>> Solve the Cloudflare check (if any), then press ENTER.\n")
        input("Press ENTER when the site has loaded: ")

        # Optional: dump search entry page HTML for date-field discovery
        if args.dump_search_page:
            dump_search_page(page)
            browser.close()
            return

        for i, keyword in enumerate(keywords):
            print(f"\n[{i+1}/{len(keywords)}]", end="")
            scrape_keyword(page, keyword, all_records)
            time.sleep(1)

        browser.close()

    save_results(all_records)

    if all_records:
        unique_instruments = set(r['Instrument_Number'] for r in all_records)
        doc_types = {}
        for r in all_records:
            dt = r['Document_Type'] or 'UNKNOWN'
            doc_types[dt] = doc_types.get(dt, 0) + 1

        print(f"\n{'='*60}")
        print(f"  SUMMARY")
        print(f"{'='*60}")
        print(f"  Total records scraped:     {len(all_records)}")
        print(f"  Unique instrument numbers: {len(unique_instruments)}")
        print(f"  Document types:")
        for dt, count in sorted(doc_types.items(), key=lambda x: -x[1]):
            print(f"    {dt}: {count}")

        # Show discovered entity names not in our keyword list
        all_grantees = set()
        all_grantors = set()
        for r in all_records:
            if r['Grantee_E']:
                all_grantees.add(r['Grantee_E'])
            if r['Grantor_R']:
                all_grantors.add(r['Grantor_R'])
        
        print(f"\n  Unique Grantee [E] names: {len(all_grantees)}")
        for name in sorted(all_grantees):
            print(f"    {name}")
        print(f"\n  Unique Grantor [R] names: {len(all_grantors)}")
        for name in sorted(all_grantors):
            print(f"    {name}")


if __name__ == '__main__':
    main()
