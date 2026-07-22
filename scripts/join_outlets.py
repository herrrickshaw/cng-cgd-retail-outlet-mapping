#!/usr/bin/env python3
"""Assign SSRI outlets to districts (point-in-polygon) and CGD entities.

Outputs:
  outlets_cgd.csv       -- full outlet -> district -> CGD supplier table
  outlets_map.json      -- compact arrays for the map overlay
"""
import csv
import json
from collections import Counter

from shapely.geometry import shape, Point
from shapely.strtree import STRtree
from shapely.prepared import prep

gj = json.load(open("india_districts_clean.geojson"))
alloc = json.load(open("district_alloc.json"))

geoms, meta = [], []
for f in gj["features"]:
    g = shape(f["geometry"])
    geoms.append(g)
    meta.append((f["properties"]["st_nm"], f["properties"]["district"]))
tree = STRtree(geoms)
prepared = [None] * len(geoms)

# content-level dedup: SSRI db has byte-identical rows under different ids
seen_content = set()
rows = []
dropped_dup = 0
bad_coord = 0
for line in open("ssri_pumps_raw.jsonl"):
    p = json.loads(line)
    try:
        lat, lon = float(p["latitude"]), float(p["longitude"])
    except (TypeError, ValueError):
        bad_coord += 1
        continue
    if not (6.0 <= lat <= 37.5 and 68.0 <= lon <= 97.5):
        bad_coord += 1
        continue
    ck = (p.get("name"), p.get("address"), p.get("company"), round(lat, 6), round(lon, 6))
    if ck in seen_content:
        dropped_dup += 1
        continue
    seen_content.add(ck)
    p["lat"], p["lon"] = lat, lon
    rows.append(p)

print(f"outlets after dedup: {len(rows)} (dropped {dropped_dup} dupes, {bad_coord} bad coords)")

# spatial join
unassigned = 0
for p in rows:
    pt = Point(p["lon"], p["lat"])
    idxs = tree.query(pt)
    hit = None
    for i in idxs:
        i = int(i)
        if prepared[i] is None:
            prepared[i] = prep(geoms[i])
        if prepared[i].covers(pt):
            hit = i
            break
    if hit is None:
        # nearest district within ~5km (coastal jitter)
        best, bestd = None, 0.05
        for i in map(int, tree.query(pt.buffer(0.05))):
            d = geoms[i].distance(pt)
            if d < bestd:
                best, bestd = i, d
        hit = best
    if hit is None:
        unassigned += 1
        p["gj_state"], p["gj_district"] = None, None
    else:
        p["gj_state"], p["gj_district"] = meta[hit]

print(f"unassigned outlets (offshore/out of India): {unassigned}")

# CGD lookup
def cgd_of(st, dt):
    return alloc.get(f"{st}|{dt}", [])

with open("outlets_cgd.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["outlet_id", "name", "company", "lat", "lon", "address", "state", "district",
                "has_cng", "cng_price", "cgd_entity", "ga_id", "ga_name", "cgd_status"])
    for p in rows:
        recs = cgd_of(p["gj_state"], p["gj_district"]) if p["gj_district"] else []
        if recs:
            ent = "; ".join(sorted({r["entity"] for r in recs}))
            gid = "; ".join(r["ga_id"] for r in recs)
            gname = "; ".join(r["ga_name"] for r in recs)
            status = "CGD GA authorised"
        else:
            ent = gid = gname = ""
            status = "no authorised CGD GA" if p["gj_district"] else "outside district map"
        w.writerow([p["id"], p["name"], p["company"], p["lat"], p["lon"], p.get("address", ""),
                    p["gj_state"] or p.get("state", ""), p["gj_district"] or p.get("district", ""),
                    p.get("has_cng"), p.get("cng_price") or "", ent, gid, gname, status])

# compact payload for map: parallel arrays
companies = sorted({p["company"] or "?" for p in rows})
cidx = {c: i for i, c in enumerate(companies)}
dist_keys = []
dk_idx = {}
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

json.dump(dict(companies=companies, dist_keys=dist_keys,
               lat=lats, lon=lons, comp=comps, cng=cngs, dist=dists),
          open("outlets_map.json", "w"), separators=(",", ":"))

st = Counter(p["company"] for p in rows)
print("by company:", dict(st.most_common(8)))
print(f"CNG-equipped: {sum(cngs)}")
import os
print("outlets_map.json MB:", round(os.path.getsize("outlets_map.json") / 1e6, 2))
