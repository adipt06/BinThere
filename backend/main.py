from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from osm_service import get_resources

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods = ["*"],
    allow_headers = ["*"]
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
        )

@app.get("/route")
def route():
    start_lat = Query(ge=-90, le=90)
    start_lon = Query(ge=-180, le=180)
    end_lat = Query(ge=-90, le=90)
    end_lon = Query(ge=-180, le=180)

    try:
        route_data = get_route(start_lat, start_lon, end_lat, end_lon)
        if route_data is None:
            raise HTTPException(
                status_code=404,
                detail="No route found between the specified coordinates"
            )
        return route_data

    except requests.exceptions.RequestException as e:
        print("Mapbox API error:", e)
        raise HTTPException(
            status_code=502,
            detail="Mapbox API is currently unavailable"
        )




