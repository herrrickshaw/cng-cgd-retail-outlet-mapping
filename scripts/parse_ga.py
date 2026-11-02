#!/usr/bin/env python3
"""Parse PNGRB 'State and Entity-wise list of GAs' PDF into a tidy table.

Output: one row per (state, ga_id, ga_name, districts_covered, entity).
Districts stay as the raw cell text; a second pass splits them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

PDF = Path("pngrb_ga_list.pdf")
OUT_PATH = Path("ga_rows_raw.json")
N_COLS = 5  # S.No | GA id | GA name | districts covered | entity


def parse_tables(tables: list, pageno: int, state: str | None, rows: list[dict]) -> str | None:
    """Fold one page's pdfplumber tables into ``rows`` (mutated); return the current state."""
    for tbl in tables:
        for raw in tbl:
            cells = [(c or "").replace("\n", " ").strip() for c in raw]
            if not any(cells):
                continue
            nonempty = [c for c in cells if c]
            if cells and cells[0].startswith("S. No"):  # header row
                continue
            if nonempty and nonempty[0].startswith("State and Entity"):
                continue
            # state header row: single non-empty cell, no digits pattern
            if len(nonempty) == 1 and not re.match(r"^\d", nonempty[0]):
                state = nonempty[0]
                continue
            padded = cells + [""] * (N_COLS - len(cells))
            if re.fullmatch(r"\d{1,3}", cells[0] if cells else ""):
                # data row: first cell is an S.No integer
                sno, ga_id, ga_name, districts, entity = padded[:N_COLS]
                rows.append(dict(state=state, sno=int(sno), ga_id=ga_id, ga_name=ga_name,
                                 districts=districts, entity=entity, page=pageno))
            elif rows:
                # continuation row (cell spillover) — append to last row
                for idx, key in [(2, "ga_name"), (3, "districts"), (4, "entity")]:
                    if padded[idx]:
                        rows[-1][key] = (rows[-1][key] + " " + padded[idx]).strip()
    return state


def parse_pdf(pdf_path: Path = PDF) -> list[dict]:
    """Extract GA rows from the PNGRB PDF (needs pdfplumber)."""
    import pdfplumber

    rows: list[dict] = []
    state = None
    with pdfplumber.open(pdf_path) as pdf:
        for pageno, page in enumerate(pdf.pages, 1):
            tables = page.extract_tables()
            if tables:  # state headers sometimes live outside tables; skip those pages
                state = parse_tables(tables, pageno, state, rows)
    return rows


def main(pdf_path: Path = PDF, out_path: Path = OUT_PATH) -> int:
    rows = parse_pdf(pdf_path)
    print(f"parsed rows: {len(rows)}")
    states: dict = {}
    for r in rows:
        states[r["state"]] = states.get(r["state"], 0) + 1
    for s, n in states.items():
        print(f"  {s}: {n}")
    with open(out_path, "w") as f:
        json.dump(rows, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
