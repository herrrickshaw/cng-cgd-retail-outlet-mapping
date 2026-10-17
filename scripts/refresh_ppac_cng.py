#!/usr/bin/env python3
"""Refresh PPAC 'Status of PNG connections and CNG stations' (CGD Network table).

Source: https://ppac.gov.in/natural-gas/city-gas-distribution-network (public).
The page links an xlsx whose file name carries a rotating timestamp prefix
(e.g. 1790853565_8_CGD-Network-Web.xlsx), so the link is discovered, not hard-coded.
Parses the xlsx with the stdlib only (zipfile + regex; no openpyxl needed).

Writes data/ppac_cng_png_by_state.csv (one block per 'as on' date in the workbook)
and prints a diff vs the SSRI-derived has_cng counts in data/outlets_cgd.csv.gz.
PPAC clubs states by PNGRB GA (e.g. 'Bihar & Jharkhand'), so only single-state rows
are compared. Nothing is overwritten except the output CSV.
"""
import csv, gzip, html, io, re, sys, zipfile
from collections import Counter
from pathlib import Path
import requests

PAGE = "https://ppac.gov.in/natural-gas/city-gas-distribution-network"
UA = {"User-Agent": "Mozilla/5.0"}
DATA = Path(__file__).resolve().parent.parent / "data"


def find_xlsx():
    t = requests.get(PAGE, headers=UA, timeout=60).text
    m = re.search(r'href="([^"]*CGD-Network[^"]*\.xlsx)"', t, re.I)
    if not m:
        sys.exit("CGD-Network xlsx link not found on PPAC page (layout changed?)")
    return m.group(1)


def parse(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    ss = [html.unescape(re.sub("<[^>]+>", "", s)).strip()
          for s in re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    out = []
    for name in sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet")):
        for row in re.findall(r"<row.*?</row>", z.read(name).decode(), re.S):
            vals = []
            for m in re.finditer(r'<c r="[A-Z]+\d+"([^>]*?)(?:/>|>(.*?)</c>)', row, re.S):
                v = re.search(r"<v>(.*?)</v>", m.group(2) or "")
                if v:
                    vals.append(ss[int(v.group(1))] if 't="s"' in m.group(1) else v.group(1))
            if vals:
                out.append(vals)
    return out


def main():
    url = find_xlsx()
    print("fetching", url)
    rows = parse(requests.get(url, headers=UA, timeout=60).content)
    recs, asof = [], None
    for r in rows:
        mm = re.search(r"as on\s+([\d.]+)", r[0])
        if mm:
            asof = mm.group(1)
        elif asof and len(r) == 5 and r[1].isdigit():
            recs.append([asof, r[0], *r[1:]])
    out = DATA / "ppac_cng_png_by_state.csv"
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["as_on", "state_clubbed", "cng_stations", "png_domestic", "png_commercial", "png_industrial"])
        w.writerows(recs)
    print(f"wrote {out} ({len(recs)} rows)")

    latest = max({r[0] for r in recs}, key=lambda d: d.split(".")[::-1])
    ppac = {r[1]: int(r[2]) for r in recs if r[0] == latest}
    cur = Counter()
    with gzip.open(DATA / "outlets_cgd.csv.gz", "rt") as f:
        for o in csv.DictReader(f):
            if o["has_cng"] == "True":
                cur[o["state"]] += 1
    print(f"\nPPAC as on {latest}: total {ppac.get('Grand Total')}; repo (SSRI has_cng): {sum(cur.values())}")
    print(f"{'state':32}{'PPAC':>7}{'repo':>7}{'diff':>7}")
    for s, n in sorted(ppac.items()):
        if "&" in s or " and " in s.lower() or s == "Grand Total":
            continue
        k = next((c for c in cur if c.lower() == {"national capital territory of delhi (ut)": "delhi"}.get(s.lower(), s.lower())), None)
        print(f"{s[:31]:32}{n:>7}{cur.get(k, 0):>7}{cur.get(k, 0) - n:>7}")


if __name__ == "__main__":
    main()
