#!/usr/bin/env python3
"""Build the self-contained CGD GA map HTML: precomputed SVG paths + allotment data."""
import json
import math

gj = json.load(open("districts_simplified.json"))
alloc = json.load(open("district_alloc.json"))

# ---- projection ----
lons, lats = [], []
def walk(c, into):
    if isinstance(c[0], (int, float)):
        into.append(c)
    else:
        for x in c:
            walk(x, into)
pts = []
for f in gj["features"]:
    walk(f["geometry"]["coordinates"], pts)
lons = [p[0] for p in pts]; lats = [p[1] for p in pts]
LOMIN, LOMAX = min(lons), max(lons)
LAMIN, LAMAX = min(lats), max(lats)
MIDLAT = (LAMIN + LAMAX) / 2
KY = 30.0                       # px per degree latitude
KX = KY * math.cos(math.radians(MIDLAT))
W = (LOMAX - LOMIN) * KX
H = (LAMAX - LAMIN) * KY

def px(lon, lat):
    return round((lon - LOMIN) * KX, 1), round((LAMAX - lat) * KY, 1)

def ring_to_path(ring):
    out = []
    lx = ly = None
    for lon, lat in ring:
        x, y = px(lon, lat)
        if lx is None:
            out.append(f"M{x} {y}")
        else:
            if x == lx and y == ly:
                continue
            out.append(f"L{x} {y}")
        lx, ly = x, y
    out.append("Z")
    return "".join(out)

def geom_to_path(geom):
    if geom["type"] == "Polygon":
        polys = [geom["coordinates"]]
    else:
        polys = geom["coordinates"]
    parts = []
    for poly in polys:
        for ring in poly:
            parts.append(ring_to_path(ring))
    return "".join(parts)

GROUP_ORDER = [
 "GAIL Gas Limited","Adani Total Gas Limited","Indian Oil Corporation Limited",
 "Megha City Gas Distribution Private Limited","Bharat Petroleum Corporation Limited",
 "Gujarat Gas Limited","Hindustan Petroleum Corporation Limited",
 "Indian Oil-Adani Gas Private Limited","AGP / AG&P Pratham","Torrent Gas",
 "Indraprastha Gas Limited","Maharashtra Natural Gas Limited","Gasonet Services",
 "Think Gas","North East Gas Distribution Private Limited",
]
LIGHT = ["#1F6FB2","#D2622E","#1D6B33","#8A4B9F","#C79A26","#3E4E9C","#C0392B","#17A398",
         "#A34D7E","#7A9A28","#5E35B1","#4EA6DC","#96581F","#D98CB3","#0F7E63"]
DARK  = ["#3D7FBF","#D07430","#237A3C","#9A5FB5","#B08A28","#5A6FBF","#C74438","#17A89A",
         "#93436F","#7E942F","#7B5FC9","#3E97C9","#A5622A","#C4749F","#2A8F6B"]
gidx = {g: i for i, g in enumerate(GROUP_ORDER)}

# ---- district records ----
dist = []
paths = []
for f in gj["features"]:
    st, dt = f["properties"]["st"], f["properties"]["dt"]
    key = f"{st}|{dt}"
    recs = alloc.get(key, [])
    # primary group = group of first GA (they're in PDF order; most districts have 1)
    if recs:
        g = recs[0]["group"]
        gi = gidx.get(g, 15)     # 15 = Other
    else:
        gi = -1                  # uncovered
    dist.append(dict(s=st, d=dt, g=gi,
                     a=[[r["ga_id"], r["ga_name"], r["entity"], r["note"]] for r in recs]))
    paths.append(geom_to_path(f["geometry"]))

n_ga = len({r["ga_id"] for v in alloc.values() for r in v})
n_ent = len({r["entity"] for v in alloc.values() for r in v})
n_cov = sum(1 for d in dist if d["g"] >= 0)

payload = dict(w=round(W,1), h=round(H,1), dist=dist, paths=paths,
               groups=GROUP_ORDER, light=LIGHT, dark=DARK,
               proj=dict(lomin=LOMIN, lamax=LAMAX, kx=KX, ky=KY),
               stats=dict(gas=n_ga, entities=n_ent, covered=n_cov, total=len(dist)))

# outlet overlay (optional; requires outlets_map.json from join_outlets.py)
import os
if os.path.exists("outlets_map.json"):
    om = json.load(open("outlets_map.json"))
    # remap dist_keys -> feature index
    key_to_fi = {f'{d["s"]}|{d["d"]}': i for i, d in enumerate(dist)}
    remap = [key_to_fi.get(k, -1) for k in om["dist_keys"]]
    om["dist"] = [remap[i] for i in om["dist"]]
    del om["dist_keys"]
    payload["outlets"] = om
    print(f"embedded {len(om['lat'])} outlets")

tpl = open("map_template.html").read()
html = tpl.replace("/*__DATA__*/", "const DATA=" + json.dumps(payload, separators=(",", ":")) + ";")
open("cgd_ga_map.html", "w").write(html)
import os
print("wrote cgd_ga_map.html", round(os.path.getsize("cgd_ga_map.html")/1e6, 2), "MB",
      "| stats:", payload["stats"])
