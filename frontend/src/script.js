import { initializeTabs } from './tabs.js';
import { initializeCommunity, appendCommunityReport } from './community.js';
import { initializeAssistant } from './ai_assistant.js';
import 'mapbox-gl/dist/mapbox-gl.css';
import './style.css';
import { RequestLane, validCoordinate, validateRoute, distance, filterFacilities } from './state.js';
const $ = id => document.getElementById(id);
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');
const EMPTY = { type: 'FeatureCollection', features: [] };
const lanes = Object.fromEntries(['route', 'facilities', 'start', 'destination'].map(k => [k, new RequestLane()]));
let map, mapboxgl, ready = false, start = null, destination = null, selection = null;
let facilityState = 'idle', facilityError = '', facilityWarnings = [], categoryStates = {}, facilityPartial = false;
let facilities = [], facilityMarkers = [], startMarker, destinationMarker, recommendedMarker, gpsGeneration = 0;
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const colors = { 'Trash Bin': '#216b49', Restroom: '#8054c8', 'Recycling Location': '#247ce3' };
const routeButtons = ['direct-route-button', 'optimize-button', 'nearest-button'];
const formatDistance = m => Math.abs(m) < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(2)} km`;
const formatDuration = s => s < 60 ? `${Math.round(s)} sec` : `${(s / 60).toFixed(1)} min`;
const facilityName = f => f.name && f.name !== 'Unknown' ? f.name : f.type;
const status = message => { $('bin-status').textContent = message; $('map-status').textContent = message; };
async function api(path, options = {}) {
  let response;
  try {
    const timeout = path === '/optimized-route' ? 180000 : 110000;
    response = await fetch(API_BASE + path, { ...options, signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(timeout)]) : AbortSignal.timeout(timeout) });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    throw new Error(error.name === 'TimeoutError' ? 'Request timed out. Please retry.' : 'Cannot reach the API. Check the backend and network configuration.');
  }
  const data = await response.json().catch(() => { throw new Error('The API returned invalid JSON.'); });
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status}). Check the inputs.`);
  return data;
}
function busy(ids, value) { if (ids.includes('optimize-button')) $('cancel-route-button').hidden = !value; for (const id of ids) { $(id).disabled = value; $(id).setAttribute('aria-busy', String(value)); } }
function removeMarker(marker) { marker?.remove(); }
function cancelSearch(kind) {
  lanes[kind].cancel(); $(`${kind}-search-results`).replaceChildren();
  $(`${kind}-search-form`).querySelector('button').disabled = !ready;
}
function clearRoute(message = 'Displayed route cleared. Trip locations retained.') {
  lanes.route.cancel(); busy(routeButtons, false);
  if (ready) for (const id of ['direct-route', 'optimized-route']) map.getSource(id)?.setData(EMPTY);
  removeMarker(recommendedMarker); recommendedMarker = null;
  $('directions-section').hidden = true; $('facility-details').hidden = true; $('route-comparison').replaceChildren(); $('route-warnings').textContent = ''; status(message);
}
function cancelSelection() {
  selection = null; $('cancel-selection-button').hidden = true;
  if (map) map.getCanvas().style.cursor = '';
}
function togglePanel(collapsed) {
  $('bin-panel').classList.toggle('collapsed', collapsed);
  $('map-status').hidden = !collapsed;
  $('panel-toggle').setAttribute('aria-expanded', String(!collapsed)); $('panel-toggle').textContent = collapsed ? 'Show controls' : 'Hide controls';
}
function selectOnMap(kind) {
  if (!ready) return status('Wait for the map to load, then try again.');
  cancelSelection(); selection = kind; if (kind === 'start') gpsGeneration++;
  cancelSearch(kind); $('cancel-selection-button').hidden = false; map.getCanvas().style.cursor = 'crosshair';
  if (window.innerWidth <= 600) togglePanel(true);
  status(`Click the map to choose your ${kind}. Press Escape to cancel.`);
}
function setLocation(kind, coordinates, name) {
  if (!validCoordinate(coordinates)) return status('Invalid location coordinates.');
  clearRoute(); cancelSelection(); cancelSearch(kind);
  const location = { coordinates, name: name || `${coordinates[1].toFixed(5)}, ${coordinates[0].toFixed(5)}` };
  if (kind === 'start') {
    gpsGeneration++; start = location; removeMarker(startMarker);
    startMarker = new mapboxgl.Marker({ color: '#3987ff' }).setLngLat(coordinates).setPopup(new mapboxgl.Popup().setText(`Start: ${location.name}`)).addTo(map);
    $('start-hint').textContent = `Start: ${location.name}`; cancelSearch('destination'); $('facility-details').hidden = true; fetchFacilities();
    status('Starting location set. Choose a nearby facility or plan a walk.');
  } else {
    $('route-planner').open = true; destination = location; removeMarker(destinationMarker);
    destinationMarker = new mapboxgl.Marker({ color: '#e34c4c' }).setLngLat(coordinates).setPopup(new mapboxgl.Popup().setText(`Destination: ${location.name}`)).addTo(map);
    $('destination-hint').textContent = `Destination: ${location.name}`; status('Destination selected. Get a direct route or add a facility stop.');
  }
  map.flyTo({ center: coordinates, zoom: 15, animate: !reducedMotion }); if (window.innerWidth <= 600) togglePanel(false);
}
function clearFacilities() {
  lanes.facilities.cancel(); facilityState = 'idle'; facilityError = ''; facilityWarnings = []; categoryStates = {}; facilityPartial = false; $('facility-warnings').replaceChildren(); facilities = []; facilityMarkers.forEach(removeMarker); facilityMarkers = [];
  $('facility-source-details').hidden = true; $('facility-source-details').open = false; $('facility-source-info').textContent = '';
  $('bin-results').replaceChildren(); $('results-count').textContent = '0 found'; $('results-subtitle').textContent = start ? 'Waiting for facilities' : 'Choose a start';
}
async function fetchFacilities() {
  clearFacilities(); if (!start) return;
  const ticket = lanes.facilities.begin(); facilityState = 'loading'; $('bin-results').textContent = 'Searching OpenStreetMap…'; $('results-subtitle').textContent = 'Loading facilities';
  const [longitude, latitude] = start.coordinates;
  try {
    const data = await api(`/resources?${new URLSearchParams({ longitude, latitude, radius: $('distance-filter').value, include_metadata: true })}`, { signal: ticket.signal });
    if (!ticket.current()) return;
    const loaded = Array.isArray(data) ? data : data.facilities;
    if (!Array.isArray(loaded) || loaded.some(f => !validCoordinate([f.longitude, f.latitude]) || typeof f.name !== 'string' || !colors[f.type])) throw new Error('Invalid facility response.');
    if (!Array.isArray(data) && (!Array.isArray(data.warnings) || data.warnings.some(w => typeof w !== 'string') || !data.categories || typeof data.categories !== 'object')) throw new Error('Invalid facility metadata.');
    facilityPartial = !Array.isArray(data) && data.partial === true; facilityWarnings = Array.isArray(data) ? [] : data.warnings; categoryStates = Array.isArray(data) ? {} : data.categories;
    facilities = loaded; facilityState = 'ready'; renderFacilities(); return true;
  } catch (error) {
    if (ticket.current() && error.name !== 'AbortError') {
      facilityState = 'error'; facilityError = error.message; renderFacilities();
    }
  }
}
function facilityDescription(f) {
  return [f.type, ...(f.source?.kind === 'community' ? ['Community submission; location and public access are user reported.'] : []), ...(f.source?.kind === 'local_snapshot' ? [`Saved OSM data: ${f.source.name}, retrieved ${f.source.retrieved_at}. © OpenStreetMap contributors, ODbL.`] : []), ...Object.entries(f.metadata || {}).map(([k, v]) => `${k.replaceAll('_', ' ')}: ${v}`), 'Access and opening hours are not verified.',
    ...(f.coordinate_source === 'area_center' ? ['Area center; entrance may differ.'] : [])].join(' · ');
}
function walkToFacility(f) {
  if (!ready || !start) return status('Choose a starting location before requesting walking directions.');
  setLocation('destination', [f.longitude, f.latitude], facilityName(f));
  return requestRoute(false);
}
function showFacility(f) {
  const container = $('facility-details'); container.replaceChildren(); container.hidden = false;
  const heading = document.createElement('h3'); heading.textContent = facilityName(f);
  const details = document.createElement('p'); details.className = 'location-note'; details.textContent = facilityDescription(f);
  const coordinates = document.createElement('p'); coordinates.className = 'location-note'; coordinates.textContent = `${f.latitude.toFixed(5)}, ${f.longitude.toFixed(5)}`;
  const button = document.createElement('button'); button.type = 'button'; button.className = 'primary-button'; button.textContent = 'Walk to this facility';
  button.onclick = () => walkToFacility(f);
  container.append(heading, details, coordinates, button);
  appendCommunityReport(container, f, { apiBase: API_BASE, refreshed: fetchFacilities,
    removed: () => {
      if (destination && distance(destination.coordinates, [f.longitude, f.latitude]) < 1) {
        destination = null; removeMarker(destinationMarker); destinationMarker = null;
        $('destination-hint').textContent = 'Select a destination on the map to optimize your walk.';
      }
      clearRoute('Community facility removed after reaching the report threshold.');
    } });
  if (window.innerWidth <= 600) togglePanel(false);
}
function facilityPopup(f) {
  const node = document.createElement('div'), title = document.createElement('strong'), body = document.createElement('p'), button = document.createElement('button');
  title.textContent = facilityName(f); body.textContent = facilityDescription(f); button.textContent = 'View facility details'; button.onclick = () => showFacility(f);
  const directions = document.createElement('button'); directions.type = 'button'; directions.textContent = 'Get walking directions'; directions.onclick = () => walkToFacility(f);
  node.append(title, body, button, directions); return new mapboxgl.Popup().setDOMContent(node);
}
function renderFacilities() {
  const sources = [...new Map([...facilities.map(f => f.source), ...Object.values(categoryStates).map(s => s.source)].filter(s => s?.kind === 'local_snapshot').map(s => [s.name, s])).values()];
  const notes = facilityWarnings.filter(w => !w.startsWith('Showing saved OpenStreetMap facilities'));
  $('facility-warnings').textContent = [...sources.map(s => `Showing saved OpenStreetMap facilities for ${s.name}.`), ...notes].join(' ');
  $('facility-source-details').hidden = sources.length === 0;
  $('facility-source-info').textContent = sources.map(s => `Saved, not live. Retrieved ${s.retrieved_at}. OSM data date: ${s.data_timestamp || 'unknown'}. Coverage: ${s.coverage?.type === 'circle' ? `${(s.coverage.radius_meters / 1609.344).toFixed(1)} miles around approximate center ${s.coverage.center.latitude}, ${s.coverage.center.longitude}` : `bounds ${(s.bbox || []).join(', ')}`}. © OpenStreetMap contributors, ODbL.`).join(' ') + (facilityPartial ? ' Search coverage is incomplete; see warnings above.' : '');
  if (facilityState !== 'ready') {
    $('bin-results').textContent = facilityState === 'loading' ? 'Searching OpenStreetMap…' : facilityState === 'error' ? `Facility search failed: ${facilityError}` : 'Choose a starting location.';
    if (facilityState === 'error') {
      $('results-subtitle').textContent = 'Search failed';
      const retry = document.createElement('button'); retry.textContent = 'Retry facility search'; retry.onclick = fetchFacilities; $('bin-results').append(retry);
    }
    return;
  }
  facilityMarkers.forEach(removeMarker); facilityMarkers = [];
  const visible = filterFacilities(facilities, $('facility-filter').value, $('bin-search').value, start?.coordinates);
  const container = $('bin-results'); container.replaceChildren(); $('results-count').textContent = `${visible.length} found`; $('results-subtitle').textContent = 'Sorted by straight-line distance';
  if (!visible.length) {
    const selected = $('facility-filter').value;
    container.textContent = categoryStates[selected]?.status === 'failed' ? `${selected} could not be loaded. Results are unavailable, not empty.` : facilityPartial ? 'No matches in the successfully searched areas. See incomplete-search warnings above.' : start ? 'No matching mapped facilities. Try a larger radius.' : 'Choose a starting location.';
  }
  for (const f of visible) {
    const coordinates = [f.longitude, f.latitude], card = document.createElement('article'); card.className = 'bin-card';
    const button = document.createElement('button'); button.type = 'button'; button.className = 'facility-card-details'; button.setAttribute('aria-label', `View details for ${facilityName(f)}`);
    const title = document.createElement('strong'); title.textContent = facilityName(f);
    const description = document.createElement('span'); description.textContent = `${f.type} · ${formatDistance(distance(start.coordinates, coordinates))} straight-line${f.source?.kind === 'local_snapshot' ? ' · Saved OSM data' : f.source?.kind === 'community' ? ' · Community submission' : ''}`;
    button.append(title, description); button.onclick = () => showFacility(f);
    const directions = document.createElement('button'); directions.type = 'button'; directions.className = 'facility-card-directions'; directions.textContent = 'Get walking directions'; directions.setAttribute('aria-label', `Get walking directions to ${facilityName(f)}`);
    directions.onclick = () => walkToFacility(f); card.append(button, directions); container.append(card);
    const marker = new mapboxgl.Marker({ color: colors[f.type] }).setLngLat(coordinates).setPopup(facilityPopup(f)).addTo(map);
    marker.getElement().addEventListener('click', event => { event.stopPropagation(); showFacility(f); }); facilityMarkers.push(marker);
  }
}
function fitRoutes(routes) {
  const bounds = new mapboxgl.LngLatBounds(); for (const route of routes.filter(Boolean)) route.geometry.coordinates.forEach(c => bounds.extend(c));
  const panel = $('bin-panel').getBoundingClientRect(), mobile = window.innerWidth <= 600; if (mobile) togglePanel(true);
  map.fitBounds(bounds, { padding: { top: mobile ? 65 : 45, bottom: 55, right: 45, left: mobile || $('bin-panel').classList.contains('collapsed') ? 45 : Math.ceil(panel.right + 25) }, maxZoom: 17, animate: !reducedMotion });
}
function draw(id, route) { map.getSource(id).setData({ type: 'Feature', properties: {}, geometry: route.geometry }); }
function displayRoute(direct, optimized, result = {}) {
  validateRoute(direct); if (optimized) validateRoute(optimized);
  draw('direct-route', direct); if (optimized) draw('optimized-route', optimized);
  const route = optimized || direct; $('directions-section').hidden = false;
  $('directions-destination').textContent = result.facility ? `Via ${facilityName(result.facility)}` : destination?.name || 'Walking route';
  $('trip-summary').textContent = `${start.name} → ${destination?.name || 'Selected facility'}`;
  $('route-duration').textContent = formatDuration(route.duration); $('route-distance').textContent = formatDistance(route.distance);
  $('detour-info').textContent = optimized ? `Extra walking: ${formatDuration(result.detour_seconds)} · ${formatDistance(optimized.distance - direct.distance)} additional distance. Meets detour limit.` : 'Direct walking route.';
  const comparison = $('route-comparison'); comparison.replaceChildren();
  if (result.summary) {
    const table = document.createElement('table');
    for (const row of [['Route', 'Walking time', 'Distance'], ['Direct (blue)', formatDuration(direct.duration), formatDistance(direct.distance)], ['Via facility (green)', optimized ? formatDuration(optimized.duration) : 'None found', optimized ? formatDistance(optimized.distance) : '—']]) {
      const tr = document.createElement('tr'); row.forEach(value => { const cell = document.createElement(table.childElementCount ? 'td' : 'th'); cell.textContent = value; tr.append(cell); }); table.append(tr);
    }
    comparison.append(table); const note = document.createElement('p'); note.textContent = `${result.candidates_evaluated} routes evaluated of ${result.candidates_found} candidates found.`; comparison.append(note);
  }
  $('route-warnings').textContent = [result.message, ...(result.warnings || [])].filter(Boolean).join(' ');
  if (result.facility) {
    recommendedMarker = new mapboxgl.Marker({ color: '#ff9f1c' }).setLngLat([result.facility.longitude, result.facility.latitude]).setPopup(facilityPopup(result.facility)).addTo(map);
    showFacility(result.facility);
  }
  fitRoutes([direct, optimized]);
}
async function requestRoute(optimize) {
  if (!ready || !start || !destination) return status('Choose a start and destination first.');
  const raw = $('detour-filter').value, maxDetour = Number(raw);
  if (optimize && (!raw.trim() || !Number.isFinite(maxDetour) || maxDetour < 0 || maxDetour > 30)) return status('Maximum detour must be between 0 and 30 minutes.');
  clearRoute(); const ticket = lanes.route.begin(); busy(routeButtons, true);
  const [start_lon, start_lat] = start.coordinates, [end_lon, end_lat] = destination.coordinates, coordinates = { start_lat, start_lon, end_lat, end_lon };
  status(optimize ? 'Checking walking routes through mapped facilities…' : 'Calculating direct walking route…');
  try {
    const result = optimize ? await api('/optimized-route', { method: 'POST', signal: ticket.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...coordinates, facility_type: $('optimizer-facility').value, max_detour_minutes: maxDetour }) }) : await api(`/route?${new URLSearchParams(coordinates)}`, { signal: ticket.signal });
    if (!ticket.current()) return;
    if (optimize && (Boolean(result.optimized_route) !== Boolean(result.facility) || !result.direct_route || !Array.isArray(result.warnings) || !Number.isFinite(result.candidates_evaluated) || (result.optimized_route && (!result.facility || !validCoordinate([result.facility.longitude, result.facility.latitude]) || !Number.isFinite(result.detour_seconds) || result.detour_seconds < 0 || result.detour_seconds > maxDetour * 60)))) throw new Error('Invalid optimization response.');
    displayRoute(optimize ? result.direct_route : result, optimize ? result.optimized_route : null, optimize ? result : {}); status(optimize ? result.message : 'Direct walking route calculated.');
  } catch (error) { if (ticket.current() && error.name !== 'AbortError') status(error.message); }
  finally { if (ticket.current()) busy(routeButtons, false); }
}
async function nearestBin() {
  if (!start) return status('Choose a starting location first.');
  clearRoute(); const ticket = lanes.route.begin(); busy(routeButtons, true); status('Comparing walking times to nearby trash bins…');
  const [longitude, latitude] = start.coordinates;
  try {
    const result = await api(`/nearest-bin?${new URLSearchParams({ longitude, latitude, radius: $('distance-filter').value })}`, { signal: ticket.signal });
    if (!ticket.current()) return;
    if (!Array.isArray(result.warnings) || !Object.hasOwn(result, 'facility') || (result.facility && !result.route)) throw new Error('Invalid nearest-bin response.');
    if (!result.facility) { status('No reachable mapped trash bin found in this radius.'); return; }
    validateRoute(result.route); if (!validCoordinate([result.facility.longitude, result.facility.latitude])) throw new Error('Invalid bin location.');
    setLocation('destination', [result.facility.longitude, result.facility.latitude], facilityName(result.facility));
    displayRoute(result.route, null, { warnings: result.warnings }); showFacility(result.facility); status('Bin selected by walking time among checked candidates.');
  } catch (error) { if (ticket.current() && error.name !== 'AbortError') status(error.message); }
  finally { if (ticket.current()) busy(routeButtons, false); }
}
async function searchPlaces(kind, event) {
  event.preventDefault(); const q = $(`${kind}-search`).value.trim(); if (q.length < 2) return status('Enter at least two characters for an address or place.');
  const ticket = lanes[kind].begin(); if (kind === 'start') gpsGeneration++;
  const button = $(`${kind}-search-form`).querySelector('button'); button.disabled = true;
  const container = $(`${kind}-search-results`); container.textContent = 'Searching places…';
  try {
    const params = new URLSearchParams({ q }); if (start) { params.set('longitude', start.coordinates[0]); params.set('latitude', start.coordinates[1]); }
    const data = await api(`/search?${params}`, { signal: ticket.signal }); if (!ticket.current()) return;
    if (!Array.isArray(data.results) || data.results.some(r => !validCoordinate(r.coordinates) || typeof r.name !== 'string')) throw new Error('Invalid place search results.');
    container.replaceChildren(); if (!data.results.length) container.textContent = 'No places found. Try a fuller address or pick on map.';
    for (const place of data.results) { const result = document.createElement('button'); result.type = 'button'; result.className = 'bin-card'; result.textContent = place.name; result.onclick = () => setLocation(kind, place.coordinates, place.name); container.append(result); }
    const attribution = document.createElement('small'); attribution.textContent = data.attribution; container.append(attribution);
  } catch (error) { if (ticket.current() && error.name !== 'AbortError') container.textContent = error.message; }
  finally { if (ticket.current()) button.disabled = false; }
}
function requestLocation() {
  if (!ready) return status('Wait for the map to load.');
  if (!navigator.geolocation) return status('GPS is unavailable. Pick a start on the map or search an address.');
  const generation = ++gpsGeneration; status('Finding your GPS location… You can also choose a start manually.');
  navigator.geolocation.getCurrentPosition(position => {
    if (generation === gpsGeneration) setLocation('start', [position.coords.longitude, position.coords.latitude], 'Current GPS location');
  }, error => {
    if (generation !== gpsGeneration) return;
    const reason = { 1: 'Location permission denied.', 2: 'GPS location unavailable.', 3: 'GPS timed out.' }[error.code] || 'GPS failed.';
    status(`${reason} Pick a start on the map or search an address.`);
  }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
}
for (const kind of ['start', 'destination']) { $(`${kind}-search-form`).onsubmit = event => searchPlaces(kind, event); $(`${kind}-search`).oninput = () => cancelSearch(kind); }
$('choose-start-button').onclick = () => selectOnMap('start'); $('choose-destination-button').onclick = () => selectOnMap('destination');
$('cancel-selection-button').onclick = () => { cancelSelection(); status('Map selection cancelled.'); };
document.addEventListener('keydown', event => { if (event.key === 'Escape') { cancelSelection(); status('Map selection cancelled.'); } });
$('panel-toggle').onclick = () => togglePanel(!$('bin-panel').classList.contains('collapsed'));
$('my-location-button').onclick = requestLocation; $('direct-route-button').onclick = () => requestRoute(false); $('optimize-button').onclick = () => requestRoute(true); $('nearest-button').onclick = nearestBin;
$('clear-route-button').onclick = () => clearRoute(); $('cancel-route-button').onclick = () => clearRoute('Route request cancelled.');
$('clear-destination-button').onclick = () => {
  clearRoute('Destination cleared.'); cancelSelection(); cancelSearch('destination'); destination = null; removeMarker(destinationMarker); destinationMarker = null;
  $('destination-search').value = ''; $('destination-hint').textContent = 'Choose a destination on the map or search an address.';
};
$('reset-trip-button').onclick = () => {
  $('clear-destination-button').click(); gpsGeneration++; cancelSearch('start'); start = null; removeMarker(startMarker); startMarker = null; clearFacilities();
  $('start-search').value = ''; $('start-hint').textContent = 'Choose a starting location.'; $('facility-details').hidden = true; status('Trip reset. Choose a new start.');
};
$('search-form').onsubmit = event => { event.preventDefault(); renderFacilities(); }; $('bin-search').oninput = renderFacilities; $('facility-filter').onchange = renderFacilities;
$('distance-filter').onchange = () => { clearRoute('Search radius changed.'); $('facility-details').hidden = true; fetchFacilities(); };
$('optimizer-facility').onchange = () => clearRoute('Requested stop changed. Calculate a new route.'); $('detour-filter').oninput = () => clearRoute('Detour limit changed. Calculate a new route.');
async function initializeMap() {
  const token = import.meta.env.VITE_MAPBOX_TOKEN;
  if (!token?.startsWith('pk.')) return status('Set VITE_MAPBOX_TOKEN to a public Mapbox token in frontend/.env, then restart Vite.');
  try {
    mapboxgl = (await import('mapbox-gl')).default; mapboxgl.accessToken = token;
    map = new mapboxgl.Map({ container: 'map', style: 'mapbox://styles/mapbox/standard', center: [-74.45, 40.50], zoom: 12 });
    map.addControl(new mapboxgl.NavigationControl(), 'top-right'); map.addControl(new mapboxgl.FullscreenControl(), 'top-right');
    map.on('load', () => {
      for (const [id, color, width] of [['direct-route', '#247ce3', 5], ['optimized-route', '#216b49', 6]]) {
        map.addSource(id, { type: 'geojson', data: EMPTY });
        map.addLayer({ id: `${id}-outline`, type: 'line', source: id, slot: 'middle', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#ffffff', 'line-width': width + 4 } });
        map.addLayer({ id: `${id}-line`, type: 'line', source: id, slot: 'middle', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': color, 'line-width': width } });
      }
      ready = true; busy(['choose-start-button', 'choose-destination-button', 'my-location-button'], false);
      for (const kind of ['start', 'destination']) $(`${kind}-search-form`).querySelector('button').disabled = false;
      status('Map ready. Use GPS, search an address, or choose a start on the map.'); requestLocation();
    });
    map.on('click', event => { if (selection) setLocation(selection, [event.lngLat.lng, event.lngLat.lat]); });
    map.on('error', () => status('Map tiles could not load. Check the public token, its URL restrictions, and network connection.'));
  } catch { status('Map could not initialize. Check WebGL support, your public token, and network connection.'); }
}
busy(['choose-start-button', 'choose-destination-button', 'my-location-button'], true);
for (const kind of ['start', 'destination']) $(`${kind}-search-form`).querySelector('button').disabled = true;
initializeMap();

const selectView = initializeTabs({ resizeMap: () => map?.resize?.(), suspendNavigation: cancelSelection });
initializeAssistant({ apiBase: API_BASE, selectView, navigate: async (type, item) => {
  $('facility-filter').value = type; $('bin-search').value = ''; $('facility-details').hidden = true; togglePanel(false);
  if (!start) { renderFacilities(); status('Choose a starting location to find disposal facilities.'); return; }
  const selectedStart = start;
  // Search the local demo radius once, retaining the trip and existing route layers.
  if (type === 'Recycling Location') {
    $('distance-filter').value = '16093';
    status('Finding the closest mapped recycling location within 10 miles…');
    const loaded = await fetchFacilities();
    if (!loaded || start !== selectedStart || $('facility-filter').value !== type) return;
  } else {
    if (facilityState !== 'ready' && !await fetchFacilities()) return;
    if (start !== selectedStart || $('facility-filter').value !== type) return;
    renderFacilities();
  }
  const nearest = filterFacilities(facilities, type, '', start.coordinates)
    .find(f => !['private', 'no'].includes((f.metadata?.access || '').toLowerCase()));
  if (!nearest) {
    status(facilityPartial ? 'No matching location in the covered search area. Coverage is incomplete; see facility warnings.' : 'No matching mapped location found in this search radius.');
    return;
  }
  showFacility(nearest);
  if (type === 'Recycling Location') {
    const acceptance = document.createElement('p'); acceptance.className = 'location-note';
    acceptance.textContent = `Acceptance of ${item.name} is unverified. Contact the operator before bringing it.`;
    $('facility-details').append(acceptance);
  }
  map?.flyTo({ center: [nearest.longitude, nearest.latitude], zoom: 15, animate: !reducedMotion });
  const label = type === 'Trash Bin' ? 'trash bin' : 'recycling location';
  status(`Closest mapped ${label} by straight-line distance: ${facilityName(nearest)}. ${type === 'Recycling Location' ? `Acceptance of ${item.name} is unverified; contact the operator before bringing it.` : 'Check mapped access.'}${facilityPartial ? ' Search coverage is incomplete.' : ''}`);
} });


initializeCommunity({ apiBase: API_BASE, published: async (facility) => {
  selectView('navigation');
  if (ready && !start) setLocation('start', [facility.longitude, facility.latitude], 'New community facility');
  await fetchFacilities();
  if (ready) {
    // An address can be outside the current search radius: still show the submitted point.
    if (!facilities.some(f => f.id === facility.id)) {
      const marker = new mapboxgl.Marker({ color: colors[facility.type] }).setLngLat([facility.longitude, facility.latitude]).setPopup(facilityPopup(facility)).addTo(map);
      marker.getElement().addEventListener('click', event => { event.stopPropagation(); showFacility(facility); }); facilityMarkers.push(marker);
    }
    showFacility(facility); map.flyTo({ center: [facility.longitude, facility.latitude], zoom: 16, animate: !reducedMotion });
  }
} });
