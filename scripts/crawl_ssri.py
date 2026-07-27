#!/usr/bin/env python3
"""Crawl the public SSRI petrol-pumps API -> ssri_pumps_raw.jsonl (one pump per line)."""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

BASE = "https://api.ssrinnovationlab.com/api/petrol-pumps/pumps/"
LIMIT = 100
KEEP = ["id", "name", "company", "latitude", "longitude", "address", "city",
        "district", "state", "has_cng", "has_petrol", "has_diesel", "cng_price",
        "petrol_price", "diesel_price", "station_timing"]

sess = requests.Session()

def fetch(page, retries=5):
    for a in range(retries):
        try:
            r = sess.get(BASE, params={"limit": LIMIT, "page": page}, timeout=40)
            if r.status_code == 200:
                return page, r.json().get("results", [])
            if r.status_code == 404:      # past the end
                return page, []
            time.sleep(2 * (a + 1))
        except Exception:
            time.sleep(2 * (a + 1))
    return page, None

def write_rows(rows, out, seen):
    for p in rows:
        pid = p.get("id")
        if pid in seen:
            continue
        seen.add(pid)
        out.write(json.dumps({k: p.get(k) for k in KEEP}, separators=(",", ":")) + "\n")


def main():
    try:
        first = sess.get(BASE, params={"limit": LIMIT, "page": 1}, timeout=40).json()
    except Exception as e:                       # noqa: BLE001 — report + exit, don't crash
        print(f"initial request failed: {e}", file=sys.stderr)
        return 1
    count = first.get("count", 0)
    pages = (count + LIMIT - 1) // LIMIT
    print(f"count={count} pages={pages}", flush=True)

    seen, failed, done = set(), [], 0
    with open("ssri_pumps_raw.jsonl", "w") as out:
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(fetch, pg): pg for pg in range(1, pages + 1)}
            for f in as_completed(futs):
                pg, rows = f.result()
                done += 1
                if rows is None:
                    failed.append(pg)
                else:
                    write_rows(rows, out, seen)
                if done % 100 == 0:
                    print(f"{done}/{pages} pages, {len(seen)} unique, "
                          f"{len(failed)} failed", flush=True)
        # one sequential retry round for failures
        for pg in failed:
            _, rows = fetch(pg, retries=3)
            if rows:
                write_rows(rows, out, seen)

    print(f"DONE unique={len(seen)} failed_pages_after_retry={len(failed)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
