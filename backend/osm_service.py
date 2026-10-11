import requests

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"


def fetch_resources(points, radius):

    query_parts = []

    for latitude, longitude in points:
        query_parts.append(
            f'node["amenity"="waste_basket"](around:{radius},{latitude},{longitude});'
        )
        query_parts.append(
            f'nwr["amenity"="toilets"](around:{radius},{latitude},{longitude});'
        )
        query_parts.append(
            f'nwr["amenity"="recycling"](around:{radius},{latitude},{longitude});'
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


def get_resources_along_route(coordinates, radius=350):

    if not coordinates:
        return []

    count = min(12, len(coordinates))

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

    return fetch_resources(points, radius)

        
