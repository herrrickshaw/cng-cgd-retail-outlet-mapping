"""normalize.py body: PNGRB district cells -> one row per (GA, district) with notes."""
import json
import os

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "normalize.py")


def run(tmp_path, monkeypatch, cells):
    rows = [{"state": "S", "ga_id": f"g{i}", "ga_name": "GA  name", "districts": c, "entity": "E  Ltd"}
            for i, c in enumerate(cells)]
    (tmp_path / "ga_rows_raw.json").write_text(json.dumps(rows))
    monkeypatch.chdir(tmp_path)
    exec(compile(open(SCRIPT).read(), SCRIPT, "exec"), {"__name__": "__main__", "__file__": SCRIPT})
    return json.loads((tmp_path / "ga_districts.json").read_text())


def test_canonical_names_notes_and_splits(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, [
        "Kutch (East)",
        "Noida (including Greater Noida)",
        "Nalgonda Suryapet",
        "Pune District, Satara District and Sangli",
        "Bengaluru Rural and Urban Districts",
        "Ahmednagar (EAAA)",
    ])
    got = [(r["ga_id"], r["district"], r["note"]) for r in out]
    assert ("g0", "Kachchh", "East") in got
    assert ("g1", "Gautam Buddha Nagar", "including Greater Noida") in got
    assert ("g2", "Nalgonda", "") in got and ("g2", "Suryapet", "") in got
    assert [d for g, d, _ in got if g == "g3"] == ["Pune", "Satara", "Sangli"]
    assert [d for g, d, _ in got if g == "g4"] == ["Bengaluru Rural", "Bengaluru Urban"]
    assert ("g5", "Ahmednagar", "EAAA") in got
    assert all(r["ga_name"] == "GA name" and r["entity"] == "E Ltd" for r in out)


def test_multi_district_word_split(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch, ["Thane District Palghar District"])
    assert [r["district"] for r in out] == ["Thane", "Palghar"]
