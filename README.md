# Cycling networks API (FastAPI)

A REST API serving the models and results of the PhD thesis
*Optimisation and comparison of urban cycling networks* (Manuel Campero Jurado, with
C. Canudas-de-Wit, G. De Nunzio and M. Salazar): the cyclist-distance model, safe routing on the
Grenoble bike network (today's and the optimised networks of the papers) and the result tables.
Full code and data of the papers: [PhD_tesis](https://github.com/leunamCampero/PhD_tesis).

## Run it

```bash
git clone https://github.com/leunamCampero/fastAPI.git
cd fastAPI

python -m venv .venv                 # 1. create the virtual environment (once)
.venv\Scripts\activate               # 2. activate it (Windows; macOS/Linux: source .venv/bin/activate)
pip install -r requirements.txt      # 3. install the packages (once)

uvicorn app.main:app --reload        # 4. start the server
```

Then open:

* **http://127.0.0.1:8000/docs** — interactive documentation: every endpoint, with a *Try it out* button
* **http://127.0.0.1:8000/map** — a web map that uses the API: click a start and a destination to
  compare the safest and the shortest bike route

`--reload` restarts the server when you edit the code. Tests: `python -m pytest -q`.

## Endpoints

| Method | Path | What it returns |
|---|---|---|
| GET | `/health` | server status, network size |
| GET | `/model/dos?rho=&psi=` | the 6 DoS classes with AADT, traffic factor, route penalty, exposure weight |
| POST | `/model/cyclist-distance` | cyclist distance of a list of segments `{length_m, slope_pct, dos}` |
| POST | `/model/upgrade-cost` | Cerema cost of upgrading segments `{length_m, from_dos, to_dos}` |
| GET | `/network/solutions` | today's network and the optimised networks of ECC / CDC / ITSC 2025 |
| GET | `/network/summary/{solution}` | km per DoS, upgrade cost, share of B_max, edges upgraded |
| GET | `/network/geojson?solution=&only_upgraded=` | the network as GeoJSON (DoS per edge) |
| GET | `/network/nearest-node?lat=&lon=` | closest network node to a point |
| GET | `/network/zones` | the 70 IRIS neighbourhoods of Grenoble |
| GET | `/route?from_lat=&from_lon=&to_lat=&to_lon=&solution=&weight=&rho=` | safest (`weight=cyclist`) or shortest (`weight=length`) route: stats + GeoJSON |
| GET | `/route/zones?origin_zone=&destination_zone=` | same, between two neighbourhoods |
| GET | `/results` and `/results/{name}` | result tables of the papers as JSON |

Examples:

```bash
curl "http://127.0.0.1:8000/network/summary/ecc2025_gab"
curl "http://127.0.0.1:8000/route/zones?origin_zone=52&destination_zone=115&solution=ecc2025_gab"
curl -X POST http://127.0.0.1:8000/model/upgrade-cost -H "Content-Type: application/json" \
     -d '{"segments": [{"length_m": 1000, "from_dos": 2, "to_dos": 6}]}'
```

```python
import requests
r = requests.get("http://127.0.0.1:8000/route",
                 params={"from_lat": 45.1915, "from_lon": 5.714, "to_lat": 45.165, "to_lon": 5.74})
print(r.json()["stats"])
```

## Layout

```
fastAPI/
├── app/
│   ├── main.py        the FastAPI app and all endpoints
│   ├── schemas.py     Pydantic models: request validation + response format (drive /docs)
│   ├── cycling.py     the model: traffic / slope factors, cyclist distance, costs, Dijkstra routing
│   └── static/index.html   the /map page (Leaflet)
├── data/              Grenoble network, optimised networks (solutions/), result tables (results/)
├── tests/test_api.py  16 tests with FastAPI's TestClient
└── requirements.txt
```

## Model

Each segment has a degree of separation (DoS) 1–6. Arc cost for routing:
b = d · s · f^ρ, with f = ψ·exp(AADT/1000) for DoS ≤ 4, 2.03ψ for DoS 5, ψ for DoS 6
(ψ = 0.84, ρ = 0.04), and s the slope factor (1 / 1.371 / 2.203 / 4.239 uphill, reciprocal downhill).
Route *exposure* = Σ d·f̂ in km, where f̂ is the min-max-normalised traffic factor
(1 km on DoS 1 = 1, DoS 6 = 0).
