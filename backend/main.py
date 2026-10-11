
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Literal
import requests

from osm_service import get_resources
from routing import get_route
from optimizer import find_best_route

app = FastAPI(title="ReRoute API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173"
    ],
    allow_methods=["*"],
    allow_headers=["*"]
)


@app.get("/")
def home():
    return {"message": "Backend is running!"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/resources")
def resources(
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
    radius: int = Query(default=2000, ge=1, le=5000)
):
    try:
        return get_resources(latitude, longitude, radius)

    except requests.exceptions.RequestException as e:
        print("Overpass API error:", e)
        raise HTTPException(
            status_code=502,
            detail="Overpass API is currently unavailable"
        ) from e


@app.get("/route")
def route(
    start_lat: float = Query(ge=-90, le=90),
    start_lon: float = Query(ge=-180, le=180),
    end_lat: float = Query(ge=-90, le=90),
    end_lon: float = Query(ge=-180, le=180)
):
    try:
        route_data = get_route(
            start_lat, start_lon, end_lat, end_lon
        )

    except requests.exceptions.RequestException as e:
        print("Mapbox API error:", e)
        raise HTTPException(
            status_code=502,
            detail="Mapbox API is currently unavailable"
        ) from e

    if route_data is None:
        raise HTTPException(
            status_code=404,
            detail="No route found between the specified coordinates"
        )

    return route_data


class OptimizeRequest(BaseModel):
    start_lat: float = Field(ge=-90, le=90)
    start_lon: float = Field(ge=-180, le=180)
    end_lat: float = Field(ge=-90, le=90)
    end_lon: float = Field(ge=-180, le=180)

    facility_type: Literal[
        "Trash Bin",
        "Restroom",
        "Recycling Location"
    ]

    max_detour_minutes: float = Field(
        default=5, ge=0, le=30
    )


@app.post("/optimized-route")
def optimized_route(request: OptimizeRequest):
    try:
        result = find_best_route(
            request.start_lat,
            request.start_lon,
            request.end_lat,
            request.end_lon,
            request.facility_type,
            max_detour_minutes=request.max_detour_minutes
        )

    except requests.exceptions.RequestException as e:
        print("Optimization API error:", e)
        raise HTTPException(
            status_code=502,
            detail="External mapping service unavailable"
        ) from e

    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No direct walking route found"
        )

    return result



