"""Tests for the CNG/CGD retail-outlet mapping pipeline (scripts/*.py).

The pipeline scripts are written script-style: they run file/network I/O at module
top level, so a plain ``import`` isn't hermetic. Two helpers bridge that gap:

  * ``load_funcs()`` extracts only the top-level ``def``s, imports, and *literal*
    constant tables (via AST), executing none of the I/O body — giving clean,
    import-safe access to the pure functions (name normalizers, the SVG-path /
    coordinate projector, and the network ``fetch`` retry loop).
  * ``run_script()`` execs a whole script in a temp cwd against tiny fixture inputs
    for a true end-to-end run (``join_final.py`` is pure file-in/file-out, no
    network) — verifying output schema, alias/entity mapping, dedupe, and that a
    re-run is idempotent (overwrites, never doubles).
"""
import ast
import os
import types

import pytest

SCRIPTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"
)


# --------------------------- loaders --------------------------------------------

def _is_literal(node):
    """True for constant/list/tuple/set/dict literals (no calls, names, comprehensions)."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return _is_literal(node.operand)
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return all(_is_literal(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is None or _is_literal(k) for k in node.keys) and all(
            _is_literal(v) for v in node.values
        )
    return False


def load_funcs(name):
    """Load a script's defs + imports + literal constants only — no top-level I/O runs."""
    path = os.path.join(SCRIPTS, name)
    with open(path) as fh:
        tree = ast.parse(fh.read())
    keep = []
    for n in tree.body:
        if isinstance(
            n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ):
            keep.append(n)
        elif isinstance(n, ast.Assign) and _is_literal(n.value):
            keep.append(n)
    mod = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(mod)
    ns = types.ModuleType(name[:-3])
    ns.__file__ = path
    exec(compile(mod, path, "exec"), ns.__dict__)
    return ns


def run_script(name):
    """Exec a full script (in whatever the current cwd is) — for end-to-end runs."""
    path = os.path.join(SCRIPTS, name)
    with open(path) as fh:
        src = fh.read()
    ns = {"__name__": "__main__", "__file__": path}
    exec(compile(src, path, "exec"), ns)
    return ns


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
    # inject the projection constants normally computed from the geojson bbox
    bh.LOMIN, bh.LAMAX, bh.KX, bh.KY = 0.0, 10.0, 30.0, 30.0
    return bh


def test_px_projects_lonlat_to_pixels_north_up():
    bh = _load_projector()
    assert bh.px(1.0, 9.0) == (30.0, 30.0)
    # y grows downward as latitude drops (screen space is north-up)
    assert bh.px(0.0, 10.0)[1] < bh.px(0.0, 8.0)[1]


def test_ring_to_path_emits_svg_and_dedups_repeats():
    bh = _load_projector()
    path = bh.ring_to_path([(0, 10), (1, 10), (1, 10), (0, 9)])  # dup 2nd point
    assert path.startswith("M")
    assert path.endswith("Z")
    assert path.count("L") == 2  # duplicate collapsed: 3 distinct verts -> M + 2 L


def test_geom_to_path_handles_polygon_and_multipolygon():
    bh = _load_projector()
    poly = bh.geom_to_path({"type": "Polygon", "coordinates": [[[0, 10], [1, 10], [0, 9]]]})
    multi = bh.geom_to_path(
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
def crawl():
    mod = load_funcs("crawl_ssri.py")
    mod.time = types.SimpleNamespace(sleep=lambda *_: None)  # never really wait
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
    import importlib
    import sys
    sys.path.insert(0, SCRIPTS)
    for m in ("crawl_ssri",):
        sys.modules.pop(m, None)
    mod = importlib.import_module("crawl_ssri")   # would raise/hang if it crawled
    assert callable(mod.main)


def test_write_rows_dedups_by_id():
    """write_rows(rows, out, seen) — explicit args (the old `global done` was dead)."""
    import io
    import importlib
    import sys
    sys.path.insert(0, SCRIPTS)
    mod = importlib.import_module("crawl_ssri")
    out, seen = io.StringIO(), set()
    mod.write_rows([{"id": 1, "name": "A"}, {"id": 1, "name": "dupe"},
                    {"id": 2, "name": "B"}], out, seen)
    lines = out.getvalue().strip().splitlines()
    assert len(lines) == 2 and seen == {1, 2}
