// A deterministic map adapter: browser tests exercise our UI, not Mapbox/WebGL.
class Map {
  constructor() {
    this.handlers = {}; this.sources = {}; this.markers = [];
    window.__map = this;
    this.canvas = document.createElement('div'); this.canvas.id = 'mock-map-canvas';
    this.canvas.style.cssText = 'position:absolute;inset:0;background:#e9eee8';
    document.getElementById('map').append(this.canvas);
    this.canvas.addEventListener('click', () => this.emit('click', {lngLat:{lng:-74.01,lat:40.51}}));
    setTimeout(() => this.emit('load'), 20);
  }
  on(name, fn) { (this.handlers[name] ||= []).push(fn); }
  emit(name, event) { (this.handlers[name] || []).forEach(fn => fn(event)); }
  addControl() {}
  addSource(id, value) { this.sources[id] = {data:value.data,setData(data){this.data=data;}}; }
  getSource(id) { return this.sources[id]; }
  addLayer() {}
  getCanvas() { return this.canvas; }
  flyTo(options) { this.fly = options; }
  fitBounds(bounds, options) { this.fit = options; }
}
class Marker {
  constructor(options) { this.color = options.color; this.element = document.createElement('button'); this.element.className = 'mock-marker'; this.element.setAttribute('aria-label',`Map marker ${this.color}`); }
  setLngLat(coordinates) { this.coordinates = coordinates; return this; }
  setPopup(popup) { this.popup=popup; return this; }
  addTo(map) { this.map=map; map.markers.push(this); document.getElementById('map').append(this.element); return this; }
  getElement() { return this.element; }
  remove() { this.element.remove(); if(this.map) this.map.markers=this.map.markers.filter(m=>m!==this); }
}
class Popup { setText(value) { this.text=value; return this; } setDOMContent(value) { this.node=value; return this; } }
class LngLatBounds { extend() { return this; } }
export default {Map,Marker,Popup,LngLatBounds,NavigationControl:class {},FullscreenControl:class {}};
