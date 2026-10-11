
import math
import requests

from osm_service import get_resources_along_route
from routing import get_route


def distance_to_route(resource, coordinates):

    latitude = resource["latitude"]
    longitude = resource["longitude"]

    scale_x = 111320 * math.cos(math.radians(latitude))
    scale_y = 111320

    points = []

    for lon, lat in coordinates:
        x = (lon - longitude) * scale_x
        y = (lat - latitude) * scale_y
        points.append((x, y))

    if len(points) == 1:
        return math.hypot(*points[0])

    closest = float("inf")

    for i in range(len(points) - 1):

        ax, ay = points[i]
        bx, by = points[i + 1]

        dx = bx - ax
        dy = by - ay

        length_squared = dx * dx + dy * dy

        if length_squared == 0:
            t = 0
        else:
            t = -(ax * dx + ay * dy) / length_squared
            t = max(0, min(1, t))

        x = ax + t * dx
        y = ay + t * dy

        distance = math.hypot(x, y)
        closest = min(closest, distance)

    return closest


def find_best_route(
    start_lat,
    start_lon,
    end_lat,
    end_lon,
    facility_type,
    max_detour_minutes=5,
    max_candidates=8
):

    direct_route = get_route(
        start_lat, start_lon, end_lat, end_lon
    )

    if direct_route is None:
        return None

    coordinates = direct_route["geometry"]["coordinates"]

    resources = get_resources_along_route(
        coordinates,
        facility_type=facility_type
    )

    candidates = []

    for resource in resources:
        if resource["type"] == facility_type:
            candidates.append(resource)

    candidates.sort(
        key=lambda resource: distance_to_route(
            resource, coordinates
        )
    )

    candidates = candidates[:max_candidates]

    best_route = None
    best_facility = None
    best_detour = float("inf")
    evaluated = 0

    for facility in candidates:

        try:
            alternative = get_route(
                start_lat,
                start_lon,
                end_lat,
                end_lon,
                stop=facility
            )

        except requests.exceptions.HTTPError as error:
            if (
                error.response is not None
                and error.response.status_code == 422
            ):
                continue
            raise

        if alternative is None:
            continue

        evaluated += 1

        detour = max(
            0,
            alternative["duration"] - direct_route["duration"]
        )

        if (
            detour <= max_detour_minutes * 60
            and detour < best_detour
        ):
            best_detour = detour
            best_route = alternative
            best_facility = facility

    if best_route is not None:
        summary = {
            "direct_distance_meters": round(direct_route["distance"], 2),
            "direct_duration_minutes": round(direct_route["duration"] / 60, 2),
            "optimized_distance_meters": round(best_route["distance"], 2),
            "optimized_duration_minutes": round(best_route["duration"] / 60, 2),
            "extra_distance_meters": round(
                best_route["distance"] - direct_route["distance"], 2
            ),
            "detour_minutes": round(best_detour / 60, 2),
            "detour_seconds": round(best_detour, 2),
            "facility_type": best_facility["type"],
            "facility_latitude": best_facility["latitude"],
            "facility_longitude": best_facility["longitude"]
        }
    else:
        summary = {
            "direct_distance_meters": round(direct_route["distance"], 2),
            "direct_duration_minutes": round(direct_route["duration"] / 60, 2),
            "optimized_distance_meters": None,
            "optimized_duration_minutes": None,
            "extra_distance_meters": None,
            "detour_minutes": None,
            "detour_seconds": None,
            "facility_type": None,
            "facility_latitude": None,
            "facility_longitude": None
        }

    return {
        "summary": summary,
        "direct_route": direct_route,
        "optimized_route": best_route,
        "facility": best_facility,
        "detour_seconds": (
            best_detour if best_route is not None else None
        ),
        "candidates_evaluated": evaluated,
        "message": (
            "Route found"
            if best_route is not None
            else "No matching facility within the detour limit"
        )
    }
