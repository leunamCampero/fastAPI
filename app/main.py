"""
REST API for the cycling-network results of the PhD thesis.

Run it with:
    uvicorn app.main:app --reload
then open  http://127.0.0.1:8000/docs  (interactive documentation, try every endpoint)
      or   http://127.0.0.1:8000/map   (small web map that calls the API)

Each function below is an *endpoint*: the decorator (@app.get / @app.post) says which URL and
HTTP method call it; the function arguments become query parameters (simple types) or the JSON
body (Pydantic models); the return value is converted to JSON.
"""
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

from .cycling import (COST_MATRIX, DATA, RHO, SOLUTIONS, cyclist_distance, dos_table,
                      load_network, load_result)
from .schemas import (CyclistDistanceRequest, CyclistDistanceResponse, DosRow, NetworkSummary,
                      RouteResponse, Solution, UpgradeCostRequest, UpgradeCostResponse, Weight)

STATIC = Path(__file__).parent / "static"
MAX_SNAP_M = 1500  # a point further than this from the network is rejected

app = FastAPI(
    title="Cycling networks API - PhD results",
    description="Cyclist-distance model, safe routing on the Grenoble network and the result tables "
                "of the papers ECC 2025, CDC 2025, ITSC 2025, ITSC 2026 and T-ITS 2025.",
    version="1.0.0",
)
net = load_network()  # loaded once when the server starts


def _distance_m(lon1, lat1, lon2, lat2) -> float:
    k = np.cos(np.radians(lat1))
    return float(np.hypot((lon2 - lon1) * k, lat2 - lat1) * 111_320)


def _snap(lon: float, lat: float) -> int:
    node = net.nearest_node(lon, lat)
    d = _distance_m(lon, lat, net.lon[node], net.lat[node])
    if d > MAX_SNAP_M:
        raise HTTPException(422, f"point ({lat:.5f}, {lon:.5f}) is {d:.0f} m from the Grenoble network")
    return node


def _route_response(o: int, d: int, solution: str, weight: Weight, rho: float) -> RouteResponse:
    if o == d:
        raise HTTPException(422, "origin and destination snap to the same node")
    try:
        r = net.route(o, d, solution, weight=weight.value, rho=rho)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    lon, lat = net.route_coords(r)
    return RouteResponse(
        solution=solution, weight=weight, origin_node=o, destination_node=d, stats=r.to_dict(),
        geometry={"type": "LineString", "coordinates": [[x, y] for x, y in zip(lon, lat)]},
    )


# ----------------------------------------------------------------------------- general
@app.get("/", tags=["general"])
def root():
    return {"message": "Cycling networks API", "docs": "/docs", "map": "/map",
            "endpoints": sorted({r.path for r in app.routes if r.path.startswith("/") and
                                 not r.path.startswith(("/openapi", "/docs", "/redoc"))})}


@app.get("/health", tags=["general"])
def health():
    return {"status": "ok", "nodes": net.N, "edges": net.E}


@app.get("/map", tags=["general"], include_in_schema=False)
def web_map():
    return FileResponse(STATIC / "index.html")


# ----------------------------------------------------------------------------- model
@app.get("/model/dos", response_model=list[DosRow], tags=["model"])
def dos_classes(rho: float = Query(RHO, ge=0, le=1), psi: float = Query(0.84, gt=0, le=5)):
    """The six degree-of-separation classes with their traffic factor and penalties."""
    t = dos_table(rho, psi)
    return [DosRow(dos=r[0], description=r[1], aadt_veh_per_day=r[2], traffic_factor=r[3],
                   route_penalty_f_pow_rho=r[4], exposure_f_hat=r[5]) for r in t.itertuples(index=False)]


@app.post("/model/cyclist-distance", response_model=CyclistDistanceResponse, tags=["model"])
def compute_cyclist_distance(req: CyclistDistanceRequest):
    """Cyclist distance b = sum of d * s * f^rho over a list of segments."""
    seg = req.segments
    b = cyclist_distance([s.length_m for s in seg], [s.slope_pct for s in seg],
                         [s.dos for s in seg], req.rho, req.psi)
    total_len = sum(s.length_m for s in seg)
    return CyclistDistanceResponse(segments_m=b.round(2).tolist(), total_length_m=total_len,
                                   total_cyclist_distance_m=round(float(b.sum()), 2),
                                   overhead_pct=round(100 * (float(b.sum()) / total_len - 1), 2))


@app.post("/model/upgrade-cost", response_model=UpgradeCostResponse, tags=["model"])
def upgrade_cost(req: UpgradeCostRequest):
    """Cost of upgrading segments with the Cerema prices (EUR per metre)."""
    costs = [float(s.length_m * COST_MATRIX[s.from_dos, s.to_dos]) for s in req.segments]
    return UpgradeCostResponse(segments_eur=costs, total_eur=sum(costs),
                               share_of_grenoble_B_max=round(sum(costs) / net.max_budget(), 6))


# ----------------------------------------------------------------------------- network
@app.get("/network/solutions", tags=["network"])
def list_solutions():
    """The networks available: today's and the optimised ones of the papers."""
    return [{"solution": k, "label": v[0]} for k, v in SOLUTIONS.items()]


@app.get("/network/summary/{solution}", response_model=NetworkSummary, tags=["network"])
def network_summary(solution: Solution):
    """Km per DoS, upgrade cost and number of upgraded edges of one network."""
    return net.summary(solution.value)


@app.get("/network/geojson", tags=["network"])
def network_geojson(solution: Solution = Solution.original,
                    only_upgraded: bool = Query(False, description="only edges changed vs today")):
    """The network as a GeoJSON FeatureCollection (one LineString per edge, with its DoS)."""
    dos = net.dos(solution.value)
    idx = np.flatnonzero(dos != net.dos0) if only_upgraded else np.arange(net.E)
    feats = [{"type": "Feature",
              "properties": {"edge_id": int(i), "dos": int(dos[i]), "dos_today": int(net.dos0[i]),
                             "length_m": round(float(net.length[i]), 1)},
              "geometry": {"type": "LineString",
                           "coordinates": [[float(net.lon[net.u[i]]), float(net.lat[net.u[i]])],
                                           [float(net.lon[net.v[i]]), float(net.lat[net.v[i]])]]}}
             for i in idx]
    return {"type": "FeatureCollection", "features": feats}


@app.get("/network/nearest-node", tags=["network"])
def nearest_node(lat: float = Query(..., examples=[45.1885]), lon: float = Query(..., examples=[5.7245])):
    node = net.nearest_node(lon, lat)
    return {"node": node, "lat": float(net.lat[node]), "lon": float(net.lon[node]),
            "distance_m": round(_distance_m(lon, lat, net.lon[node], net.lat[node]), 1)}


@app.get("/network/zones", tags=["network"])
def zones():
    """The IRIS neighbourhoods of Grenoble (use their zone_id in /route/zones)."""
    z = net.zones[net.zones.zone_id.isin(net.nodes.zone_id.unique())]
    return z.sort_values("name").to_dict(orient="records")


@app.get("/network/zones.geojson", tags=["network"], include_in_schema=False)
def zones_geojson():
    return FileResponse(DATA / "network" / "grenoble_iris.geojson", media_type="application/geo+json")


# ----------------------------------------------------------------------------- routing
@app.get("/route", response_model=RouteResponse, tags=["routing"])
def route(from_lat: float = Query(..., examples=[45.1915]), from_lon: float = Query(..., examples=[5.7140]),
          to_lat: float = Query(..., examples=[45.1650]), to_lon: float = Query(..., examples=[5.7400]),
          solution: Solution = Solution.original, weight: Weight = Weight.cyclist,
          rho: float = Query(RHO, ge=0, le=1)):
    """Safest (weight=cyclist) or shortest (weight=length) bike route between two points."""
    return _route_response(_snap(from_lon, from_lat), _snap(to_lon, to_lat), solution.value, weight, rho)


@app.get("/route/zones", response_model=RouteResponse, tags=["routing"])
def route_zones(origin_zone: int = Query(..., examples=[48]), destination_zone: int = Query(..., examples=[80]),
                solution: Solution = Solution.original, weight: Weight = Weight.cyclist,
                rho: float = Query(RHO, ge=0, le=1)):
    """Route between the centres of two IRIS neighbourhoods (see /network/zones)."""
    try:
        o, d = net.zone_node(origin_zone), net.zone_node(destination_zone)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return _route_response(o, d, solution.value, weight, rho)


# ----------------------------------------------------------------------------- results
RESULTS = sorted(p.stem for p in (DATA / "results").glob("*.csv"))


@app.get("/results", tags=["results"])
def list_results():
    """Names of the result tables of the papers."""
    return RESULTS


@app.get("/results/{name}", tags=["results"])
def get_result(name: str, limit: int = Query(500, ge=1, le=5000)):
    """One result table as a list of rows (JSON)."""
    if name not in RESULTS:
        raise HTTPException(404, f"unknown table {name!r}; see /results")
    df = load_result(name).head(limit)
    return df.replace({np.nan: None}).to_dict(orient="records")
