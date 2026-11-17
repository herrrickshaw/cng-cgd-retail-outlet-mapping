#!/usr/bin/env python3
"""Build the self-contained CGD GA map HTML: precomputed SVG paths + allotment data."""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from pathlib import Path

DISTRICTS_IN = Path("districts_simplified.json")
ALLOC_IN = Path("district_alloc.json")
OUTLETS_IN = Path("outlets_map.json")
TEMPLATE_IN = Path("map_template.html")
HTML_OUT = Path("cgd_ga_map.html")
PX_PER_DEG_LAT = 30.0           # px per degree latitude

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
GROUP_IDX = {g: i for i, g in enumerate(GROUP_ORDER)}
OTHER_GROUP = 15   # legend index for entities not in GROUP_ORDER
UNCOVERED = -1     # group index for districts with no authorised GA



def walk(c, into: list) -> None:
    """Collect every [lon, lat] leaf of a nested GeoJSON coordinate array into ``into``."""
    if isinstance(c[0], (int, float)):
        into.append(c)
    else:
        for x in c:
            walk(x, into)


@dataclass(frozen=True)
class Projection:
    """Equirectangular projection (lon/lat degrees -> SVG px), north-up."""
    lomin: float
    lamax: float
    kx: float
    ky: float
    w: float = 0.0
    h: float = 0.0

    @classmethod
    def from_features(cls, features: list) -> "Projection":
        """Fit the projection to the bounding box of all feature geometries."""
        pts: list = []
        for f in features:
            walk(f["geometry"]["coordinates"], pts)
        lons = [p[0] for p in pts]
        lats = [p[1] for p in pts]
        lomin, lomax, lamin, lamax = min(lons), max(lons), min(lats), max(lats)
        ky = PX_PER_DEG_LAT
        kx = ky * math.cos(math.radians((lamin + lamax) / 2))
        return cls(lomin, lamax, kx, ky, (lomax - lomin) * kx, (lamax - lamin) * ky)

    def px(self, lon: float, lat: float) -> tuple:
        """(lon, lat) in degrees -> (x, y) in px, rounded to 0.1."""
        return round((lon - self.lomin) * self.kx, 1), round((self.lamax - lat) * self.ky, 1)

    def ring_to_path(self, ring: list) -> str:
        """SVG path for one linear ring, collapsing repeated pixel points."""
        out = []
        lx = ly = None
        for lon, lat in ring:
            x, y = self.px(lon, lat)
            if lx is None:
                out.append(f"M{x} {y}")
            else:
                if x == lx and y == ly:
                    continue
                out.append(f"L{x} {y}")
            lx, ly = x, y
        out.append("Z")
        return "".join(out)

    def geom_to_path(self, geom: dict) -> str:
        """SVG path for a GeoJSON Polygon or MultiPolygon."""
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        return "".join(self.ring_to_path(ring) for poly in polys for ring in poly)


def build_district_records(features: list, alloc: dict, proj: Projection) -> tuple[list, list]:
    """Return (district records, SVG paths) in feature order."""
    dist, paths = [], []
    for f in features:
        st, dt = f["properties"]["st"], f["properties"]["dt"]
        recs = alloc.get(f"{st}|{dt}", [])
        # primary group = group of first GA (they're in PDF order; most districts have 1)
        gi = GROUP_IDX.get(recs[0]["group"], OTHER_GROUP) if recs else UNCOVERED
        dist.append(dict(s=st, d=dt, g=gi,
                         a=[[r["ga_id"], r["ga_name"], r["entity"], r["note"]] for r in recs]))
        paths.append(proj.geom_to_path(f["geometry"]))
    return dist, paths


def build_payload(gj: dict, alloc: dict, outlets: dict | None) -> dict:
    """Assemble the DATA object injected into the HTML template."""
    proj = Projection.from_features(gj["features"])
    dist, paths = build_district_records(gj["features"], alloc, proj)
    payload = dict(w=round(proj.w, 1), h=round(proj.h, 1), dist=dist, paths=paths,
                   groups=GROUP_ORDER, light=LIGHT, dark=DARK,
                   proj=dict(lomin=proj.lomin, lamax=proj.lamax, kx=proj.kx, ky=proj.ky),
                   stats=dict(gas=len({r["ga_id"] for v in alloc.values() for r in v}),
                              entities=len({r["entity"] for v in alloc.values() for r in v}),
                              covered=sum(1 for d in dist if d["g"] >= 0), total=len(dist)))
    if outlets is not None:
        # remap dist_keys -> feature index
        key_to_fi = {f'{d["s"]}|{d["d"]}': i for i, d in enumerate(dist)}
        remap = [key_to_fi.get(k, -1) for k in outlets["dist_keys"]]
        outlets["dist"] = [remap[i] for i in outlets["dist"]]
        del outlets["dist_keys"]
        payload["outlets"] = outlets
    return payload


def render_html(template: str, payload: dict) -> str:
    """Inject ``payload`` into the template's ``/*__DATA__*/`` placeholder."""
    return template.replace("/*__DATA__*/", "const DATA=" + json.dumps(payload, separators=(",", ":")) + ";")


def main() -> int:
    gj = json.load(open(DISTRICTS_IN))
    alloc = json.load(open(ALLOC_IN))
    # outlet overlay is optional; requires outlets_map.json from join_outlets.py
    outlets = json.load(open(OUTLETS_IN)) if OUTLETS_IN.exists() else None
    payload = build_payload(gj, alloc, outlets)
    if outlets is not None:
        print(f"embedded {len(outlets['lat'])} outlets")
    HTML_OUT.write_text(render_html(TEMPLATE_IN.read_text(), payload))
    print("wrote cgd_ga_map.html", round(os.path.getsize(HTML_OUT) / 1e6, 2), "MB",
          "| stats:", payload["stats"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
