# CNG & CGD Retail Outlet Mapping

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

## Sources

- PNGRB, *State and Entity-wise list of GAs* — pngrb.gov.in
- SSRI/FuelABC public petrol-pumps API — api.ssrinnovationlab.com (only
  `/api/petrol-pumps/pumps/` is public; the rest of the surface needs a RapidAPI key)
- District boundaries — github.com/udit-001/india-maps-data
  (datta07/INDIAN-SHAPEFILES was rejected: diacritic corruption truncates Karnataka
  district names to unusable stubs)
- PPAC retail-outlet statistics for cross-tallies — ppac.gov.in
