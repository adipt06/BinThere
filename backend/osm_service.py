import requests

OVERPASS_API_URL = "https://overpass-api.de/api/interpreter"

AMENITY_TAGS = {
    "Trash Bin": "waste_basket",
    "Restroom": "toilets",
    "Recycling Location": "recycling"
}


def fetch_overpass(query):

    response = requests.post(
        OVERPASS_API_URL,
        data={"data": query},
        headers={
            "User-Agent": "ReRoute-HackRU/1.0",
            "Accept": "application/json"
        },
        timeout=35
    )

    if response.status_code != 200:
        print("Overpass error:", response.text[:500])

    response.raise_for_status()

    resources = {}

    for element in response.json().get("elements", []):

        center = element.get("center") or {}

        lat = element.get("lat", center.get("lat"))
        lon = element.get("lon", center.get("lon"))

        if lat is None or lon is None:
            continue

        amenity = element.get("tags", {}).get("amenity")

        names = {
            "waste_basket": "Trash Bin",
            "toilets": "Restroom",
            "recycling": "Recycling Location"
        }

        if amenity not in names:
            continue

        resource_id = f'{element["type"]}/{element["id"]}'

        resources[resource_id] = {
            "id": resource_id,
            "name": element.get("tags", {}).get("name", "Unknown"),
            "type": names[amenity],
            "latitude": lat,
            "longitude": lon
        }

    return list(resources.values())


def get_resources(latitude, longitude, radius=2000):

    query = f"""
    [out:json][timeout:25];
    (
        node["amenity"="waste_basket"](around:{radius},{latitude},{longitude});
        nwr["amenity"="toilets"](around:{radius},{latitude},{longitude});
        nwr["amenity"="recycling"](around:{radius},{latitude},{longitude});
    );
    out center;
    """

    return fetch_overpass(query)


def get_resources_along_route(
    coordinates,
    radius=200,
    facility_type=None
):

    if not coordinates:
        return []

    # Limit how many points are included in the query
    count = min(20, len(coordinates))

    if count == 1:
        indices = [0]
    else:
        indices = sorted({
            round(i * (len(coordinates) - 1) / (count - 1))
            for i in range(count)
        })

    route_points = []

    for index in indices:
        lon, lat = coordinates[index]
        route_points.append(f"{lat},{lon}")

    # One route corridor instead of many separate searches
    path = ",".join(route_points)

    if facility_type is not None:

        amenity = AMENITY_TAGS[facility_type]
        selector = "node" if amenity == "waste_basket" else "nwr"

        query = f"""
        [out:json][timeout:25];
        {selector}["amenity"="{amenity}"](around:{radius},{path});
        out center;
        """

    else:
        query = f"""
        [out:json][timeout:25];
        (
            node["amenity"="waste_basket"](around:{radius},{path});
            nwr["amenity"="toilets"](around:{radius},{path});
            nwr["amenity"="recycling"](around:{radius},{path});
        );
        out center;
        """

    return fetch_overpass(query)

