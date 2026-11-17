#!/usr/bin/env python3
"""Assign SSRI outlets to districts (point-in-polygon) and CGD entities.

Outputs:
  outlets_cgd.csv       -- full outlet -> district -> CGD supplier table
  outlets_map.json      -- compact arrays for the map overlay
"""
from __future__ import annotations

import csv
import json
import os
from collections import Counter
from pathlib import Path

LAT_RANGE = (6.0, 37.5)          # degrees; outside India's bounding box -> bad coord
LON_RANGE = (68.0, 97.5)
COASTAL_TOLERANCE_DEG = 0.05     # ~5 km nearest-district fallback for coastal jitter
CSV_HEADER = ["outlet_id", "name", "company", "lat", "lon", "address", "state", "district",
              "has_cng", "cng_price", "cgd_entity", "ga_id", "ga_name", "cgd_status"]

GEOJSON_IN = Path("india_districts_clean.geojson")
ALLOC_IN = Path("district_alloc.json")
OUTLETS_IN = Path("ssri_pumps_raw.jsonl")
CSV_OUT = Path("outlets_cgd.csv")
MAP_OUT = Path("outlets_map.json")


def load_outlets(lines) -> tuple[list[dict], int, int]:
    """Parse JSONL ``lines``; drop bad coordinates and content-level duplicates.

    SSRI has byte-identical rows under different ids, so dedup is on
    (name, address, company, lat, lon). Returns (rows, dropped_dupes, bad_coords).
    """
    seen_content: set = set()
    rows: list[dict] = []
    dropped_dup = bad_coord = 0
    for line in lines:
        p = json.loads(line)
        try:
            lat, lon = float(p["latitude"]), float(p["longitude"])
        except (TypeError, ValueError):
            bad_coord += 1
            continue
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1] and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            bad_coord += 1
            continue
        ck = (p.get("name"), p.get("address"), p.get("company"), round(lat, 6), round(lon, 6))
        if ck in seen_content:
            dropped_dup += 1
            continue
        seen_content.add(ck)
        p["lat"], p["lon"] = lat, lon
        rows.append(p)
    return rows, dropped_dup, bad_coord


def assign_districts(rows: list[dict], gj: dict) -> int:
    """Point-in-polygon join: set ``gj_state``/``gj_district`` on each row; return #unassigned."""
    from shapely.geometry import Point, shape
    from shapely.prepared import prep
    from shapely.strtree import STRtree

    geoms, meta = [], []
    for f in gj["features"]:
        geoms.append(shape(f["geometry"]))
        meta.append((f["properties"]["st_nm"], f["properties"]["district"]))
    tree = STRtree(geoms)
    prepared: list = [None] * len(geoms)

    unassigned = 0
    for p in rows:
        pt = Point(p["lon"], p["lat"])
        hit = None
        for i in map(int, tree.query(pt)):
            if prepared[i] is None:
                prepared[i] = prep(geoms[i])
            if prepared[i].covers(pt):
                hit = i
                break
        if hit is None:
            # nearest district within ~5km (coastal jitter)
            best, bestd = None, COASTAL_TOLERANCE_DEG
            for i in map(int, tree.query(pt.buffer(COASTAL_TOLERANCE_DEG))):
                d = geoms[i].distance(pt)
                if d < bestd:
                    best, bestd = i, d
            hit = best
        if hit is None:
            unassigned += 1
            p["gj_state"], p["gj_district"] = None, None
        else:
            p["gj_state"], p["gj_district"] = meta[hit]
    return unassigned


def cgd_columns(p: dict, alloc: dict) -> tuple[str, str, str, str]:
    """Return (entity, ga_id, ga_name, status) strings for an outlet already district-assigned."""
    recs = alloc.get(f"{p['gj_state']}|{p['gj_district']}", []) if p["gj_district"] else []
    if recs:
        return ("; ".join(sorted({r["entity"] for r in recs})),
                "; ".join(r["ga_id"] for r in recs),
                "; ".join(r["ga_name"] for r in recs),
                "CGD GA authorised")
    return "", "", "", ("no authorised CGD GA" if p["gj_district"] else "outside district map")


def write_csv(rows: list[dict], alloc: dict, path: Path = CSV_OUT) -> None:
    """Write the outlet -> district -> CGD supplier table."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_HEADER)
        for p in rows:
            ent, gid, gname, status = cgd_columns(p, alloc)
            w.writerow([p["id"], p["name"], p["company"], p["lat"], p["lon"], p.get("address", ""),
                        p["gj_state"] or p.get("state", ""), p["gj_district"] or p.get("district", ""),
                        p.get("has_cng"), p.get("cng_price") or "", ent, gid, gname, status])


def build_map_payload(rows: list[dict]) -> dict:
    """Compact parallel arrays (lat/lon/company/cng/district index) for the map overlay."""
    companies = sorted({p["company"] or "?" for p in rows})
    cidx = {c: i for i, c in enumerate(companies)}
    dist_keys: list[str] = []
    dk_idx: dict = {}
    lats, lons, comps, cngs, dists = [], [], [], [], []
    for p in rows:
        if p["gj_district"] is None:
            continue
        k = f'{p["gj_state"]}|{p["gj_district"]}'
        if k not in dk_idx:
            dk_idx[k] = len(dist_keys)
            dist_keys.append(k)
        lats.append(round(p["lat"], 4))
        lons.append(round(p["lon"], 4))
        comps.append(cidx[p["company"] or "?"])
        cngs.append(1 if p.get("has_cng") else 0)
        dists.append(dk_idx[k])
    return dict(companies=companies, dist_keys=dist_keys,
                lat=lats, lon=lons, comp=comps, cng=cngs, dist=dists)


def main() -> int:
    gj = json.load(open(GEOJSON_IN))
    alloc = json.load(open(ALLOC_IN))
    with open(OUTLETS_IN) as fh:
        rows, dropped_dup, bad_coord = load_outlets(fh)
    print(f"outlets after dedup: {len(rows)} (dropped {dropped_dup} dupes, {bad_coord} bad coords)")

    unassigned = assign_districts(rows, gj)
    print(f"unassigned outlets (offshore/out of India): {unassigned}")

    write_csv(rows, alloc)
    payload = build_map_payload(rows)
    json.dump(payload, open(MAP_OUT, "w"), separators=(",", ":"))

    st = Counter(p["company"] for p in rows)
    print("by company:", dict(st.most_common(8)))
    print(f"CNG-equipped: {sum(payload['cng'])}")
    print("outlets_map.json MB:", round(os.path.getsize(MAP_OUT) / 1e6, 2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
