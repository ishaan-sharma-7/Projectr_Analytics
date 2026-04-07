# Keywords That Hit the 300-Record Server Cap

The Travis County Clerk search returns at most **300 results** per query (15 pages × 20 rows). Any keyword whose total deed count exceeds 300 gets silently truncated — we only see whichever 300 the server happened to return (usually the most recent block).

These are the keywords that came back at or very near the cap in the latest deed scrape (`institutional_deeds.csv`, 6,313 rows total). They almost certainly have *more* records on TCC that we are missing. To get the rest, re-run them later with **year-by-year date filters** (the date ranges below show how many years each keyword spans, so each year-slice should land well under 300).

## Capped Keywords

| Returned | Keyword | Years observed | Suggested split |
|---:|---|---|---|
| 298 | `CARMA PROPERTIES WESTPORT` | 2017–2025 | per-year |
| 298 | `LENDINGHOME FUNDING` | 2017–2025 | per-year |
| 296 | `KIAVI FUNDING` | 2022–2026 | per-year |
| 296 | `HOUSEMAX FUNDING` | 2019–2026 | per-year |
| 296 | `PARK PLACE FINANCE` | 2016–2026 | per-year |
| 291 | `TOORAK CAPITAL` | 2020–2026 | per-year |
| 291 | `TOORAK CAPITAL PARTNERS` | 2020–2026 | per-year (duplicate of above — drop one) |

## Notes

- `TOORAK CAPITAL` and `TOORAK CAPITAL PARTNERS` are functionally the same query (the substring matches both). Pick one for the rerun, not both.
- All seven capped keywords are **fix-and-flip lender REO vehicles** (Tier 4 in `scrape_deeds.py`). That category is the most volume-heavy — the buy-to-rent landlords (AMH, Pretium, HPA) are mostly *under* 300 because they hold properties and don't churn instruments as fast.
- When re-running, the scraper's date range fields take `MM/DD/YYYY`. Splitting `LENDINGHOME FUNDING` into 9 single-year slices will turn 298 truncated rows into the full set (probably 600–900 actual records).
- After re-runs, dedupe `institutional_deeds.csv` on `Instrument_Number` — the year-slice runs will overlap whatever we already captured.

## Why this matters

Missing 50–70% of LendingHome / Kiavi / Toorak / HouseMax deeds means our **counterparty graph is undercounted**. Those four are the largest fix-flip warehouse lenders nationwide, and the 4,915 unique instruments we currently have only show their *recent* activity. Filling in the historical tail will probably double the size of any "shells that did business with each other" cluster we build.
