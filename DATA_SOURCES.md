
```markdown
# DATA_SOURCES

Unofficial research compilation; verify before operational use. Snapshot: 22 Jul 2026 (outlets), 17 Oct 2026 (PPAC).

## 1. PNGRB - authorised City Gas Distribution geographical areas
- Publisher: Petroleum & Natural Gas Regulatory Board. Document: "State and Entity-wise list of GAs" (pngrb.gov.in), rounds through 12A plus legacy GAs.
- Licence: Government of India publication; open-data licence not stated on the page (GODL-India presumed).
- Files: data/pngrb_ga_list.md (table extracted from the PDF), cgd_ga_allotment.csv (780 district-GA rows), district_alloc.json, ga_districts.json.
- Fields: state, district, ga_id, ga_name, entity, entity_group, note. 309 GAs, 58 entities, 720 of 737 districts.
- Refresh: manual; the live list URL could not be located on 2026-10-17 so GAs authorised after round 12A may be missing.
- Caveats: the PDF mixes district vintages (Telangana post-2016, AP pre-2022); "Districts Covered" is under-filled for GAs 9.50 and 9.52-9.54;
  ~60 spelling variants aliased manually; Chhota Udaipur unassigned; overlapping GAs mean colour shows only the first listed GA.
- Method: pdfplumber table extraction (scripts/parse_ga.py, normalize.py, join_final.py).

## 2. Retail outlets - third-party database (to be replaced)
- Publisher: SS Innovation Lab (FUELabc), api.ssrinnovationlab.com/api/petrol-pumps/pumps/ . Terms: none found; robots.txt reserves rights (ai-train=no).
- Status: 82,593 de-duplicated outlets (from 105,035 raw) with name, OMC, lat/lon, address, state, district, has_cng, cng_price, CGD join.
- Plan: replace with OpenStreetMap amenity=fuel (ODbL) and OMC-supplied data; keep only aggregates publicly until permission is obtained.
- Caveats: has_cng overstates PPAC by ~23% (11,198 vs 9,096); Delhi understated; 3% of outlets have unknown OMC; 122 coordinates are shared by 5+ outlets.

## 3. PPAC - CNG stations and PNG connections by state
- Publisher: Petroleum Planning & Analysis Cell, MoPNG; https://ppac.gov.in/natural-gas/city-gas-distribution-network
- File: data/ppac_cng_png_by_state.csv (as on 31.01.2025 and 31.07.2026, P = provisional). Multi-state GAs are clubbed in PPAC rows.
- Method: scripts/refresh_ppac_cng.py discovers the xlsx link and parses it.

## 4. District boundaries
- Source: github.com/udit-001/india-maps-data (no licence declared). To be replaced with geoBoundaries (CC BY 4.0) or LGD-based polygons.
- Simplified geometry committed as data/districts_simplified.json; the 47 MB full file is not committed.

## 5. Map assets
- Leaflet/Folium HTML under from-global-market-research-platform/ use OpenStreetMap tiles: credit "(c) OpenStreetMap contributors" (ODbL).
```
