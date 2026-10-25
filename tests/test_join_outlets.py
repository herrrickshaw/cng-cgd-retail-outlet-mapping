"""join_outlets.py end to end on a two-district toy map (temp cwd, no network)."""
import csv
import json
import os

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "join_outlets.py")


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def run(tmp_path, monkeypatch, pumps):
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"st_nm": "Gujarat", "district": "Alpha"}, "geometry": square(72, 22, 73, 23)},
        {"type": "Feature", "properties": {"st_nm": "Gujarat", "district": "Beta"}, "geometry": square(73, 22, 74, 23)},
    ]}
    (tmp_path / "india_districts_clean.geojson").write_text(json.dumps(gj))
    (tmp_path / "district_alloc.json").write_text(json.dumps({
        "Gujarat|Alpha": [{"entity": "Gujarat Gas", "ga_id": "9.1", "ga_name": "Alpha GA"},
                          {"entity": "Adani Total Gas", "ga_id": "9.2", "ga_name": "Alpha-2 GA"}]}))
    with open(tmp_path / "ssri_pumps_raw.jsonl", "w") as fh:
        for p in pumps:
            fh.write(json.dumps(p) + "\n")
    monkeypatch.chdir(tmp_path)
    src = open(SCRIPT).read()
    exec(compile(src, SCRIPT, "exec"), {"__name__": "__main__", "__file__": SCRIPT})
    with open(tmp_path / "outlets_cgd.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    return {r["outlet_id"]: r for r in rows}, json.loads((tmp_path / "outlets_map.json").read_text())


def pump(i, lat, lon, name=None, company="IOCL", **kw):
    d = {"id": i, "name": name or f"P{i}", "company": company, "latitude": lat, "longitude": lon,
         "address": f"addr {i}", "state": "Gujarat", "district": "raw", "has_cng": False, "cng_price": None}
    d.update(kw)
    return d


def test_point_in_polygon_entities_and_status(tmp_path, monkeypatch):
    rows, _ = run(tmp_path, monkeypatch, [pump(1, 22.5, 72.5, has_cng=True, cng_price=80.5),
                                          pump(2, 22.5, 73.5)])
    a, b = rows["1"], rows["2"]
    assert (a["district"], a["cgd_entity"], a["ga_id"]) == ("Alpha", "Adani Total Gas; Gujarat Gas", "9.1; 9.2")
    assert a["cgd_status"] == "CGD GA authorised" and a["cng_price"] == "80.5"
    assert (b["district"], b["cgd_status"], b["cgd_entity"]) == ("Beta", "no authorised CGD GA", "")


def test_nearest_district_fallback_and_offshore(tmp_path, monkeypatch):
    # 0.03 deg (~3 km) west of Alpha's edge -> snapped to Alpha; 0.2 deg away -> unassigned
    rows, m = run(tmp_path, monkeypatch, [pump(1, 22.5, 71.97), pump(2, 22.5, 71.8)])
    assert rows["1"]["district"] == "Alpha"
    assert rows["2"]["cgd_status"] == "outside district map"
    assert rows["2"]["district"] == "raw"  # falls back to the SSRI-reported district
    assert len(m["lat"]) == 1  # unassigned outlets are left off the map payload


def test_content_duplicates_and_bad_coordinates_dropped(tmp_path, monkeypatch):
    rows, m = run(tmp_path, monkeypatch, [
        pump(1, 22.5, 72.5, name="Same", address="A"), pump(2, 22.5, 72.5, name="Same", address="A"),  # same content, new id
        pump(3, 22.5, 72.5, name="Other"),                                     # same spot, different pump
        pump(4, None, 72.5), pump(5, "x", 72.5), pump(6, 51.5, -0.1),          # bad / outside India box
    ])
    assert sorted(rows) == ["1", "3"]
    assert m["dist_keys"] == ["Gujarat|Alpha"] and m["dist"] == [0, 0]
    assert m["companies"] == ["IOCL"]
