#!/usr/bin/env python3
"""Parse PNGRB 'State and Entity-wise list of GAs' PDF into a tidy table.

Output: one row per (state, ga_id, ga_name, districts_covered, entity).
Districts stay as the raw cell text; a second pass splits them.
"""
import json
import re

import pdfplumber

PDF = "pngrb_ga_list.pdf"

rows = []          # (state, sno, ga_id, ga_name, districts, entity)
current_state = None

with pdfplumber.open(PDF) as pdf:
    for pageno, page in enumerate(pdf.pages, 1):
        tables = page.extract_tables()
        if not tables:
            # state headers sometimes live outside tables
            continue
        for tbl in tables:
            for raw in tbl:
                cells = [(c or "").replace("\n", " ").strip() for c in raw]
                # drop fully empty
                if not any(cells):
                    continue
                nonempty = [c for c in cells if c]
                # header row
                if cells and cells[0].startswith("S. No"):
                    continue
                if nonempty and nonempty[0].startswith("State and Entity"):
                    continue
                # state header row: single non-empty cell, no digits pattern
                if len(nonempty) == 1 and not re.match(r"^\d", nonempty[0]):
                    current_state = nonempty[0]
                    continue
                # data row: first cell is an S.No integer
                if re.fullmatch(r"\d{1,3}", cells[0] if cells else ""):
                    # pad to 5 columns
                    c = cells + [""] * (5 - len(cells))
                    sno, ga_id, ga_name, districts, entity = c[:5]
                    rows.append(
                        dict(
                            state=current_state,
                            sno=int(sno),
                            ga_id=ga_id,
                            ga_name=ga_name,
                            districts=districts,
                            entity=entity,
                            page=pageno,
                        )
                    )
                else:
                    # continuation row (cell spillover) — append to last row
                    if rows:
                        c = cells + [""] * (5 - len(cells))
                        for idx, key in [(2, "ga_name"), (3, "districts"), (4, "entity")]:
                            if c[idx]:
                                rows[-1][key] = (rows[-1][key] + " " + c[idx]).strip()

print(f"parsed rows: {len(rows)}")
states = {}
for r in rows:
    states.setdefault(r["state"], 0)
    states[r["state"]] += 1
for s, n in states.items():
    print(f"  {s}: {n}")

with open("ga_rows_raw.json", "w") as f:
    json.dump(rows, f, indent=1)
