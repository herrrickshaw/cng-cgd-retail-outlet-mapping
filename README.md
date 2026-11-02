# CNG & CGD Retail Outlet Mapping

<!-- how-to-use-with-ai -->
> **New here?** See [How to use this repo with AI (Claude, Gemini, ChatGPT)](HOW_TO_USE_WITH_AI.md) — clone it, paste it into an AI tool, and ask in plain English.

District-wise map of all PNGRB-authorised City Gas Distribution (CGD) geographical areas (GAs) in India,
linked to 82,593 fuel retail outlets. For every outlet it answers: *which CGD entity is authorised to supply
it CNG (by cascade today, by pipeline where the entity's steel network reaches)?* Outputs are a GA-allotment
table, an outlet-to-entity linkage table (gzipped CSV) and a self-contained interactive HTML map.

> Status: maintained (data snapshot as of 22 Jul 2026). Outlet data comes from a public third-party API
> (see Data sources); no licence file yet — all rights reserved. Not investment or regulatory advice.

**Interactive map:** open `webapp/cgd_ga_map.html` in a browser — choropleth by CGD entity, retail-outlet dot
layer, CNG-only and per-OMC filters, searchable table view.

## What it does
- Parses the PNGRB "State and Entity-wise list of GAs" table into one row per GA and district (`parse_ga.py`, `normalize.py`).
- Matches PNGRB district names to modern GeoJSON districts with alias, successor-district and supplement tables (`join_final.py`).
- Crawls the public SSRI petrol-pump API (`crawl_ssri.py`).
- De-duplicates outlets by content and assigns each to a district by point-in-polygon (`join_outlets.py`).
- Builds the single-file SVG/JS map with the outlet overlay (`build_html.py` + `webapp/map_template.html`).

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

## Quick start
```bash
git clone https://github.com/herrrickshaw/cng-cgd-retail-outlet-mapping.git
cd cng-cgd-retail-outlet-mapping
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
open webapp/cgd_ga_map.html        # the headline output is already built and committed
```

## How it works
Every script reads and writes files in the **current working directory** (names below), so run them from a
scratch directory holding the inputs. Each script is import-safe: work happens in `main()` under `__main__`.

| Stage | Script | Reads | Writes |
|---|---|---|---|
| 1 parse PDF | `scripts/parse_ga.py` | `pngrb_ga_list.pdf` (not committed) | `ga_rows_raw.json` |
| 2 split/clean districts | `scripts/normalize.py` | `ga_rows_raw.json` | `ga_districts.json` |
| 3 match to GeoJSON | `scripts/join_final.py` | `ga_districts.json`, `gj_pairs.json` | `district_alloc.json`, `cgd_ga_allotment.csv` |
| 4 crawl outlets (~6 min) | `scripts/crawl_ssri.py` | public SSRI API | `ssri_pumps_raw.jsonl` |
| 5 dedup + point-in-polygon | `scripts/join_outlets.py` | `india_districts_clean.geojson`, `district_alloc.json`, `ssri_pumps_raw.jsonl` | `outlets_cgd.csv`, `outlets_map.json` |
| 6 build map | `scripts/build_html.py` | `districts_simplified.json`, `district_alloc.json`, `outlets_map.json`, `map_template.html` | `cgd_ga_map.html` |

`gj_pairs.json` is a list of `[state, district]` pairs taken from the district GeoJSON; no script in this repo
generates it. `india_districts_clean.geojson` (47 MB, not committed) is built by merging the per-state files from
[udit-001/india-maps-data](https://github.com/udit-001/india-maps-data) (`geojson/states/*.geojson`, concatenate
features, keep `st_nm` + `district` props). `districts_simplified.json` is a simplified copy of the same geometries.

## Repository layout
| Path | Purpose |
|---|---|
| `scripts/` | The six pipeline stages above |
| `tests/` | pytest suite: pure functions, `join_final` end-to-end on fixtures, mocked-network crawl tests |
| `data/` | Committed inputs/outputs (see next table) |
| `webapp/` | `map_template.html` (template) and `cgd_ga_map.html` (built map) |
| `from-global-market-research-platform/` | Two earlier standalone HTML maps copied from another repo; not produced by this pipeline |

| Data file | Contents |
|---|---|
| `data/pngrb_ga_list.md` | Markdown conversion of the PNGRB "State and Entity-wise list of GAs" (the PDF itself is not committed) |
| `data/ga_districts.json` | Stage-2 output: one row per (GA, district) |
| `data/cgd_ga_allotment.csv` | District → GA → entity table (780 rows) |
| `data/district_alloc.json` | Same, keyed `"State\|District"` for the webapp |
| `data/outlets_cgd.csv.gz` | **The linkage table**: outlet id, name, OMC, lat/lon, district, `has_cng`, authorised CGD entity/GA, status |
| `data/ssri_pumps_raw_20260722.jsonl.gz` | Raw SSRI crawl snapshot (105,035 records, pre-dedup) |
| `data/districts_simplified.json` | Simplified district geometries (from udit-001/india-maps-data) |
| `data/outlets_map.json` | Compact outlet arrays consumed by the webapp |

No LFS anywhere in this repo — everything is a regular git object, large tables gzipped. (The account's LFS
budget exhaustion is what orphaned the original `fuel-retail-outlets` datasets; this repo deliberately avoids
the same trap.)

## Data sources
| Source | What is taken | Access route | Licence / caveat |
|---|---|---|---|
| PNGRB, *State and Entity-wise list of GAs* — pngrb.gov.in | GA ids, names, districts, authorised entity | Manual PDF download | Government publication; terms not checked |
| SSRI/FuelABC petrol-pumps API — api.ssrinnovationlab.com | Outlet name, OMC, address, lat/lon, CNG flag/price | Scraped; only `/api/petrol-pumps/pumps/` is public (the rest needs a RapidAPI key) | Terms not stated; third-party data, check before reuse |
| District boundaries — github.com/udit-001/india-maps-data | District polygons | GitHub download | Upstream licence not verified here |
| PPAC retail-outlet statistics — ppac.gov.in | Cross-tallies only | Manual | — |

`datta07/INDIAN-SHAPEFILES` was rejected: diacritic corruption truncates Karnataka district names to unusable stubs.

## Configuration
None. No environment variables or credentials are needed; nothing secret is committed. `requirements-ocr.txt`
lists optional OCR-fallback client dependencies and is not used by the scripts in this repo.

## Testing
```bash
pip install -r requirements-dev.txt
pytest -q          # 24 tests, no network
ruff check .
```

## Limitations and known issues
- **PNGRB PDF quirks:**
  - The "Districts Covered" column is under-filled for GAs 9.50 and 9.52–9.54 — Patiala/Sangrur, Barnala/Moga,
    Kapurthala/SBS Nagar, Karaikal appear only in the GA *title*. Handled via `SUPPLEMENTS` in `join_final.py`.
  - The PDF mixes district vintages — Telangana rows use post-2016 districts, AP rows pre-2022 ones. Old
    districts are expanded to their successors (`AP_EXPAND`, TN Kancheepuram/Vellore splits, Mulugu, and
    Gujarat's 2013 splits — the last verified against operator disclosures: Morbi/Devbhumi Dwarka → Gujarat
    Gas, Aravalli → Sabarmati Gas). Chhota Udaipur could **not** be verified and stays unassigned rather than guessed.
  - One cell spells "DIstrict"; ~60 spelling variants needed a manual alias table.
- **SSRI contains genuine duplicate rows** (not a pagination artifact): 105,035 ids → 82,593 after
  `(name, address, company, lat, lon)` dedup; single Delhi coordinates carry 3,000+ byte-identical copies. Always
  content-dedupe. The API's own `district` field is unreliable — outlets are assigned by point-in-polygon instead.
- **Colour shows the first-listed GA** where a district falls under more than one (overlapping EAAA / legacy city
  GAs — 45 districts); tooltips and the table list all.
- **Authorisation ≠ pipeline reach:** an outlet inside a GA can be cascade-supplied by the authorised entity
  today; pipeline supply depends on the entity's actual steel-network build-out, which PNGRB's GA list does not describe.
- Genuinely uncovered districts (no authorised GA, not parse gaps): A&N, Lakshadweep, Mizoram beyond the Aizawl
  GA, Majuli, Kalimpong, Ratnagiri, Pratapgarh (RJ), Chhota Udaipur.
- The outlet table contains business names, addresses and coordinates of fuel stations as published by the API;
  no personal data was identified, but it has not been audited for it.

## Related repositories
`fuel-retail-outlets` — earlier outlet datasets, orphaned by GitHub LFS budget exhaustion (see Repository layout).

## Licence
No licence file yet — all rights reserved.
