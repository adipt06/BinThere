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





