
import requests
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN")


def get_route(start_lat, start_lon, end_lat, end_lon, stop=None):

    if not MAPBOX_TOKEN:
        raise RuntimeError("MAPBOX_TOKEN is missing")

    coordinates = f"{start_lon},{start_lat}"

    if stop is not None:
        coordinates += f";{stop['longitude']},{stop['latitude']}"

    coordinates += f";{end_lon},{end_lat}"

    url = (
        "https://api.mapbox.com/directions/v5/mapbox/walking/"
        + coordinates
    )

    params = {
        "access_token": MAPBOX_TOKEN,
        "geometries": "geojson",
        "overview": "full"
    }

    response = requests.get(url, params=params, timeout=15)
    response.raise_for_status()

    data = response.json()

    if data.get("code") != "Ok" or not data.get("routes"):
        return None

    route = data["routes"][0]

    return {
        "distance": route["distance"],
        "duration": route["duration"],
        "geometry": route["geometry"]
    }


if __name__ == "__main__":
    result = get_route(
        40.7661, -73.9772,
        40.7681, -73.9819
    )

    print(result)


