import os
import requests
from dotenv import load_dotenv

load_dotenv()
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN")

def get_route(start_lat, start_lon, end_lat, end_lon):
    
    url = (
        "https://api.mapbox.com/directions/v5/mapbox/walking/"
        f"{start_lon},{start_lat};{end_lon},{end_lat}"
    )

    params = {
        "access_token": MAPBOX_TOKEN,
        "geometries": "geojson",
        "overview": "full",
    }

    response = requests.get(url, params=params , timeout = 20)
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
    start_lat = 40.5008
    start_lon = -74.4474

    end_lat = 40.5020
    end_lon = -74.4500

    route = get_route(start_lat, start_lon, end_lat, end_lon)

    if route is not None:
        print("Distance:", route["distance"], "meters")
        print("Duration:", route["duration"], "seconds")
        print("Geometry:", route["geometry"])
    else:
        print("No route found")




