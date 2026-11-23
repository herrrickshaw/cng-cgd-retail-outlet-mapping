"""End-to-end runs of the script-style pipeline stages (parse_ga -> normalize -> join_final ->
join_outlets -> build_html) and crawl_ssri.main(), each in a tmp cwd with tiny synthetic inputs.
The PDF reader and the SSRI HTTP session are faked; nothing touches the network or the repo's data."""
import csv
import json
import os

import pytest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")


def run_script(name, capsys=None):
    """Exec a whole script in the current cwd; the code object keeps the real path so coverage sees it."""
    path = os.path.join(SCRIPTS, name)
    with open(path) as fh:
        code = compile(fh.read(), path, "exec")
    ns = {"__name__": "__main__", "__file__": path}
    exec(code, ns)
    return ns


def jload(path):
    with open(path) as fh:
        return json.load(fh)


# ------------------------------------------------------------------ parse_ga.py (fake pdfplumber)
class FakePage:
    def __init__(self, tables):
        self._t = tables

    def extract_tables(self):
        return self._t


class FakePdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def run_parse_ga(monkeypatch, pages):
    pdfplumber = pytest.importorskip("pdfplumber")
    monkeypatch.setattr(pdfplumber, "open", lambda path: FakePdf(pages))
    return run_script("parse_ga.py")


def test_parse_ga_state_headers_data_rows_and_continuations(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    t1 = [
        ["State and Entity-wise list of GAs", "", "", "", ""],
        ["S. No", "GA ID", "GA Name", "Districts Covered", "Entity"],
        ["Andhra Pradesh", None, None, None, None],
        ["1", "9.01", "Kakinada GA", "East Godavari", "Entity A"],
        ["", "", "(cont.)", "and Kakinada", "Pvt Ltd"],
        ["", "", "", "", ""],
        ["2", "9.02", "Eluru GA", "West Godavari"],                         # short row is padded to 5 cells
    ]
    t2 = [["Kerala"], ["3", "7.01", "Kochi GA", "Ernakulam", "Entity B"]]
    pages = [FakePage([t1]), FakePage([]), FakePage([t2])]                  # page 2 has no tables
    run_parse_ga(monkeypatch, pages)
    rows = jload(tmp_path / "ga_rows_raw.json")
    assert [(r["state"], r["sno"], r["ga_id"], r["page"]) for r in rows] == [
        ("Andhra Pradesh", 1, "9.01", 1), ("Andhra Pradesh", 2, "9.02", 1), ("Kerala", 3, "7.01", 3)]
    assert rows[0]["ga_name"] == "Kakinada GA (cont.)" and rows[0]["districts"] == "East Godavari and Kakinada"
    assert rows[0]["entity"] == "Entity A Pvt Ltd"
    assert rows[1]["entity"] == ""
    out = capsys.readouterr().out
    assert "parsed rows: 3" in out and "Andhra Pradesh: 2" in out and "Kerala: 1" in out


def test_parse_ga_ignores_continuation_before_any_row_and_non_numeric_first_cell(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    t = [["", "", "orphan", "text", "x"], ["Goa"], ["abc", "1", "2", "3", "4"], ["1234", "1", "2", "3", "4"]]
    run_parse_ga(monkeypatch, [FakePage([t])])
    assert jload(tmp_path / "ga_rows_raw.json") == []                      # '1234' is not an S.No (max 3 digits)


# ------------------------------------------------------------------ normalize.py
def run_normalize(tmp_path, monkeypatch, rows):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ga_rows_raw.json").write_text(json.dumps(rows))
    ns = run_script("normalize.py")
    return ns, jload(tmp_path / "ga_districts.json")


def raw(districts, ga_id="1", state="S", ga_name="GA  name", entity="Ent  Ltd"):
    return {"state": state, "ga_id": ga_id, "ga_name": ga_name, "districts": districts, "entity": entity}


def test_normalize_helpers(tmp_path, monkeypatch):
    ns, _ = run_normalize(tmp_path, monkeypatch, [])
    assert ns["clean_name"]("  Chennai   Dsitricts, ") == "Chennai"
    assert ns["clean_name"]("Pune District.") == "Pune"
    assert ns["clean_name"]("*Thane*") == "Thane"
    assert ns["split_cell"]("Bengaluru Rural and Urban   Districts") == ["Bengaluru Rural", "Bengaluru Urban"]
    assert ns["split_cell"]("National Capital Territory of Delhi") == ["NCT of Delhi"]
    assert ns["split_cell"]("Raigad, Thane and Palghar") == ["Raigad", "Thane", "Palghar"]
    assert ns["split_cell"]("A & B") == ["A", "B"]
    assert ns["split_cell"]("Pune District Satara District") == ["Pune", "Satara"]       # >=2 'district' words, no , or 'and'
    assert ns["split_cell"]("Pune District, Satara District") == ["Pune", "Satara"]        # comma path
    assert ns["split_cell"]("") == []


def test_normalize_canonical_names_notes_and_special_cases(tmp_path, monkeypatch, capsys):
    rows = [
        raw("Kutch (East)", "g1", "Gujarat"),
        raw("Vizianagarm", "g2", "AP"),
        raw("Nalgonda Suryapet", "g3", "Telangana"),
        raw("Pune (Rural)", "g4", "MH"),
        raw("Noida (including Greater Noida)", "g5", "UP"),
        raw("Bhiwadi (in Alwar )", "g6", "RJ"),
        raw("Amravati, (EAAA)", "g7", "MH"),
        raw("(ORPHAN)", "g8", "MH"),
    ]
    _, out = run_normalize(tmp_path, monkeypatch, rows)
    by = {}
    for r in out:
        by.setdefault(r["ga_id"], []).append(r)
    assert by["g1"][0]["district"] == "Kachchh" and by["g1"][0]["note"] == "East"
    assert by["g2"][0]["district"] == "Vizianagaram" and by["g2"][0]["note"] == ""
    assert [r["district"] for r in by["g3"]] == ["Nalgonda", "Suryapet"]                 # two districts jammed into one cell
    assert by["g4"][0]["district"] == "Pune" and by["g4"][0]["note"] == "Rural"
    assert by["g5"][0]["district"] == "Gautam Buddha Nagar" and by["g5"][0]["note"] == "including Greater Noida"
    assert by["g6"][0]["district"] == "Alwar" and by["g6"][0]["note"] == "in Alwar"
    assert [(r["district"], r["note"]) for r in by["g7"]] == [("Amravati", "EAAA")]      # orphan parenthetical -> note on previous row
    assert "g8" not in by                                                                # orphan with no previous row of the GA is dropped
    assert by["g1"][0]["ga_name"] == "GA name" and by["g1"][0]["entity"] == "Ent Ltd"     # whitespace collapsed
    printed = capsys.readouterr().out
    assert "district rows: 8" in printed and "weird remaining:" in printed


def test_normalize_canonicalises_a_name_revealed_by_stripping_its_parenthetical(tmp_path, monkeypatch):
    _, out = run_normalize(tmp_path, monkeypatch, [raw("Maldah (old spelling)", "g1", "WB")])
    assert [(r["district"], r["note"]) for r in out] == [("Malda", "old spelling")]


def test_normalize_counts_districts_under_multiple_gas(tmp_path, monkeypatch, capsys):
    run_normalize(tmp_path, monkeypatch, [raw("Pune", "a"), raw("Pune", "b"), raw("Satara", "a")])
    out = capsys.readouterr().out
    assert "unique (state, district): 2" in out and "districts under >1 GA: 1" in out


def test_normalize_flags_short_or_digit_names_as_weird(tmp_path, monkeypatch, capsys):
    run_normalize(tmp_path, monkeypatch, [raw("Ab", "a"), raw("Zone 5", "b"), raw("Longname", "c")])
    line = next(ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("weird remaining"))
    assert "Ab" in line and "Zone 5" in line and "Longname" not in line


# ------------------------------------------------------------------ join_final.py extras
def run_join(tmp_path, monkeypatch, rows, pairs):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ga_districts.json").write_text(json.dumps(rows))
    (tmp_path / "gj_pairs.json").write_text(json.dumps(pairs))
    ns = run_script("join_final.py")
    return ns, jload(tmp_path / "district_alloc.json")


def drow(state, district, ga_id="1", entity="E", note="", ga_name="GA"):
    return {"state": state, "district": district, "ga_id": ga_id, "ga_name": ga_name, "entity": entity, "note": note}


def test_join_helpers(tmp_path, monkeypatch):
    ns, _ = run_join(tmp_path, monkeypatch, [], [])
    assert ns["norm"]("  Sri-Sathya  Sai (x) ") == "SRI SATHYA SAI X"
    assert ns["entity_group"]("Think Gas Pvt") == "Think Gas" and ns["entity_group"]("Torrent Gas Chennai") == "Torrent Gas"
    assert ns["entity_group"]("Gasonet Services Ltd") == "Gasonet Services"
    assert ns["entity_group"]("AGP City Gas") == "AGP / AG&P Pratham" and ns["entity_group"]("HCG Pvt") == "Haryana City Gas group"
    assert ns["entity_group"]("Haryana City Gas Distribution") == "Haryana City Gas group"
    assert ns["entity_group"]("GAIL Gas Limited") == "GAIL Gas Limited" and ns["entity_group"]("GAIL (India) Limited") == "GAIL (India) Limited"
    assert ns["entity_group"]("Other Co") == "Other Co"


def test_join_andhra_successor_districts_get_a_note(tmp_path, monkeypatch):
    pairs = [["Andhra Pradesh", "East Godavari"], ["Andhra Pradesh", "Kakinada"], ["Andhra Pradesh", "Konaseema"]]
    _, alloc = run_join(tmp_path, monkeypatch, [drow("Andhra Pradesh", "East Godavari")], pairs)
    assert set(alloc) == {"Andhra Pradesh|East Godavari", "Andhra Pradesh|Kakinada", "Andhra Pradesh|Konaseema"}
    assert alloc["Andhra Pradesh|East Godavari"][0]["note"] == ""
    assert alloc["Andhra Pradesh|Kakinada"][0]["note"] == "successor of pre-2022 district"


def test_join_andhra_expansion_with_no_matching_districts_is_unmatched(tmp_path, monkeypatch, capsys):
    _, alloc = run_join(tmp_path, monkeypatch, [drow("Andhra Pradesh", "Visakhapatnam")], [["Andhra Pradesh", "Chittoor"]])
    assert alloc == {} and "no-match" in capsys.readouterr().out


def test_join_aliases_and_alias_miss(tmp_path, monkeypatch, capsys):
    rows = [drow("Kerala", "Kasargod", "1"), drow("Kerala", "Pattanamtitta", "2")]
    _, alloc = run_join(tmp_path, monkeypatch, rows, [["Kerala", "Kasaragod"]])
    assert list(alloc) == ["Kerala|Kasaragod"]
    out = capsys.readouterr().out
    assert "allotments: 1 across 1 districts; unmatched: 1" in out and "alias-miss" in out


def test_join_secondary_state_and_substring_fallback(tmp_path, monkeypatch):
    # Gujarat GAs also map into Dadra & Nagar Haveli and Daman & Diu; a unique substring match resolves 'Surat City'
    pairs = [["Gujarat", "Surat"], ["Dadra and Nagar Haveli and Daman and Diu", "Daman"]]
    rows = [drow("Gujarat", "Surat City", "1"), drow("Gujarat", "Daman", "2")]
    _, alloc = run_join(tmp_path, monkeypatch, rows, pairs)
    assert "Gujarat|Surat" in alloc
    assert "Dadra and Nagar Haveli and Daman and Diu|Daman" in alloc


def test_join_ambiguous_substring_is_unmatched(tmp_path, monkeypatch, capsys):
    pairs = [["Bihar", "East Champaran"], ["Bihar", "West Champaran"]]
    _, alloc = run_join(tmp_path, monkeypatch, [drow("Bihar", "Champaran")], pairs)
    assert alloc == {} and "no-match" in capsys.readouterr().out


def test_join_supplements_add_districts_named_only_in_the_ga_title(tmp_path, monkeypatch):
    pairs = [["Punjab", "Patiala"], ["Punjab", "Sangrur"], ["Punjab", "Barnala"]]
    rows = [drow("Punjab", "Patiala", "9.52", note="PDF note")]
    _, alloc = run_join(tmp_path, monkeypatch, rows, pairs)
    assert set(alloc) == {"Punjab|Patiala", "Punjab|Sangrur"}
    assert "under-filled" in alloc["Punjab|Sangrur"][0]["note"] and alloc["Punjab|Sangrur"][0]["note"].startswith("PDF note; ")
    assert alloc["Punjab|Patiala"][0]["note"] == "PDF note"


def test_join_missing_supplement_source_row_is_reported(tmp_path, monkeypatch, capsys):
    run_join(tmp_path, monkeypatch, [drow("Goa", "North Goa")], [["Goa", "North Goa"]])
    assert "!! supplement source row not found" in capsys.readouterr().out


def test_join_same_district_different_entities_both_kept(tmp_path, monkeypatch):
    rows = [drow("Goa", "North Goa", "1", "A"), drow("Goa", "North Goa", "1", "B"), drow("Goa", "North Goa", "2", "A")]
    _, alloc = run_join(tmp_path, monkeypatch, rows, [["Goa", "North Goa"]])
    assert len(alloc["Goa|North Goa"]) == 3                              # dedup key is (ga_id, entity)


def test_join_embedded_tables_are_consistent(tmp_path, monkeypatch):
    ns, _ = run_join(tmp_path, monkeypatch, [], [])
    states = set(ns["STATE_MAP"])
    assert {k[0] for k in ns["ALIASES"]} <= states
    assert {k[0] for k in ns["SUPPLEMENTS"]} <= states
    assert all(v and all(isinstance(x, str) for x in v) for v in ns["STATE_MAP"].values())
    assert all(k == k.upper() for k in (a[1] for a in ns["ALIASES"])), "alias keys are matched against norm() output (upper-case)"
    assert set(ns["ENTITY_FIX"].values()) - set(ns["ENTITY_FIX"]) == set(ns["ENTITY_FIX"].values())   # fixes never chain


# ------------------------------------------------------------------ join_outlets.py (shapely)
@pytest.fixture
def outlets_dir(tmp_path, monkeypatch):
    pytest.importorskip("shapely")
    sq = lambda x0, x1: [[[x0, 10], [x1, 10], [x1, 12], [x0, 12], [x0, 10]]]
    gj = {"features": [
        {"properties": {"st_nm": "S1", "district": "D1"}, "geometry": {"type": "Polygon", "coordinates": sq(70, 72)}},
        {"properties": {"st_nm": "S1", "district": "D2"}, "geometry": {"type": "Polygon", "coordinates": sq(72, 74)}},
    ]}
    alloc = {"S1|D1": [{"entity": "Zeta Gas", "ga_id": "1.1", "ga_name": "G1"}, {"entity": "Alpha Gas", "ga_id": "1.2", "ga_name": "G2"},
                       {"entity": "Zeta Gas", "ga_id": "1.3", "ga_name": "G3"}]}
    (tmp_path / "india_districts_clean.geojson").write_text(json.dumps(gj))
    (tmp_path / "district_alloc.json").write_text(json.dumps(alloc))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def pump(i, lat, lon, name=None, company="IOCL", address="a", **kw):
    return {"id": i, "name": name or f"P{i}", "company": company, "latitude": lat, "longitude": lon, "address": address, **kw}


def write_pumps(d, pumps):
    (d / "ssri_pumps_raw.jsonl").write_text("\n".join(json.dumps(p) for p in pumps))


def read_csv_rows(path):
    return list(csv.DictReader(open(path)))


def test_join_outlets_assignment_zones_and_csv(outlets_dir, capsys):
    pumps = [
        pump(1, 11.0, 71.0, has_cng=True, cng_price=70.0),                    # inside D1 (CGD authorised)
        pump(2, 11.0, 73.0),                                                  # inside D2 (no authorised CGD GA)
        pump(3, 11.0, 72.0),                                                  # exactly on the D1/D2 border: covered by the first hit
        pump(4, 11.0, 74.03),                                                 # 0.03 deg outside D2: nearest district within 0.05
        pump(5, 11.0, 75.0),                                                  # 1 deg outside: unassigned
        pump(6, "x", 71.0),                                                   # bad coordinate
        pump(7, 5.9, 71.0), pump(8, 37.6, 71.0), pump(9, 11.0, 67.9), pump(10, 11.0, 97.6),     # outside India bounds
        pump(11, 6.0, 68.0), pump(12, 37.5, 97.5),                            # bounds are inclusive (and outside every district)
    ]
    write_pumps(outlets_dir, pumps)
    run_script("join_outlets.py")
    rows = {r["outlet_id"]: r for r in read_csv_rows(outlets_dir / "outlets_cgd.csv")}
    assert set(rows) == {"1", "2", "3", "4", "5", "11", "12"}                       # 5 invalid coords dropped
    assert rows["1"]["district"] == "D1" and rows["1"]["cgd_status"] == "CGD GA authorised"
    assert rows["1"]["cgd_entity"] == "Alpha Gas; Zeta Gas"                         # unique, sorted
    assert rows["1"]["ga_id"] == "1.1; 1.2; 1.3" and rows["1"]["ga_name"] == "G1; G2; G3"
    assert rows["1"]["cng_price"] == "70.0" and rows["1"]["has_cng"] == "True"
    assert rows["2"]["district"] == "D2" and rows["2"]["cgd_status"] == "no authorised CGD GA" and rows["2"]["cgd_entity"] == ""
    assert rows["3"]["district"] in ("D1", "D2")                                    # border point resolves to one district, not none
    assert rows["4"]["district"] == "D2"                                           # coastal-jitter tolerance
    assert rows["5"]["cgd_status"] == "outside district map" and rows["5"]["district"] == ""
    out = capsys.readouterr().out
    assert "outlets after dedup: 7 (dropped 0 dupes, 5 bad coords)" in out and "unassigned outlets (offshore/out of India): 3" in out


def test_join_outlets_content_dedup_and_map_payload(outlets_dir, capsys):
    pumps = [
        pump(1, 11.0, 71.0, name="Same", has_cng=True),
        pump(2, 11.0, 71.0, name="Same", has_cng=True),                         # byte-identical content under a new id
        pump(3, 11.0, 71.0000004, name="Same", has_cng=False),                  # rounds to the same 6-dp coordinate
        pump(4, 11.0, 71.001, name="Same", company=None),                       # different coordinate -> distinct
        pump(5, 11.0, 73.0, name="Other", company="BPCL", has_cng=True),
        pump(6, 11.0, 80.0, name="Outside"),
    ]
    write_pumps(outlets_dir, pumps)
    run_script("join_outlets.py")
    assert "outlets after dedup: 4 (dropped 2 dupes, 0 bad coords)" in capsys.readouterr().out
    m = jload(outlets_dir / "outlets_map.json")
    assert m["companies"] == ["?", "BPCL", "IOCL"]                              # sorted, None -> '?'
    assert m["dist_keys"] == ["S1|D1", "S1|D2"] and len(m["lat"]) == 3          # the unassigned outlet is not in the map
    assert m["cng"] == [1, 0, 1] and m["dist"] == [0, 0, 1]
    assert m["comp"] == [2, 0, 1]
    assert m["lat"][0] == 11.0 and m["lon"][1] == 71.001


def test_join_outlets_missing_cng_price_is_blank(outlets_dir):
    write_pumps(outlets_dir, [pump(1, 11.0, 71.0, cng_price=None)])
    run_script("join_outlets.py")
    assert read_csv_rows(outlets_dir / "outlets_cgd.csv")[0]["cng_price"] == ""


# ------------------------------------------------------------------ build_html.py
def poly(x0, y0, size=1.0):
    return [[[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]]


@pytest.fixture
def html_dir(tmp_path, monkeypatch):
    gj = {"features": [
        {"properties": {"st": "S1", "dt": "D1"}, "geometry": {"type": "Polygon", "coordinates": poly(70, 10)}},
        {"properties": {"st": "S1", "dt": "D2"}, "geometry": {"type": "MultiPolygon", "coordinates": [poly(72, 10), poly(74, 10)]}},
        {"properties": {"st": "S2", "dt": "D3"}, "geometry": {"type": "Polygon", "coordinates": poly(70, 14)}},
        {"properties": {"st": "S2", "dt": "D4"}, "geometry": {"type": "Polygon", "coordinates": poly(72, 14)}},
    ]}
    alloc = {
        "S1|D1": [{"ga_id": "1", "ga_name": "G1", "entity": "E1", "group": "Indraprastha Gas Limited", "note": "n"}],
        "S1|D2": [{"ga_id": "2", "ga_name": "G2", "entity": "E2", "group": "GAIL Gas Limited", "note": ""},
                  {"ga_id": "3", "ga_name": "G3", "entity": "E2", "group": "Think Gas", "note": ""}],
        "S2|D3": [{"ga_id": "4", "ga_name": "G4", "entity": "E3", "group": "Some New Group", "note": ""}],
    }
    (tmp_path / "districts_simplified.json").write_text(json.dumps(gj))
    (tmp_path / "district_alloc.json").write_text(json.dumps(alloc))
    (tmp_path / "map_template.html").write_text("<script>/*__DATA__*/</script>")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def data_of(html):
    start = html.index("const DATA=") + len("const DATA=")
    return json.loads(html[start:html.rindex(";</script>")])


def test_build_html_payload_groups_paths_and_stats(html_dir, capsys):
    ns = run_script("build_html.py")
    d = data_of((html_dir / "cgd_ga_map.html").read_text())
    assert [x["g"] for x in d["dist"]] == [ns["gidx"]["Indraprastha Gas Limited"], ns["gidx"]["GAIL Gas Limited"], 15, -1]
    assert d["dist"][1]["a"] == [["2", "G2", "E2", ""], ["3", "G3", "E2", ""]]      # first GA's group colours the district
    assert d["stats"] == {"gas": 4, "entities": 3, "covered": 3, "total": 4}
    assert d["groups"] == ns["GROUP_ORDER"] and len(d["paths"]) == 4
    assert d["paths"][0].startswith("M") and d["paths"][0].endswith("Z")
    assert d["paths"][1].count("M") == 2 and d["paths"][1].count("Z") == 2          # MultiPolygon: one subpath per polygon
    assert "outlets" not in d
    assert "wrote cgd_ga_map.html" in capsys.readouterr().out


def test_build_html_projection_is_north_up_and_scales_with_latitude(html_dir):
    ns = run_script("build_html.py")
    d = data_of((html_dir / "cgd_ga_map.html").read_text())
    lons = [70, 71, 72, 73, 74, 75]
    lats = [10, 11, 14, 15]
    assert d["proj"]["lomin"] == min(lons) and d["proj"]["lamax"] == max(lats)
    assert d["h"] == round((max(lats) - min(lats)) * 30.0, 1)
    import math
    kx = 30.0 * math.cos(math.radians((min(lats) + max(lats)) / 2))
    assert d["w"] == round((max(lons) - min(lons)) * kx, 1) and d["proj"]["kx"] == pytest.approx(kx)
    assert ns["px"](70, 15) == (0.0, 0.0)                                           # top-left of the bounding box
    assert ns["px"](75, 10)[1] == d["h"]


def test_build_html_embeds_outlets_with_remapped_district_indices(html_dir, capsys):
    (html_dir / "outlets_map.json").write_text(json.dumps({
        "companies": ["IOCL"], "dist_keys": ["S2|D3", "S1|D2", "NOPE|X"], "lat": [1, 2, 3], "lon": [1, 2, 3],
        "comp": [0, 0, 0], "cng": [0, 1, 0], "dist": [0, 1, 2]}))
    run_script("build_html.py")
    d = data_of((html_dir / "cgd_ga_map.html").read_text())
    assert d["outlets"]["dist"] == [2, 1, -1] and "dist_keys" not in d["outlets"]
    assert "embedded 3 outlets" in capsys.readouterr().out


def test_build_html_palette_covers_every_named_group():
    with open(os.path.join(SCRIPTS, "build_html.py")) as fh:
        src = fh.read()
    import re
    names = re.search(r"GROUP_ORDER = (\[.*?\])\nLIGHT", src, re.DOTALL).group(1)
    light = re.search(r"LIGHT = (\[.*?\])\nDARK", src, re.DOTALL).group(1)
    dark = re.search(r"DARK  = (\[.*?\])\ngidx", src, re.DOTALL).group(1)
    import ast
    ns = {"names": ast.literal_eval(names), "light": ast.literal_eval(light), "dark": ast.literal_eval(dark)}
    assert len(ns["names"]) == len(ns["light"]) == len(ns["dark"]) == len(set(ns["names"])) == 15


# ------------------------------------------------------------------ crawl_ssri.main()
class Resp:
    def __init__(self, code=200, payload=None):
        self.status_code, self._p = code, payload

    def json(self):
        return self._p


@pytest.fixture
def crawl(monkeypatch, tmp_path):
    import importlib
    import sys
    monkeypatch.syspath_prepend(SCRIPTS)
    sys.modules.pop("crawl_ssri", None)
    mod = importlib.import_module("crawl_ssri")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    monkeypatch.chdir(tmp_path)
    yield mod
    sys.modules.pop("crawl_ssri", None)


def pump_row(i, **kw):
    return {"id": i, "name": f"p{i}", "latitude": 10.0, "longitude": 20.0, "extra": "dropped", **kw}


def test_main_crawls_all_pages_keeps_only_listed_fields_and_dedups(crawl, tmp_path, capsys):
    pages = {1: [pump_row(1), pump_row(2)], 2: [pump_row(2), pump_row(3)], 3: [pump_row(4)]}

    def get(url, params=None, timeout=None):
        if params["page"] == 1 and "first" not in get.__dict__:
            get.first = True
            return Resp(200, {"count": 250, "results": pages[1]})
        return Resp(200, {"results": pages.get(params["page"], [])})
    crawl.sess.get = get
    assert crawl.main() == 0
    rows = [json.loads(ln) for ln in (tmp_path / "ssri_pumps_raw.jsonl").read_text().splitlines()]
    assert sorted(r["id"] for r in rows) == [1, 2, 3, 4]
    assert set(rows[0]) == set(crawl.KEEP) and "extra" not in rows[0]
    assert "count=250 pages=3" in capsys.readouterr().out


def test_main_reports_a_failed_first_request(crawl, capsys):
    def boom(*a, **k):
        raise RuntimeError("no network")
    crawl.sess.get = boom
    assert crawl.main() == 1
    assert "initial request failed" in capsys.readouterr().err


def test_main_retries_failed_pages_once_more_sequentially(crawl, tmp_path, capsys):
    calls = {"p2": 0}

    def get(url, params=None, timeout=None):
        if params["page"] == 1:
            return Resp(200, {"count": 150, "results": [pump_row(1)]})
        calls["p2"] += 1
        if calls["p2"] <= 5:                                                  # all 5 attempts in the pool fail
            raise RuntimeError("flaky")
        return Resp(200, {"results": [pump_row(2)]})                          # the sequential retry round succeeds
    crawl.sess.get = get
    assert crawl.main() == 0
    ids = sorted(json.loads(ln)["id"] for ln in (tmp_path / "ssri_pumps_raw.jsonl").read_text().splitlines())
    assert ids == [1, 2]
    assert "DONE unique=2 failed_pages_after_retry=1" in capsys.readouterr().out


def test_progress_line_every_hundred_pages(crawl, capsys):
    crawl.sess.get = lambda url, params=None, timeout=None: Resp(200, {"count": 10_000, "results": []})
    crawl.main()
    out = capsys.readouterr().out
    assert "100/100 pages, 0 unique, 0 failed" in out and "count=10000 pages=100" in out


def test_page_count_rounds_up(crawl, capsys):
    crawl.sess.get = lambda url, params=None, timeout=None: Resp(200, {"count": 201, "results": []})
    crawl.main()
    assert "count=201 pages=3" in capsys.readouterr().out
