"""
Tests of the API. TestClient calls the app in-process (no server needed).

    python -m pytest -q
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

GARE = (45.1915, 5.7140)            # railway station
VILLAGE_OLYMPIQUE = (45.1650, 5.7400)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "nodes": 3452, "edges": 4993}


def test_map_page_served():
    r = client.get("/map")
    assert r.status_code == 200 and "leaflet" in r.text


def test_dos_table():
    rows = client.get("/model/dos").json()
    assert [r["dos"] for r in rows] == [6, 5, 4, 3, 2, 1]
    assert rows[0]["traffic_factor"] == pytest.approx(0.84)
    assert rows[-1]["exposure_f_hat"] == pytest.approx(1.0)


def test_cyclist_distance_penalises_traffic_and_slope():
    body = {"segments": [{"length_m": 100, "slope_pct": 0, "dos": 6},
                         {"length_m": 100, "slope_pct": 0, "dos": 1},
                         {"length_m": 100, "slope_pct": 5, "dos": 6}]}
    r = client.post("/model/cyclist-distance", json=body).json()
    sep, busy, uphill = r["segments_m"]
    assert busy > sep and uphill == pytest.approx(sep * 2.203, rel=1e-3)


def test_validation_rejects_bad_dos():
    r = client.post("/model/cyclist-distance", json={"segments": [{"length_m": 100, "dos": 7}]})
    assert r.status_code == 422


def test_upgrade_cost():
    r = client.post("/model/upgrade-cost",
                    json={"segments": [{"length_m": 1000, "from_dos": 2, "to_dos": 6}]}).json()
    assert r["total_eur"] == 600_000


def test_upgrade_cost_rejects_downgrade():
    r = client.post("/model/upgrade-cost",
                    json={"segments": [{"length_m": 1000, "from_dos": 5, "to_dos": 2}]})
    assert r.status_code == 422


@pytest.mark.parametrize("solution,share,km6", [("original", 0.0, 31.03),
                                                ("ecc2025_gab", 0.5, 127.28),
                                                ("ecc2025_mlcc", 0.5, 189.05)])
def test_network_summary_matches_paper(solution, share, km6):
    r = client.get(f"/network/summary/{solution}").json()
    assert r["share_of_B_max"] == pytest.approx(share, abs=1e-3)
    assert r["km_per_dos"]["6"] == pytest.approx(km6, abs=0.01)


def test_unknown_solution_is_422():
    assert client.get("/network/summary/nope").status_code == 422


def test_geojson_only_upgraded():
    gj = client.get("/network/geojson", params={"solution": "cdc2025_ga_u", "only_upgraded": True}).json()
    assert gj["type"] == "FeatureCollection"
    assert 0 < len(gj["features"]) < 4993
    assert all(f["properties"]["dos"] > f["properties"]["dos_today"] for f in gj["features"])


def test_route_safe_vs_short():
    q = {"from_lat": GARE[0], "from_lon": GARE[1], "to_lat": VILLAGE_OLYMPIQUE[0], "to_lon": VILLAGE_OLYMPIQUE[1]}
    safe = client.get("/route", params={**q, "weight": "cyclist"}).json()
    short = client.get("/route", params={**q, "weight": "length"}).json()
    assert safe["geometry"]["type"] == "LineString"
    assert short["stats"]["length_km"] <= safe["stats"]["length_km"]
    assert safe["stats"]["exposure_km_equiv"] <= short["stats"]["exposure_km_equiv"]


def test_route_outside_grenoble_rejected():
    r = client.get("/route", params={"from_lat": 48.85, "from_lon": 2.35, "to_lat": 45.18, "to_lon": 5.72})
    assert r.status_code == 422


def test_route_zones():
    r = client.get("/route/zones", params={"origin_zone": 52, "destination_zone": 115})
    assert r.status_code == 200
    assert client.get("/route/zones", params={"origin_zone": 1, "destination_zone": 115}).status_code == 404


def test_results():
    names = client.get("/results").json()
    assert "ecc2025_table3" in names
    rows = client.get("/results/ecc2025_table3").json()
    assert [r["solution"] for r in rows] == ["Original", "GAB", "MLCC"]
    assert client.get("/results/does_not_exist").status_code == 404
