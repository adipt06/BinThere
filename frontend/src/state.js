export class RequestLane {
  constructor() { this.generation = 0; this.controller = null; }
  cancel() { this.generation++; this.controller?.abort(); this.controller = null; }
  begin() {
    this.cancel(); this.controller = new AbortController();
    const generation = this.generation;
    return { signal: this.controller.signal, current: () => generation === this.generation };
  }
}
export function validCoordinate(p) {
  return Array.isArray(p) && p.length === 2 && p.every(Number.isFinite) && Math.abs(p[0]) <= 180 && Math.abs(p[1]) <= 90;
}
export function validateRoute(route) {
  if (!route || !Number.isFinite(route.distance) || route.distance < 0 || !Number.isFinite(route.duration) || route.duration < 0 ||
      route.geometry?.type !== 'LineString' || !Array.isArray(route.geometry.coordinates) || route.geometry.coordinates.length < 2 || !route.geometry.coordinates.every(validCoordinate)) throw new Error('The mapping service returned an invalid route.');
  return route;
}
export function distance(a, b) {
  const rad = n => n * Math.PI / 180;
  const h = Math.sin(rad(b[1] - a[1]) / 2) ** 2 + Math.cos(rad(a[1])) * Math.cos(rad(b[1])) * Math.sin(rad(b[0] - a[0]) / 2) ** 2;
  return 12742000 * Math.asin(Math.sqrt(Math.min(1, h)));
}
export function filterFacilities(facilities, type, search, start) {
  const text = search.trim().toLowerCase();
  return facilities.filter(f => (type === 'All' || f.type === type) && `${f.name} ${f.type}`.toLowerCase().includes(text))
    .sort((a, b) => start ? distance(start, [a.longitude, a.latitude]) - distance(start, [b.longitude, b.latitude]) : 0);
}
