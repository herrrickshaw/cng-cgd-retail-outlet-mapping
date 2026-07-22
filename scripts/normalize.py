#!/usr/bin/env python3
"""Normalize district names: strip parenthetical qualifiers into notes, fix known variants."""
import json
import re

rows = json.load(open("ga_rows_raw.json"))

SPECIAL = {
    "Bengaluru Rural and Urban Districts": ["Bengaluru Rural", "Bengaluru Urban"],
    "National Capital Territory of Delhi": ["NCT of Delhi"],
}


def clean_name(s):
    s = s.strip(" ,;&*")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\bdsitricts?\b|\bdistricts?\b\.?", "", s, flags=re.I).strip(" ,;&*")
    return s.strip()


def split_cell(cell):
    cell = re.sub(r"\s+", " ", cell).strip()
    if cell in SPECIAL:
        return SPECIAL[cell]
    parts = []
    if len(re.findall(r"district\b", cell, flags=re.I)) >= 2 and "," not in cell and " and " not in cell.lower():
        parts = re.split(r"[Dd][Ii]strict\b", cell)
    else:
        parts = [cell]
    out = []
    for p in parts:
        for chunk in re.split(r",", p):
            for sub in re.split(r"\s+(?:and|&)\s+", chunk):
                n = clean_name(sub)
                if n:
                    out.append(n)
    return out


# name → (canonical district, state_override or None)
CANON = {
    "Vizianagarm": "Vizianagaram",
    "Khamman": "Khammam",
    "Nalgonda Suryapet": None,  # actually two districts
    "Maldah": "Malda",
    "Kutch (East)": "Kachchh",
    "Kutch (West)": "Kachchh",
    "Kutch (East)*": "Kachchh",
    "Narmada (Rajpipla)": "Narmada",
    "Noida (including Greater Noida)": "Gautam Buddha Nagar",
    "Bhiwadi (in Alwar )": "Alwar",
    "Bhiwadi (in Alwar)": "Alwar",
    "Alwar (Other than Bhiwadi)": "Alwar",
    "Indore (including Ujjain City)": "Indore",
    "the Dangs": "Dang",
    "The Dangs": "Dang",
    "Dangs": "Dang",
}

district_rows = []
for r in rows:
    for d in split_cell(r["districts"]):
        note = ""
        base = d
        if base in CANON and CANON[base]:
            note_m = re.search(r"\(([^)]*)\)", base)
            note = note_m.group(1).strip() if note_m else ""
            base = CANON[base]
        elif base == "Nalgonda Suryapet":
            # two districts jammed together
            for b in ("Nalgonda", "Suryapet"):
                district_rows.append(dict(state=r["state"], ga_id=r["ga_id"],
                    ga_name=re.sub(r"\s+", " ", r["ga_name"]), district=b, note="",
                    entity=re.sub(r"\s+", " ", r["entity"])))
            continue
        else:
            m = re.search(r"\(([^)]*)\)", base)
            if m:
                note = m.group(1).strip()
                base = clean_name(re.sub(r"\([^)]*\)", "", base))
            if base in CANON and CANON[base]:
                base = CANON[base]
        if not base:
            # orphan parenthetical (e.g. stray "(EAAA)") — attach note to previous row of same GA
            if note and district_rows and district_rows[-1]["ga_id"] == r["ga_id"]:
                district_rows[-1]["note"] = note
            continue
        district_rows.append(dict(state=r["state"], ga_id=r["ga_id"],
            ga_name=re.sub(r"\s+", " ", r["ga_name"]), district=base, note=note,
            entity=re.sub(r"\s+", " ", r["entity"])))

print(f"district rows: {len(district_rows)}")
uniq = sorted({(d["state"], d["district"]) for d in district_rows})
print(f"unique (state, district): {len(uniq)}")
dups = {}
for d in district_rows:
    dups.setdefault((d["state"], d["district"]), []).append(d["ga_id"])
multi = {k: v for k, v in dups.items() if len(v) > 1}
print(f"districts under >1 GA: {len(multi)}")
weird = sorted({d["district"] for d in district_rows if len(d["district"]) < 4 or re.search(r"[()\d]", d["district"])})
print("weird remaining:", weird)

json.dump(district_rows, open("ga_districts.json", "w"), indent=1)
