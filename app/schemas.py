"""
Pydantic models: they describe the JSON that goes in and out of the API.

FastAPI uses them to (1) validate requests - a wrong type or a DoS of 7 is rejected with a
clear 422 error before your code runs - and (2) generate the interactive docs at /docs.
"""
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from .cycling import SOLUTIONS

# An Enum gives a drop-down in /docs and rejects unknown names automatically.
Solution = Enum("Solution", {k.replace(".", "_"): k for k in SOLUTIONS}, type=str)


class Weight(str, Enum):
    cyclist = "cyclist"
    length = "length"


class DosRow(BaseModel):
    dos: int
    description: str
    aadt_veh_per_day: int
    traffic_factor: float
    route_penalty_f_pow_rho: float
    exposure_f_hat: float


class Segment(BaseModel):
    length_m: float = Field(gt=0, examples=[500])
    slope_pct: float = Field(0, ge=-30, le=30, description="positive = uphill", examples=[3])
    dos: int = Field(ge=1, le=6, examples=[2])


class CyclistDistanceRequest(BaseModel):
    segments: list[Segment] = Field(min_length=1)
    rho: float = Field(0.04, ge=0, le=1)
    psi: float = Field(0.84, gt=0, le=5)


class CyclistDistanceResponse(BaseModel):
    segments_m: list[float]
    total_length_m: float
    total_cyclist_distance_m: float
    overhead_pct: float


class UpgradeSegment(BaseModel):
    length_m: float = Field(gt=0, examples=[1000])
    from_dos: int = Field(ge=1, le=6, examples=[2])
    to_dos: int = Field(ge=1, le=6, examples=[6])

    @model_validator(mode="after")
    def no_downgrade(self):
        if self.to_dos < self.from_dos:
            raise ValueError("to_dos must be >= from_dos (the model only upgrades)")
        return self


class UpgradeCostRequest(BaseModel):
    segments: list[UpgradeSegment] = Field(min_length=1)


class UpgradeCostResponse(BaseModel):
    segments_eur: list[float]
    total_eur: float
    share_of_grenoble_B_max: float


class NetworkSummary(BaseModel):
    solution: str
    label: str
    km_per_dos: dict[int, float]
    upgrade_cost_eur: int
    share_of_B_max: float
    edges_upgraded: int


class RouteStats(BaseModel):
    n_nodes: int
    length_km: float
    cyclist_distance_km: float
    km_per_dos: dict[int, float]
    km_exposed_dos_1_3: float
    exposure_km_equiv: float


class RouteResponse(BaseModel):
    solution: str
    weight: Weight
    origin_node: int
    destination_node: int
    stats: RouteStats
    geometry: dict = Field(description="GeoJSON LineString of the route")
