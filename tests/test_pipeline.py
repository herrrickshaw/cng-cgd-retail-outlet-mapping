"""Tests for the CNG/CGD retail-outlet mapping pipeline (scripts/*.py).

Every script is import-safe (work happens in ``main()`` under ``__main__``), so tests
import the modules directly. File-in/file-out stages run ``main()`` in a temp cwd
against tiny fixtures; network access is always mocked.
"""
import importlib
import os
import sys
import types

import pytest

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def load_funcs(name):
    """Import ``scripts/<name>`` (no side effects at import time)."""
    return importlib.import_module(name[:-3])


def run_script(name):
    """Run a script's ``main()`` in the current cwd — for end-to-end runs."""
    return load_funcs(name).main()


# --------------------------- normalize.py : name cleaning -----------------------

def test_clean_name_strips_district_word_and_punct():
    nz = load_funcs("normalize.py")
    assert nz.clean_name("  Chennai District. ") == "Chennai"
    assert nz.clean_name("Kutch,;& ") == "Kutch"


def test_split_cell_splits_on_and_and_comma():
    nz = load_funcs("normalize.py")
    assert nz.split_cell("Chennai and Tiruvallur") == ["Chennai", "Tiruvallur"]
    assert nz.split_cell("Salem, Erode & Namakkal") == ["Salem", "Erode", "Namakkal"]


def test_split_cell_uses_special_map():
    nz = load_funcs("normalize.py")
    assert nz.split_cell("National Capital Territory of Delhi") == ["NCT of Delhi"]
    assert nz.split_cell("Bengaluru Rural and Urban Districts") == [
        "Bengaluru Rural",
        "Bengaluru Urban",
    ]


# --------------------------- join_final.py : pure transforms --------------------

def test_norm_uppercases_and_drops_punctuation():
    jf = load_funcs("join_final.py")
    assert jf.norm("S.A.S. Nagar!!") == "S A S NAGAR"
    assert jf.norm("  purba   bardhaman ") == "PURBA BARDHAMAN"


def test_entity_group_buckets_by_prefix_but_keeps_gail_distinct():
    jf = load_funcs("join_final.py")
    assert jf.entity_group("Torrent Gas Rajasthan Pvt Ltd") == "Torrent Gas"
    assert jf.entity_group("Think Gas Nalanda") == "Think Gas"
    # GAIL entities stay individually named, never merged into a group
    assert jf.entity_group("GAIL Gas Limited") == "GAIL Gas Limited"
    assert jf.entity_group("Gujarat Gas Limited") == "Gujarat Gas Limited"


# --------------------------- build_html.py : geo/coordinate projection ----------

def _load_projector():
    bh = load_funcs("build_html.py")
    # fixed projection normally derived from the geojson bbox
    return bh.Projection(lomin=0.0, lamax=10.0, kx=30.0, ky=30.0)


def test_px_projects_lonlat_to_pixels_north_up():
    proj = _load_projector()
    assert proj.px(1.0, 9.0) == (30.0, 30.0)
    # y grows downward as latitude drops (screen space is north-up)
    assert proj.px(0.0, 10.0)[1] < proj.px(0.0, 8.0)[1]


def test_ring_to_path_emits_svg_and_dedups_repeats():
    proj = _load_projector()
    path = proj.ring_to_path([(0, 10), (1, 10), (1, 10), (0, 9)])  # dup 2nd point
    assert path.startswith("M")
    assert path.endswith("Z")
    assert path.count("L") == 2  # duplicate collapsed: 3 distinct verts -> M + 2 L


def test_geom_to_path_handles_polygon_and_multipolygon():
    proj = _load_projector()
    poly = proj.geom_to_path({"type": "Polygon", "coordinates": [[[0, 10], [1, 10], [0, 9]]]})
    multi = proj.geom_to_path(
        {"type": "MultiPolygon", "coordinates": [[[[0, 10], [1, 10], [0, 9]]]]}
    )
    assert poly == multi  # single-ring polygon == single-poly multipolygon
    assert poly.endswith("Z")


# --------------------------- crawl_ssri.py : fetch + retry (network mocked) ------

class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}

    def json(self):
        return self._payload


class _Sess:
    """Fake requests.Session yielding a scripted sequence of responses/exceptions."""

    def __init__(self, seq):
        self._seq = list(seq)
        self.calls = 0

    def get(self, *a, **k):
        item = self._seq[self.calls]
        self.calls += 1
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def crawl(monkeypatch):
    mod = load_funcs("crawl_ssri.py")
    monkeypatch.setattr(mod, "time", types.SimpleNamespace(sleep=lambda *_: None))  # never wait
    monkeypatch.setattr(mod, "sess", None)
    return mod


def test_fetch_returns_results_on_200(crawl):
    crawl.sess = _Sess([_Resp(200, {"results": [{"id": 1}, {"id": 2}]})])
    page, rows = crawl.fetch(3)
    assert page == 3 and rows == [{"id": 1}, {"id": 2}]
    assert crawl.sess.calls == 1  # success on first try, no retries


def test_fetch_returns_empty_on_404(crawl):
    crawl.sess = _Sess([_Resp(404)])
    page, rows = crawl.fetch(9)
    assert (page, rows) == (9, [])  # 404 = past the end, stop cleanly
    assert crawl.sess.calls == 1


def test_fetch_exhausts_retries_then_returns_none(crawl):
    crawl.sess = _Sess([_Resp(500), _Resp(500), _Resp(500)])
    page, rows = crawl.fetch(1, retries=3)
    assert rows is None                 # signals a hard failure to the caller
    assert crawl.sess.calls == 3        # tried every retry


def test_fetch_recovers_after_transient_error(crawl):
    crawl.sess = _Sess([ConnectionError("reset"), _Resp(200, {"results": [{"id": 7}]})])
    page, rows = crawl.fetch(1, retries=5)
    assert rows == [{"id": 7}]          # bounced back after the first failure
    assert crawl.sess.calls == 2


# --------------------------- join_final.py : end-to-end (temp cwd, no network) ---

def _write_join_inputs(tmp_path):
    import json

    rows = [
        # direct district match; entity "HPCL" must be expanded by ENTITY_FIX
        {"state": "Tamil Nadu", "ga_id": "1.1", "ga_name": "Chennai GA",
         "district": "Chennai", "note": "", "entity": "HPCL"},
        # needs ALIASES: PNGRB "Tiruvallur" -> geojson "Thiruvallur"
        {"state": "Tamil Nadu", "ga_id": "1.2", "ga_name": "Tiruvallur GA",
         "district": "Tiruvallur", "note": "", "entity": "Torrent Gas Chennai"},
        # exact duplicate of row 1 -> must be de-duped, not doubled
        {"state": "Tamil Nadu", "ga_id": "1.1", "ga_name": "Chennai GA",
         "district": "Chennai", "note": "", "entity": "HPCL"},
    ]
    (tmp_path / "ga_districts.json").write_text(json.dumps(rows))
    (tmp_path / "gj_pairs.json").write_text(
        json.dumps([["Tamil Nadu", "Chennai"], ["Tamil Nadu", "Thiruvallur"]])
    )


def test_join_end_to_end_schema_and_mapping(tmp_path, monkeypatch):
    import csv

    _write_join_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    run_script("join_final.py")

    with open(tmp_path / "cgd_ga_allotment.csv", newline="") as fh:
        rows = list(csv.reader(fh))
    header, data = rows[0], rows[1:]
    assert header == [
        "state", "district", "ga_id", "ga_name", "entity", "entity_group", "note"
    ]
    assert len(data) == 2  # Chennai + Thiruvallur, dupe collapsed

    by_dist = {r[1]: r for r in data}
    # ENTITY_FIX expanded the abbreviation
    assert by_dist["Chennai"][4] == "Hindustan Petroleum Corporation Limited"
    # ALIASES resolved the misspelling to the canonical geojson district name
    assert "Thiruvallur" in by_dist
    assert by_dist["Thiruvallur"][5] == "Torrent Gas"  # entity_group bucket


def test_join_dedupes_repeated_ga_in_district(tmp_path, monkeypatch):
    import json

    _write_join_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    run_script("join_final.py")

    alloc = json.loads((tmp_path / "district_alloc.json").read_text())
    assert len(alloc["Tamil Nadu|Chennai"]) == 1  # the duplicate GA row collapsed


def test_join_is_idempotent_on_rerun(tmp_path, monkeypatch):
    import csv

    _write_join_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)
    run_script("join_final.py")
    first = (tmp_path / "cgd_ga_allotment.csv").read_text()
    run_script("join_final.py")  # re-run overwrites, must not accumulate
    second = (tmp_path / "cgd_ga_allotment.csv").read_text()
    assert first == second
    assert len(list(csv.reader(second.splitlines()))) == 3  # header + 2 rows


# --------------------------- crawl_ssri.py : main() guard regression --------------

def test_crawl_ssri_import_is_side_effect_free():
    """After the main() refactor, importing the module must NOT hit the network
    or write ssri_pumps_raw.jsonl — the crawl only runs under __main__."""
    sys.modules.pop("crawl_ssri", None)
    mod = importlib.import_module("crawl_ssri")   # would raise/hang if it crawled
    assert callable(mod.main)


def test_write_rows_dedups_by_id():
    """write_rows(rows, out, seen) — explicit args (the old `global done` was dead)."""
    import io
    mod = importlib.import_module("crawl_ssri")
    out, seen = io.StringIO(), set()
    mod.write_rows([{"id": 1, "name": "A"}, {"id": 1, "name": "dupe"},
                    {"id": 2, "name": "B"}], out, seen)
    lines = out.getvalue().strip().splitlines()
    assert len(lines) == 2 and seen == {1, 2}


# --------------------------- normalize.py : to_district_rows -----------------------

def test_to_district_rows_expands_special_cases():
    nz = load_funcs("normalize.py")
    rows = [
        {"state": "Telangana", "ga_id": "3.1", "ga_name": "N  G", "districts": "Nalgonda Suryapet",
         "entity": "Y  Ltd"},
        {"state": "Gujarat", "ga_id": "2.1", "ga_name": "K", "districts": "Kutch (East)*, the Dangs",
         "entity": "X"},
        {"state": "Rajasthan", "ga_id": "4.1", "ga_name": "A",
         "districts": "Bhiwadi (in Alwar ), (EAAA)", "entity": "Z"},
    ]
    out = nz.to_district_rows(rows)
    assert [(r["district"], r["note"]) for r in out] == [
        ("Nalgonda", ""), ("Suryapet", ""),
        ("Kachchh", "East"), ("Dang", ""),
        ("Alwar", "EAAA"),   # orphan "(EAAA)" overwrites the note of the previous row
    ]
    assert out[0]["ga_name"] == "N G" and out[0]["entity"] == "Y Ltd"  # whitespace collapsed


# --------------------------- join_final.py : build_alloc ---------------------------

def test_build_alloc_alias_ap_expand_and_unmatched():
    jf = load_funcs("join_final.py")
    pairs = [("Andhra Pradesh", "East Godavari"), ("Andhra Pradesh", "Kakinada"),
             ("Kerala", "Kasaragod")]
    base = {"ga_id": "1", "ga_name": "G", "note": "", "entity": "HPCL"}
    rows = [
        dict(base, state="Andhra Pradesh", district="East Godavari"),
        dict(base, state="Kerala", district="Kasargod"),
        dict(base, state="Kerala", district="Nowhereville"),
    ]
    alloc, unmatched = jf.build_alloc(rows, pairs)
    assert "Andhra Pradesh|Kakinada" in alloc
    assert alloc["Andhra Pradesh|Kakinada"][0]["note"] == "successor of pre-2022 district"
    assert alloc["Kerala|Kasaragod"][0]["entity"] == "Hindustan Petroleum Corporation Limited"
    assert unmatched == [("Kerala", "Nowhereville", "1", "no-match")]


# --------------------------- join_outlets.py : pure stages -------------------------

def test_load_outlets_dedups_content_and_rejects_bad_coords():
    import json

    jo = load_funcs("join_outlets.py")
    good = {"id": 1, "name": "A", "address": "x", "company": "IOCL",
            "latitude": "28.6", "longitude": "77.2"}
    lines = [json.dumps(p) for p in (
        good,
        dict(good, id=2),                               # same content, new id -> dupe
        dict(good, id=3, latitude="oops"),              # unparsable
        dict(good, id=4, latitude="50.0"),              # outside India
        dict(good, id=5, name="B"),
    )]
    rows, dupes, bad = jo.load_outlets(lines)
    assert [r["id"] for r in rows] == [1, 5] and dupes == 1 and bad == 2


def test_assign_districts_and_cgd_columns():
    jo = load_funcs("join_outlets.py")
    square = {"type": "Polygon", "coordinates": [[[77, 28], [78, 28], [78, 29], [77, 29], [77, 28]]]}
    gj = {"features": [{"geometry": square, "properties": {"st_nm": "Delhi", "district": "New Delhi"}}]}
    rows = [{"lon": 77.5, "lat": 28.5}, {"lon": 77.51, "lat": 29.02}, {"lon": 90.0, "lat": 10.0}]
    assert jo.assign_districts(rows, gj) == 1
    assert rows[0]["gj_district"] == "New Delhi"
    assert rows[1]["gj_district"] == "New Delhi"        # within coastal tolerance
    assert rows[2]["gj_district"] is None
    alloc = {"Delhi|New Delhi": [{"entity": "IGL", "ga_id": "1", "ga_name": "G"}]}
    assert jo.cgd_columns(rows[0], alloc) == ("IGL", "1", "G", "CGD GA authorised")
    assert jo.cgd_columns(rows[0], {})[3] == "no authorised CGD GA"
    assert jo.cgd_columns(rows[2], alloc)[3] == "outside district map"


def test_build_map_payload_skips_unassigned_and_indexes_districts():
    jo = load_funcs("join_outlets.py")
    rows = [
        {"company": "BPCL", "lat": 1.23456, "lon": 2.0, "has_cng": True, "gj_state": "S", "gj_district": "D"},
        {"company": None, "lat": 1.0, "lon": 2.0, "has_cng": False, "gj_state": None, "gj_district": None},
        {"company": "HPCL", "lat": 3.0, "lon": 4.0, "has_cng": False, "gj_state": "S", "gj_district": "D"},
    ]
    p = jo.build_map_payload(rows)
    assert p["companies"] == ["?", "BPCL", "HPCL"] and p["dist_keys"] == ["S|D"]
    assert p["lat"] == [1.2346, 3.0] and p["cng"] == [1, 0] and p["dist"] == [0, 0]


# --------------------------- build_html.py : payload ------------------------------

def test_build_payload_groups_stats_and_outlet_remap():
    bh = load_funcs("build_html.py")
    tri = {"type": "Polygon", "coordinates": [[[0, 10], [1, 10], [0, 9]]]}
    gj = {"features": [
        {"geometry": tri, "properties": {"st": "S", "dt": "A"}},
        {"geometry": tri, "properties": {"st": "S", "dt": "B"}},
    ]}
    alloc = {"S|A": [{"ga_id": "1", "ga_name": "g", "entity": "e", "group": "Torrent Gas", "note": ""}]}
    outlets = {"dist_keys": ["S|B"], "dist": [0], "lat": [1]}
    payload = bh.build_payload(gj, alloc, outlets)
    assert [d["g"] for d in payload["dist"]] == [bh.GROUP_IDX["Torrent Gas"], bh.UNCOVERED]
    assert payload["stats"] == {"gas": 1, "entities": 1, "covered": 1, "total": 2}
    assert payload["outlets"]["dist"] == [1] and "dist_keys" not in payload["outlets"]
    html = bh.render_html("<script>/*__DATA__*/</script>", {"a": 1})
    assert html == '<script>const DATA={"a":1};</script>'


# --------------------------- parse_ga.py : table folding (no PDF needed) ----------

def test_parse_tables_tracks_state_and_continuation_rows():
    pg = load_funcs("parse_ga.py")
    tables = [[
        ["S. No", "GA ID", "GA", "Districts", "Entity"],
        ["Kerala", None, None, None, None],
        ["1", "9.1", "Kochi", "Ernakulam", "IOAGPL"],
        ["", "", "GA", "and Alappuzha", ""],
    ]]
    rows = []
    state = pg.parse_tables(tables, 3, None, rows)
    assert state == "Kerala" and len(rows) == 1
    assert rows[0]["districts"] == "Ernakulam and Alappuzha" and rows[0]["ga_name"] == "Kochi GA"
    assert rows[0]["page"] == 3 and rows[0]["sno"] == 1
