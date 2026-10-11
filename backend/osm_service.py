
import requests

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

AMENITY_TAGS = {
    "Trash Bin": "waste_basket",
    "Restroom": "toilets",
    "Recycling Location": "recycling"
}


def fetch_resources(points, radius, facility_type=None):

    query_parts = []

    if facility_type is not None:
        amenities = [AMENITY_TAGS[facility_type]]
    else:
        amenities = ["waste_basket", "toilets", "recycling"]

    for latitude, longitude in points:
        for amenity in amenities:

            selector = "node" if amenity == "waste_basket" else "nwr"

            query_parts.append(
                f'{selector}["amenity"="{amenity}"]'
                f'(around:{radius},{latitude},{longitude});'
            )

    query = (
        "[out:json][timeout:30];"
        "(" + "".join(query_parts) + ");"
        "out center;"
    )

    headers = {
        "User-Agent": "ReRoute-HackRU/1.0",
        "Accept": "application/json"
    }

    response = requests.post(
        OVERPASS_API_URL,
        data={"data": query},
        headers=headers,
        timeout=40
    )

    if response.status_code != 200:
        print("Overpass error:", response.text[:1000])

    response.raise_for_status()

    data = response.json()
    resources = {}

    for element in data["elements"]:

        osm_type = element.get("type")
        osm_id = element.get("id")

        center = element.get("center") or {}

        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))

        if lat is None or lon is None:
            continue

        amenity = element.get("tags", {}).get("amenity")
        name = element.get("tags", {}).get("name", "Unknown")

        if amenity == "waste_basket":
            amenity = "Trash Bin"

        elif amenity == "toilets":
            amenity = "Restroom"

        elif amenity == "recycling":
            amenity = "Recycling Location"

        else:
            continue

        resource_id = f"{osm_type}/{osm_id}"

        resource = {
            "id": resource_id,
            "name": name,
            "type": amenity,
            "latitude": lat,
            "longitude": lon
        }

        resources[resource_id] = resource

    return list(resources.values())


def get_resources(latitude, longitude, radius=2000):
    return fetch_resources(
        [(latitude, longitude)],
        radius
    )


def get_resources_along_route(
    coordinates,
    radius=350,
    facility_type=None
):

    if not coordinates:
        return []

    count = min(6, len(coordinates))

    if count == 1:
        indices = [0]
    else:
        indices = sorted({
            round(i * (len(coordinates) - 1) / (count - 1))
            for i in range(count)
        })

    points = []

    for index in indices:
        lon, lat = coordinates[index]
        points.append((lat, lon))

    return fetch_resources(points, radius, facility_type)

