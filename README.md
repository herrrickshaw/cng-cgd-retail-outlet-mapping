# CNG & CGD Retail Outlet Mapping

<!-- how-to-use-with-ai -->
> **New here?** See [How to use this repo with AI (Claude, Gemini, ChatGPT)](HOW_TO_USE_WITH_AI.md) — clone it, paste it into an AI tool, and ask in plain English.


District-wise map of **all PNGRB-authorised City Gas Distribution (CGD) geographical
areas** linked to **82,593 fuel retail outlets** — answering, for every outlet:
*which CGD entity is authorised to supply it CNG (by cascade today, by pipeline where
the entity's steel network reaches)?*

**Live interactive map:** open `webapp/cgd_ga_map.html` in a browser (fully
self-contained — choropleth by CGD entity, retail-outlet dot layer, CNG-only and
per-OMC filters, searchable table view).

## Headline numbers (as of 22 Jul 2026)

| Metric | Value |
|---|---|
| Authorised GAs (all rounds through 12A + pre-PNGRB legacy) | 309 |
| CGD entities | 58 |
| Districts under an authorised GA | 720 / 737 |
| Retail outlets (SSRI, content-deduplicated) | 82,593 |
| … inside an authorised GA (CGD-suppliable) | 82,261 (99.6%) |
| … CNG-equipped already | 11,194 |
| … in districts with **no** authorised CGD supplier | 305 |

## Data files

| File | Contents |
|---|---|
| `data/pngrb_ga_list.pdf` | Source: PNGRB "State and Entity-wise list of GAs" (pngrb.gov.in) |
| `data/cgd_ga_allotment.csv` | District → GA → entity table (780 rows) parsed from the PDF |
| `data/district_alloc.json` | Same, keyed `"State\|District"` for the webapp |
| `data/outlets_cgd.csv.gz` | **The linkage table**: outlet id, name, OMC, lat/lon, district, `has_cng`, authorised CGD entity/GA, status |
| `data/ssri_pumps_raw_20260722.jsonl.gz` | Raw SSRI crawl snapshot (105,035 records, pre-dedup) |
| `data/districts_simplified.json` | Simplified district geometries (from udit-001/india-maps-data) |
| `data/outlets_map.json` | Compact outlet arrays consumed by the webapp |

No LFS anywhere in this repo — everything is a regular git object, large tables
gzipped. (The account's LFS budget exhaustion is what orphaned the original
`fuel-retail-outlets` datasets; this repo deliberately avoids the same trap.)

## Pipeline (rerun order)

```bash
python scripts/parse_ga.py       # PDF -> ga_rows_raw.json (pdfplumber tables)
python scripts/normalize.py      # split/clean district cells -> ga_districts.json
python scripts/join_final.py     # match to geojson districts -> district_alloc.json + cgd_ga_allotment.csv
python scripts/crawl_ssri.py     # ~6 min: public SSRI API -> ssri_pumps_raw.jsonl
python scripts/join_outlets.py   # dedup + point-in-polygon -> outlets_cgd.csv + outlets_map.json
python scripts/build_html.py     # inject data into webapp/map_template.html -> cgd_ga_map.html
```

`join_final.py` needs the full-resolution district geojson (not committed, 47 MB):
merge the per-state files from
[udit-001/india-maps-data](https://github.com/udit-001/india-maps-data)
(`geojson/states/*.geojson`, concatenate features, keep `st_nm` + `district` props)
into `india_districts_clean.geojson`.

## Decisions & data caveats

- **PNGRB PDF quirks** (found the hard way):
  - The "Districts Covered" column is **under-filled** for GAs 9.50 and 9.52–9.54 —
    Patiala/Sangrur, Barnala/Moga, Kapurthala/SBS Nagar, Karaikal appear only in the
    GA *title*. Handled via `SUPPLEMENTS` in `join_final.py`.
  - The PDF **mixes district vintages** — Telangana rows use post-2016 districts, AP
    rows pre-2022 ones. Old districts are expanded to their successors (`AP_EXPAND`,
    TN Kancheepuram/Vellore splits, Mulugu, and Gujarat's 2013 splits — the last
    verified against operator disclosures: Morbi/Devbhumi Dwarka → Gujarat Gas,
    Aravalli → Sabarmati Gas). Chhota Udaipur could **not** be verified and stays
    unassigned rather than guessed.
  - One cell spells "DIstrict"; ~60 spelling variants needed a manual alias table.
- **SSRI database contains genuine duplicate rows** (not a pagination artifact):
  105,035 ids → 82,593 after `(name, address, company, lat, lon)` dedup; single Delhi
  coordinates carry 3,000+ byte-identical copies. Always content-dedupe. The API's
  own `district` field is unreliable — outlets are assigned by point-in-polygon
  instead.
- **Colour shows the first-listed GA** where a district falls under more than one
  (overlapping EAAA / legacy city GAs — 45 districts); tooltips/table list all.
- **Authorisation ≠ pipeline reach**: an outlet inside a GA can be cascade-supplied
  by the authorised entity today; pipeline supply depends on the entity's actual
  steel-network build-out, which PNGRB's GA list does not describe.
- Genuinely uncovered districts (no authorised GA, not parse gaps): A&N, Lakshadweep,
  Mizoram beyond the Aizawl GA, Majuli, Kalimpong, Ratnagiri, Pratapgarh (RJ),
  Chhota Udaipur.

## Data currency (checked 17 Oct 2026)

Repo data is the **22 Jul 2026** snapshot. Newer open sources were probed with `curl`:

| Source | Fetchable? | Finding |
|---|---|---|
| PNGRB GA list PDF (`State and Entity-wise list of GAs`) | **No stable URL found** | pngrb.gov.in home page loads, but the only CGD link (`cgd-auth.html`) returns 404 and the home page links no GA-list PDF; the guessed PDF path 404s. The committed `data/pngrb_ga_list.md` (309 GAs, through round 12A) therefore cannot be refreshed or checked for newer bidding rounds from here. The home page only says GA proposals are under review. |
| PPAC "CGD Network" table (CNG stations + PNG connections by state, as on 31.07.2026 P) | **Yes** | New `scripts/refresh_ppac_cng.py` discovers the xlsx link on `ppac.gov.in/natural-gas/city-gas-distribution-network`, writes `data/ppac_cng_png_by_state.csv` (two dated blocks: 31.01.2025 and 31.07.2026) and prints a diff against `has_cng` in `outlets_cgd.csv.gz`. |
| PPAC "Snapshot of India Oil & Gas" (Sept 2026 edition) | Yes (9.9 MB PDF, not committed) | CNG stations 9,158 as on 31.08.2026 (P); retail outlets 104,121 and 7,778 ROs with CNG/LNG as on 01.10.2026 (P). |
| PPAC state-wise retail outlets xls | Yes | All-India 103,023 outlets at 01.04.2026 (96,724 at 01.04.2025); not committed. |
| SSRI pumps API | Yes | `count` is now 107,380 raw records vs 105,035 in the committed crawl (22 Jul). **Not re-crawled** in this pass. |

**Diff vs current data** (`python scripts/refresh_ppac_cng.py`): PPAC reports 9,096 CNG
stations (31.07.2026) against 11,198 outlets flagged `has_cng` here (README headline
says 11,194), so SSRI `has_cng` overstates PPAC by about 23% (roughly 2,100). Overstatement is
broad (Gujarat +420, MP +323, UP +315, TN +213; only some states are under).
Delhi is the outlier the other way: SSRI flags just 5 of 363 Delhi outlets as CNG versus
PPAC's 459 stations. Treat `has_cng` as an upper-bound/noisy flag, not a station count.
PPAC clubs multi-state GAs (e.g. "Bihar & Jharkhand"), so only single-state rows are compared.

### Gaps / TODO
- TODO: locate the current PNGRB authorised-entity / GA list (PDF or page) and check for GAs authorised after round 12A.
- TODO: re-run `crawl_ssri.py` and `join_outlets.py` (raw count now 107,380) and regenerate headline numbers.
- TODO: reconcile `has_cng` against PPAC (Delhi undercount, overstatement elsewhere), e.g. by cross-checking OMC CNG-station locators.
- Gap: PPAC publishes no outlet-level or district-level CNG list; CGD sales volumes by entity were not located as a clean downloadable table.

## Sources

- PNGRB, *State and Entity-wise list of GAs* — pngrb.gov.in
- SSRI/FuelABC public petrol-pumps API — api.ssrinnovationlab.com (only
  `/api/petrol-pumps/pumps/` is public; the rest of the surface needs a RapidAPI key)
- District boundaries — github.com/udit-001/india-maps-data
  (datta07/INDIAN-SHAPEFILES was rejected: diacritic corruption truncates Karnataka
  district names to unusable stubs)
- PPAC retail-outlet statistics for cross-tallies — ppac.gov.in
