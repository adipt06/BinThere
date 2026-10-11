
import mapboxgl from "mapbox-gl";
import "mapbox-gl/dist/mapbox-gl.css";
import "./style.css";

// Your Mapbox PUBLIC token
const MAPBOX_TOKEN = import.meta.env.VITE_MAPBOX_TOKEN;

const API_BASE = "http://127.0.0.1:8000";

mapboxgl.accessToken = MAPBOX_TOKEN;

const $ = (id) => document.getElementById(id);

// Map initialization
const map = new mapboxgl.Map({
  container: "map",
  style: "mapbox://styles/mapbox/standard",
  center: [-74.0060, 40.7128],
  zoom: 12,
  pitch: 45,
  bearing: -10
});

map.addControl(
  new mapboxgl.NavigationControl(),
  "top-right"
);

map.addControl(
  new mapboxgl.FullscreenControl(),
  "top-right"
);

// Application state
let userCoordinates = null;
let destinationCoordinates = null;
let selectingDestination = false;

let facilities = [];
let markers = [];

let locationMarker = null;
let destinationMarker = null;
let facilityMarker = null;

let requestCounter = 0;

const EMPTY_ROUTE = {
  type: "FeatureCollection",
  features: []
};

// Utility functions

function setStatus(message) {
  $("bin-status").textContent = message;
}

function formatDuration(seconds) {
  if (seconds < 60) {
    return `${Math.round(seconds)} sec`;
  }

  return `${(seconds / 60).toFixed(1)} min`;
}

function formatDistance(meters) {
  if (meters < 1000) {
    return `${Math.round(meters)} m`;
  }

  return `${(meters / 1000).toFixed(2)} km`;
}

// Calculate straight-line distance between two coordinates
function calculateDistance(pointA, pointB) {
  const toRadians = (value) => value * Math.PI / 180;

  const [lon1, lat1] = pointA;
  const [lon2, lat2] = pointB;

  const deltaLat = toRadians(lat2 - lat1);
  const deltaLon = toRadians(lon2 - lon1);

  const a =
    Math.sin(deltaLat / 2) ** 2 +
    Math.cos(toRadians(lat1)) *
    Math.cos(toRadians(lat2)) *
    Math.sin(deltaLon / 2) ** 2;

  return 6371000 * 2 * Math.asin(
    Math.sqrt(Math.min(1, a))
  );
}

// Send requests to FastAPI
async function apiRequest(path, options = {}) {
  const response = await fetch(API_BASE + path, options);

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Backend error: ${response.status}`
    );
  }

  return data;
}

// Find facilities using your Overpass backend
async function fetchFacilities() {
  if (!userCoordinates) {
    return;
  }

  const [longitude, latitude] = userCoordinates;
  const radius = Number($("distance-filter").value);

  setStatus("Searching for nearby facilities...");

  try {
    const params = new URLSearchParams({
      latitude,
      longitude,
      radius
    });

    facilities = await apiRequest(`/resources?${params}`);

    renderFacilities();

    setStatus(`Found ${facilities.length} mapped facilities.`);
  } catch (error) {
    setStatus(`Could not load facilities: ${error.message}`);
  }
}

// Apply search and facility filters
function getVisibleFacilities() {
  const search = $("bin-search").value.trim().toLowerCase();
  const type = $("facility-filter").value;

  return facilities
    .filter((facility) => {
      const matchesType =
        type === "All" || facility.type === type;

      const matchesSearch =
        !search ||
        `${facility.name} ${facility.type}`
          .toLowerCase()
          .includes(search);

      return matchesType && matchesSearch;
    })
    .sort((a, b) => {
      if (!userCoordinates) return 0;

      const distanceA = calculateDistance(
        userCoordinates,
        [a.longitude, a.latitude]
      );

      const distanceB = calculateDistance(
        userCoordinates,
        [b.longitude, b.latitude]
      );

      return distanceA - distanceB;
    });
}

// Select a facility
function selectFacility(facility) {
  map.flyTo({
    center: [facility.longitude, facility.latitude],
    zoom: 16
  });

  setStatus(`Selected ${facility.type}`);

  getDirectRoute(facility);
}

// Display facilities on the map and in the sidebar
function renderFacilities() {
  markers.forEach((marker) => marker.remove());
  markers = [];

  const visibleFacilities = getVisibleFacilities();

  const container = $("bin-results");
  container.replaceChildren();

  $("results-count").textContent =
    `${visibleFacilities.length} found`;

  $("results-subtitle").textContent =
    "Sorted by straight-line distance";

  if (visibleFacilities.length === 0) {
    container.textContent = "No matching facilities found.";
    return;
  }

  for (const facility of visibleFacilities) {
    const coordinates = [
      facility.longitude,
      facility.latitude
    ];

    const name = facility.name === "Unknown"
      ? facility.type
      : facility.name;

    const distance = userCoordinates
      ? calculateDistance(userCoordinates, coordinates)
      : null;

    const button = document.createElement("button");
    button.className = "bin-card";
    button.type = "button";

    const title = document.createElement("strong");
    title.textContent = name;

    const description = document.createElement("span");
    description.textContent = distance === null
      ? facility.type
      : `${facility.type} · ${formatDistance(distance)} away`;

    button.append(title, description);

    button.addEventListener("click", () => {
      selectFacility(facility);
    });

    container.appendChild(button);

    let color = "#216b49";

    if (facility.type === "Restroom") {
      color = "#8054c8";
    } else if (facility.type === "Recycling Location") {
      color = "#247ce3";
    }

    const marker = new mapboxgl.Marker({ color })
      .setLngLat(coordinates)
      .setPopup(
        new mapboxgl.Popup().setText(name)
      )
      .addTo(map);

    marker.getElement().addEventListener("click", () => {
      selectFacility(facility);
    });

    markers.push(marker);
  }
}

// Draw GeoJSON route from FastAPI
function drawRoute(geometry) {
  const source = map.getSource("route");

  if (!source || !geometry?.coordinates?.length) {
    return;
  }

  source.setData({
    type: "Feature",
    properties: {},
    geometry
  });

  const bounds = new mapboxgl.LngLatBounds();

  geometry.coordinates.forEach((coordinate) => {
    bounds.extend(coordinate);
  });

  map.fitBounds(bounds, {
    padding: {
      top: 70,
      bottom: 70,
      right: 70,
      left: window.innerWidth > 600 ? 420 : 70
    },
    maxZoom: 17
  });
}

// Get direct walking directions from your backend
async function getDirectRoute(facility) {
  if (!userCoordinates) {
    setStatus("Allow location access first.");
    return;
  }

  const requestId = ++requestCounter;

  const [start_lon, start_lat] = userCoordinates;

  const end_lat = facility.latitude;
  const end_lon = facility.longitude;

  const params = new URLSearchParams({
    start_lat,
    start_lon,
    end_lat,
    end_lon
  });

  setStatus("Calculating walking route...");

  try {
    const route = await apiRequest(`/route?${params}`);

    if (requestId !== requestCounter) return;

    drawRoute(route.geometry);

    $("directions-section").hidden = false;

    $("directions-destination").textContent =
      facility.name === "Unknown"
        ? facility.type
        : facility.name;

    $("route-duration").textContent =
      formatDuration(route.duration);

    $("route-distance").textContent =
      formatDistance(route.distance);

    $("detour-info").textContent =
      "Direct walking route to this facility.";

    setStatus("Walking route calculated.");
  } catch (error) {
    if (requestId === requestCounter) {
      setStatus(`Routing failed: ${error.message}`);
    }
  }
}

// Request your custom optimization algorithm
async function getOptimizedRoute() {
  if (!userCoordinates || !destinationCoordinates) {
    setStatus("Allow location access and select a destination first.");
    return;
  }

  const facilityType = $("facility-filter").value;

  if (facilityType === "All") {
    setStatus("Choose a specific facility type before optimizing.");
    return;
  }

  const maxDetour = Number($("detour-filter").value);

  if (!Number.isFinite(maxDetour) ||
      maxDetour < 0 || maxDetour > 30) {
    setStatus("Maximum detour must be between 0 and 30 minutes.");
    return;
  }

  const requestId = ++requestCounter;

  const [start_lon, start_lat] = userCoordinates;
  const [end_lon, end_lat] = destinationCoordinates;

  const body = {
    start_lat,
    start_lon,
    end_lat,
    end_lon,
    facility_type: facilityType,
    max_detour_minutes: maxDetour
  };

  setStatus("Optimizing route. This may take a moment...");

  try {
    const result = await apiRequest("/optimized-route", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify(body)
    });

    if (requestId !== requestCounter) return;

    const route = result.optimized_route || result.direct_route;

    drawRoute(route.geometry);

    // Show the recommended facility
    if (facilityMarker) {
      facilityMarker.remove();
      facilityMarker = null;
    }

    if (result.facility) {
      facilityMarker = new mapboxgl.Marker({
        color: "#ff9f1c"
      })
        .setLngLat([
          result.facility.longitude,
          result.facility.latitude
        ])
        .addTo(map);
    }

    $("directions-section").hidden = false;

    $("directions-destination").textContent =
      result.facility
        ? `Via ${result.facility.type}`
        : "Direct walking route";

    $("route-duration").textContent =
      formatDuration(route.duration);

    $("route-distance").textContent =
      formatDistance(route.distance);

    if (result.facility) {
      $("detour-info").textContent =
        `Extra walking: ${result.detour_seconds.toFixed(1)} seconds. ` +
        `${result.candidates_evaluated} facilities evaluated.`;
    } else {
      $("detour-info").textContent =
        "No suitable facility found within your detour limit.";
    }

    setStatus(result.message);
  } catch (error) {
    if (requestId === requestCounter) {
      setStatus(`Optimization failed: ${error.message}`);
    }
  }
}

// Set final destination from map click
function setDestination(coordinates) {
  destinationCoordinates = coordinates;

  if (destinationMarker) {
    destinationMarker.remove();
  }

  destinationMarker = new mapboxgl.Marker({
    color: "#e34c4c"
  })
    .setLngLat(coordinates)
    .addTo(map);

  selectingDestination = false;

  $("choose-destination-button").textContent =
    "Change destination on map";

  $("destination-hint").textContent =
    `Destination: ${coordinates[1].toFixed(5)}, ` +
    `${coordinates[0].toFixed(5)}`;

  setStatus("Destination selected. You can optimize the route.");
}

// Update user location
function updateLocation(coordinates) {
  userCoordinates = coordinates;

  if (!locationMarker) {
    locationMarker = new mapboxgl.Marker({
      color: "#3987ff"
    })
      .setLngLat(coordinates)
      .addTo(map);
  } else {
    locationMarker.setLngLat(coordinates);
  }

  map.flyTo({
    center: coordinates,
    zoom: 15
  });

  fetchFacilities();
}

// Ask browser for location permission
function requestLocation() {
  if (!navigator.geolocation) {
    setStatus("Geolocation is not supported.");
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (position) => {
      updateLocation([
        position.coords.longitude,
        position.coords.latitude
      ]);
    },
    () => {
      setStatus("Unable to access location. Check browser permissions.");
    },
    {
      enableHighAccuracy: true,
      timeout: 15000,
      maximumAge: 30000
    }
  );
}

// Initialize map route layers
map.on("load", () => {
  map.addSource("route", {
    type: "geojson",
    data: EMPTY_ROUTE
  });

  map.addLayer({
    id: "route-outline",
    type: "line",
    source: "route",
    slot: "middle",
    layout: {
      "line-cap": "round",
      "line-join": "round"
    },
    paint: {
      "line-color": "#ffffff",
      "line-width": 9
    }
  });

  map.addLayer({
    id: "route-line",
    type: "line",
    source: "route",
    slot: "middle",
    layout: {
      "line-cap": "round",
      "line-join": "round"
    },
    paint: {
      "line-color": "#216b49",
      "line-width": 5
    }
  });

  requestLocation();
});

// Map click for destination selection
map.on("click", (event) => {
  if (selectingDestination) {
    setDestination([
      event.lngLat.lng,
      event.lngLat.lat
    ]);
  }
});

map.on("error", (event) => {
  console.error("Mapbox error:", event.error);
});

// UI event listeners

$("search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  renderFacilities();
});

$("bin-search").addEventListener("input", renderFacilities);

$("facility-filter").addEventListener("change", renderFacilities);

$("distance-filter").addEventListener("change", fetchFacilities);

$("nearest-button").addEventListener("click", () => {
  if (!userCoordinates) {
    requestLocation();
    return;
  }

  const bins = facilities
    .filter((facility) => facility.type === "Trash Bin")
    .sort((a, b) => {
      return calculateDistance(
        userCoordinates,
        [a.longitude, a.latitude]
      ) - calculateDistance(
        userCoordinates,
        [b.longitude, b.latitude]
      );
    });

  if (bins.length > 0) {
    selectFacility(bins[0]);
  } else {
    setStatus("No trash bins found in the selected radius.");
  }
});

$("my-location-button").addEventListener("click", requestLocation);

$("choose-destination-button").addEventListener("click", () => {
  selectingDestination = true;
  setStatus("Click anywhere on the map to choose your destination.");
});

$("optimize-button").addEventListener("click", getOptimizedRoute);

$("clear-route-button").addEventListener("click", () => {
  requestCounter++;

  const source = map.getSource("route");

  if (source) {
    source.setData(EMPTY_ROUTE);
  }

  if (facilityMarker) {
    facilityMarker.remove();
    facilityMarker = null;
  }

  $("directions-section").hidden = true;
  setStatus("Route cleared.");
});
