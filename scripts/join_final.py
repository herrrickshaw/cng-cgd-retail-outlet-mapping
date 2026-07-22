#!/usr/bin/env python3
"""Final join: PNGRB GA-district rows -> udit-001 GeoJSON districts.

Outputs:
  district_alloc.json  -- "State|District" -> [ {ga_id, ga_name, entity, entity_group, note}, ... ]
  cgd_ga_allotment.csv -- flat table
"""
import csv
import json
import re

rows = json.load(open("ga_districts.json"))
gj_pairs = [tuple(p) for p in json.load(open("gj_pairs.json"))]

STATE_MAP = {
 "Andhra Pradesh":["Andhra Pradesh"],"Telangana":["Telangana"],"West Bengal":["West Bengal"],
 "Bihar":["Bihar"],"Kerala":["Kerala"],"Punjab":["Punjab"],"Uttar Pradesh":["Uttar Pradesh"],
 "UT of Jammu & Kashmir":["Jammu and Kashmir"],
 "UT of Jammu & Kashmir and Ladakh":["Jammu and Kashmir","Ladakh"],
 "Tamil Nadu":["Tamil Nadu"],"Delhi":["Delhi"],"Assam":["Assam"],
 "Chhattisgarh":["Chhattisgarh","Madhya Pradesh"],
 "Chandigarh":["Chandigarh"],
 "UT of Dadra & Nagar Haveli & UT of Daman & Diu":["Dadra and Nagar Haveli and Daman and Diu"],
 "Goa":["Goa"],"Gujarat":["Gujarat","Dadra and Nagar Haveli and Daman and Diu"],
 "Haryana":["Haryana"],"Himachal Pradesh":["Himachal Pradesh"],"Jharkhand":["Jharkhand"],
 "Karnataka":["Karnataka"],"Madhya Pradesh":["Madhya Pradesh"],
 "Maharashtra":["Maharashtra","Madhya Pradesh"],
 "Odisha":["Odisha"],"Puducherry (UT)":["Puducherry","Tamil Nadu"],"Rajasthan":["Rajasthan"],
 "Tripura":["Tripura"],"Uttarakhand":["Uttarakhand"],"Arunachal Pradesh":["Arunachal Pradesh"],
 "Meghalaya":["Meghalaya"],"Manipur":["Manipur"],"Nagaland":["Nagaland"],"Sikkim":["Sikkim"],
 "Mizoram":["Mizoram"],
}

AP_EXPAND = {
 "EAST GODAVARI":["East Godavari","Kakinada","Konaseema","Alluri Sitharama Raju"],
 "WEST GODAVARI":["West Godavari","Eluru"],
 "KRISHNA":["Krishna","NTR"],
 "GUNTUR":["Guntur","Palnadu","Bapatla"],
 "ANANTAPUR":["Anantapuramu","Sri Sathya Sai"],
 "YSR":["YSR","Annamayya"],
 "CHITTOOR":["Chittoor","Tirupati"],
 "KURNOOL":["Kurnool","Nandyal"],
 "VISAKHAPATNAM":["Visakhapatnam","Anakapalli"],
 "VIZIANAGARAM":["Vizianagaram","Parvathipuram Manyam"],
}

# GA rows whose PDF "Districts Covered" cell is under-filled — districts named in the
# GA title but missing from the column. (state, ga_id) -> extra geojson districts
SUPPLEMENTS = {
 ("Punjab","9.52"): ["Patiala","Sangrur"],
 ("Punjab","9.53"): ["Barnala","Moga"],
 ("Punjab","9.54"): ["Kapurthala","Shahid Bhagat Singh Nagar"],
 ("Puducherry (UT)","9.50"): ["Karaikal"],
 # post-2013/2019 district splits of legacy GAs, verified via operator disclosures
 ("Gujarat","98.06"): ["Morbi"],            # GGL Rajkot GA; Morbi carved 2013
 ("Gujarat","3.03"): ["Devbhumi Dwarka"],   # GGL Jamnagar GA; carved 2013
 ("Gujarat","99.11"): ["Aravalli"],         # Sabarmati Gas; Aravalli carved 2013 from Sabarkantha
 ("Telangana","9.70"): ["Mulugu"],          # carved 2019 from Jayashankar Bhupalpally (GA on old boundary)
}

# (PNGRB state, normalized PNGRB district) -> list of geojson district names (in mapped state)
ALIASES = {
 # Telangana
 ("Telangana","JAYASHANKAR BHUPALPALLY"): ["Jayashankar Bhupalapally"],
 ("Telangana","MANCHERIAL KUMURAM BHEEM ASIFABAD"): ["Mancherial","Komaram Bheem"],
 # West Bengal
 ("West Bengal","BURDWAN"): ["Purba Bardhaman","Paschim Bardhaman"],
 ("West Bengal","HOOGLY"): ["Hooghly"],
 ("West Bengal","EAST MEDNIPORE"): ["Purba Medinipur"],
 ("West Bengal","WEST MEDNIPORE"): ["Paschim Medinipur"],
 ("West Bengal","KOCH BIHAR"): ["Cooch Behar"],
 # Kerala
 ("Kerala","KASARGOD"): ["Kasaragod"],
 ("Kerala","ALAPUZZHA"): ["Alappuzha"],
 ("Kerala","PATTANAMTITTA"): ["Pathanamthitta"],
 # Punjab
 ("Punjab","SAS NAGAR"): ["S.A.S. Nagar"],
 ("Punjab","BHATINDA"): ["Bathinda"],
 ("Punjab","PUNJAB"): ["Fatehgarh Sahib"],   # GA 6.12 name = Fatehgarh Sahib District
 # Uttar Pradesh
 ("Uttar Pradesh","ALLAHABAD"): ["Prayagraj"],
 ("Uttar Pradesh","BAGPAT"): ["Baghpat"],
 ("Uttar Pradesh","RAEBARELI"): ["Rae Bareli"],
 ("Uttar Pradesh","FAIZABAD"): ["Ayodhya"],
 ("Uttar Pradesh","AMBEDKARNAGAR"): ["Ambedkar Nagar"],
 ("Uttar Pradesh","KANPUR"): ["Kanpur Nagar"],
 ("Uttar Pradesh","KHURJA"): ["Bulandshahr"],
 ("Uttar Pradesh","SIDDHARTH NAGAR"): ["Siddharthnagar"],
 # Tamil Nadu (old-boundary GAs -> successor districts carved in 2019)
 ("Tamil Nadu","KANCHIPURAM"): ["Kancheepuram","Chengalpattu"],
 ("Tamil Nadu","VELLORE"): ["Vellore","Ranipet","Tirupathur"],
 ("Tamil Nadu","TIRUVALLUR"): ["Thiruvallur"],
 ("Tamil Nadu","TIRUVARUR"): ["Thiruvarur"],
 ("Tamil Nadu","VILLUPURAM"): ["Viluppuram"],
 ("Tamil Nadu","KALLAKKURICHI"): ["Kallakurichi"],
 ("Tamil Nadu","TIRUCHIRAPALLI"): ["Tiruchirappalli"],
 ("Tamil Nadu","PUDUKOTTAI"): ["Pudukkottai"],
 ("Tamil Nadu","VIRUDHNAGAR"): ["Virudhunagar"],
 ("Tamil Nadu","THOOTHUKUDI"): ["Thoothukkudi"],
 ("Tamil Nadu","TIRUNEVELI KATTABO"): ["Tirunelveli"],
 # Assam
 ("Assam","UDALGIRI"): ["Udalguri"],
 ("Assam","BAJALI"): ["Barpeta"],             # Bajali carved out of Barpeta (2021)
 ("Assam","UPPER ASSAM"): ["Dibrugarh","Tinsukia","Sivasagar","Charaideo","Jorhat","Golaghat"],
 # Chhattisgarh
 ("Chhattisgarh","GARIYABAND"): ["Gariaband"],
 ("Chhattisgarh","KABIRDHAM"): ["Kabeerdham"],
 ("Chhattisgarh","RAJ NANDGAON"): ["Rajnandgaon"],
 ("Chhattisgarh","BEMETARA"): ["Bametara"],
 # DNH & DD
 ("UT of Dadra & Nagar Haveli & UT of Daman & Diu","UT OF DADRA"): ["Dadra and Nagar Haveli"],
 ("UT of Dadra & Nagar Haveli & UT of Daman & Diu","NAGAR HAVELI"): ["Dadra and Nagar Haveli"],
 # Gujarat
 ("Gujarat","KACHCHH"): ["Kutch"],
 ("Gujarat","BANASKANTHA"): ["Banaskantha","Vav-Tharad"],  # Vav-Tharad carved 2023
 ("Gujarat","DAHEJ VAGRA TALUKA"): ["Bharuch"],
 ("Gujarat","BARWALA"): ["Botad"],
 ("Gujarat","RANPUR TALUKAS"): ["Botad"],
 ("Gujarat","ANKLESHWAR"): ["Bharuch"],
 ("Gujarat","NADIAD"): ["Kheda"],
 ("Gujarat","DASKROI AREA"): ["Ahmedabad"],
 ("Gujarat","HAZIRA"): ["Surat"],
 ("Gujarat","VADTAL VILLAGES"): ["Kheda"],
 ("Gujarat","GANDHINAGAR MEHSANA SABARKANTHA"): ["Gandhinagar","Mehsana","Sabarkantha"],
 # Jharkhand
 ("Jharkhand","SERAIKELA KHARSAWAN"): ["Saraikela-Kharsawan"],
 # Karnataka
 ("Karnataka","TUMKUR"): ["Tumakuru"],
 ("Karnataka","BELGAUM"): ["Belagavi"],
 # Madhya Pradesh
 ("Madhya Pradesh","SHANDOL"): ["Shahdol"],
 ("Madhya Pradesh","CHATTARPUR"): ["Chhatarpur"],
 # Maharashtra
 ("Maharashtra","RAIGARH"): ["Raigad"],
 ("Maharashtra","BULDANA"): ["Buldhana"],
 ("Maharashtra","GONDIYA"): ["Gondia"],
 ("Maharashtra","GARCHIROLI"): ["Gadchiroli"],
 ("Maharashtra","ADJOINING CONTIGENEOUS AREAS HINJEWADI"): ["Pune"],
 ("Maharashtra","CHAKAN"): ["Pune"],
 ("Maharashtra","TALEGAON"): ["Pune"],
 ("Maharashtra","ADJOINING MUNICIPALITIES"): ["Thane"],
 # Odisha
 ("Odisha","DHEKANAL"): ["Dhenkanal"],
 ("Odisha","DEBAGARH"): ["Deogarh"],
 ("Odisha","NABARANGPUR"): ["Nabarangapur"],
 ("Odisha","SONEPUR"): ["Subarnapur"],
 ("Odisha","BOLANGIR"): ["Balangir"],
 # Tripura
 ("Tripura","SEPAHIJALA"): ["Sipahijala"],
 ("Tripura","UNAKOTI"): ["Unokoti"],
 ("Tripura","AGARTALA"): ["West Tripura"],
 # Uttarakhand
 ("Uttarakhand","TEHRI GARWAL"): ["Tehri Garhwal"],
 # Arunachal Pradesh
 ("Arunachal Pradesh","DIBANG VALLEY"): ["Upper Dibang Valley"],
 ("Arunachal Pradesh","PAKKEKESSANG"): ["Pakke Kessang"],
 ("Arunachal Pradesh","KRADAADI"): ["Kra Daadi"],
 ("Arunachal Pradesh","KURUNGKUMEY"): ["Kurung Kumey"],
 # Meghalaya
 ("Meghalaya","RI BHOI"): ["Ribhoi"],
 # Nagaland (post-2021 districts -> parents on 2011-boundary map)
 ("Nagaland","CHUMOUKEDIMA"): ["Dimapur"],
 ("Nagaland","NIULAND"): ["Dimapur"],
 ("Nagaland","NOKLAK"): ["Tuensang"],
 ("Nagaland","SHAMATOR"): ["Tuensang"],
 ("Nagaland","TSEMINYU"): ["Kohima"],
 # Sikkim (new names -> old 4 districts)
 ("Sikkim","GANGTOK"): ["East Sikkim"],
 ("Sikkim","PAKYONG"): ["East Sikkim"],
 ("Sikkim","GYALSHING"): ["West Sikkim"],
 ("Sikkim","SORENG"): ["West Sikkim"],
 ("Sikkim","NAMCHI"): ["South Sikkim"],
 ("Sikkim","MANGAN"): ["North Sikkim"],
 # J&K
 ("UT of Jammu & Kashmir and Ladakh","POONCH"): ["Punch"],
 ("UT of Jammu & Kashmir and Ladakh","SHOPIAN"): ["Shopiyan"],
 # Mizoram
 ("Mizoram","SAITUAL"): ["Aizawl"],           # Saitual carved out of Aizawl (2019)
}

ENTITY_FIX = {
 "Indian Oil Adani Gas Private Limited": "Indian Oil-Adani Gas Private Limited",
 "Indian-Oil Adani Gas Private Limited": "Indian Oil-Adani Gas Private Limited",
 "HPCL": "Hindustan Petroleum Corporation Limited",
 "Haridwar Natrural Gas Private Limited": "Haridwar Natural Gas Private Limited",
}

def entity_group(e):
    if e.startswith("Think Gas"): return "Think Gas"
    if e.startswith("Torrent Gas"): return "Torrent Gas"
    if e.startswith("Gasonet Services"): return "Gasonet Services"
    if e.startswith("AGP "): return "AGP / AG&P Pratham"
    if e.startswith("HCG ") or e.startswith("Haryana City Gas"): return "Haryana City Gas group"
    if e == "GAIL Gas Limited" or e == "GAIL (India) Limited": return e  # keep distinct
    return e

def norm(s):
    s = s.upper().strip()
    s = re.sub(r"[^A-Z0-9& ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()

by_state = {}
for st, d in gj_pairs:
    by_state.setdefault(st, {})[norm(d)] = d

alloc = {}
unmatched = []

def add(st, dist, r, extra_note=""):
    key = f"{st}|{dist}"
    ent = ENTITY_FIX.get(r["entity"], r["entity"])
    note = "; ".join(x for x in (r["note"], extra_note) if x)
    rec = dict(ga_id=r["ga_id"], ga_name=r["ga_name"], entity=ent,
               group=entity_group(ent), note=note)
    # dedupe same GA in same district
    for existing in alloc.get(key, []):
        if existing["ga_id"] == rec["ga_id"] and existing["entity"] == rec["entity"]:
            return
    alloc.setdefault(key, []).append(rec)

for r in rows:
    states = STATE_MAP[r["state"]]
    d_up = norm(r["district"])
    hit = False
    akey = (r["state"], d_up)
    if akey in ALIASES:
        for nd in ALIASES[akey]:
            for st in states:
                lut = by_state.get(st, {})
                if norm(nd) in lut:
                    add(st, lut[norm(nd)], r)
                    hit = True
                    break
        if not hit:
            unmatched.append((r["state"], r["district"], r["ga_id"], "alias-miss"))
        continue
    for st in states:
        lut = by_state.get(st, {})
        if st == "Andhra Pradesh" and d_up in AP_EXPAND:
            for nd in AP_EXPAND[d_up]:
                if norm(nd) in lut:
                    add(st, lut[norm(nd)], r,
                        extra_note=("successor of pre-2022 district" if norm(nd) != d_up else ""))
                    hit = True
            if hit: break
            continue
        if d_up in lut:
            add(st, lut[d_up], r); hit = True; break
        cands = [v for k, v in lut.items() if d_up in k or k in d_up]
        if len(cands) == 1:
            add(st, cands[0], r); hit = True; break
    if not hit:
        unmatched.append((r["state"], r["district"], r["ga_id"], "no-match"))

# apply supplements (districts named in GA title but missing from the PDF column)
ga_lookup = {}
for r in rows:
    ga_lookup.setdefault((r["state"], r["ga_id"]), r)
for (st_pdf, ga_id), extras in SUPPLEMENTS.items():
    r = ga_lookup.get((st_pdf, ga_id))
    if not r:
        print(f"!! supplement source row not found: {st_pdf} {ga_id}")
        continue
    for st in STATE_MAP[st_pdf]:
        lut = by_state.get(st, {})
        for nd in extras:
            if norm(nd) in lut:
                r2 = dict(r, note=(r["note"] + "; " if r["note"] else "") + "district named in GA title (PDF column under-filled)")
                add(st, lut[norm(nd)], r2)

n_alloc = sum(len(v) for v in alloc.values())
print(f"allotments: {n_alloc} across {len(alloc)} districts; unmatched: {len(unmatched)}")
for u in unmatched: print("  ", u)

json.dump(alloc, open("district_alloc.json", "w"), indent=1)

with open("cgd_ga_allotment.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["state", "district", "ga_id", "ga_name", "entity", "entity_group", "note"])
    for key in sorted(alloc):
        st, dist = key.split("|")
        for rec in alloc[key]:
            w.writerow([st, dist, rec["ga_id"], rec["ga_name"], rec["entity"], rec["group"], rec["note"]])
print("wrote district_alloc.json + cgd_ga_allotment.csv")
