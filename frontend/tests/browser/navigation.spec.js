import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const mockMap = fs.readFileSync(new URL('./mapbox.mock.js', import.meta.url), 'utf8');
const route = {distance:1000,duration:600,geometry:{type:'LineString',coordinates:[[-74,40.5],[-74.01,40.51]]}};
const facility = {id:'node/1',name:'Campus Bin',type:'Trash Bin',latitude:40.505,longitude:-74.005,metadata:{wheelchair:'yes',opening_hours:'24/7'},coordinate_source:'node'};
const rest = {...facility,id:'node/2',name:'Campus Restroom',type:'Restroom'};
const optimized = {direct_route:route,optimized_route:{...route,duration:660,distance:1100},facility,detour_seconds:60,candidates_evaluated:2,candidates_found:2,summary:{},warnings:['Access unverified.'],message:'Route found among evaluated facilities'};
async function setup(page, gps = 'denied') {
  await page.route('**/fonts.googleapis.com/**', r => r.abort());
  await page.route('**/node_modules/.vite/deps/mapbox-gl.js*', r => r.fulfill({contentType:'application/javascript',body:mockMap}));
  await page.addInitScript(mode => {
    Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(success,error){
      if(mode==='allowed') success({coords:{longitude:-74,latitude:40.5}});
      else if(mode==='delayed') window.__gpsSuccess=success;
      else error({code:1});
    }}});
  },gps);
  await page.route('**/api/**', async r => {
    const url = new URL(r.request().url());
    let data;
    if(url.pathname.endsWith('/resources')) data=[facility,rest];
    else if(url.pathname.endsWith('/optimized-route')) data=optimized;
    else if(url.pathname.endsWith('/nearest-bin')) data={facility,route,warnings:['Among checked bins.']};
    else if(url.pathname.endsWith('/search')) data={results:[{name:url.searchParams.get('q')+' result',coordinates:[-74,40.5]}],attribution:'© Mapbox'};
    else data=route;
    await r.fulfill({json:data});
  });
  await page.goto('/');
  await expect(page.locator('#choose-start-button')).toBeEnabled();
}
async function choose(page, kind) {
  await page.locator(`#choose-${kind}-button`).click();
  await page.locator('#mock-map-canvas').click({position:{x:750,y:200}});
}
async function trip(page) { await setup(page,'allowed'); await choose(page,'destination'); }
async function markerCount(page,color) { return page.evaluate(c => window.__map.markers.filter(m=>m.color===c).length,color); }

test('GPS denied: manual start and facility discovery remain usable', async ({page}) => {
  await setup(page); await expect(page.locator('#bin-status')).toContainText('permission denied');
  await choose(page,'start'); await expect(page.locator('#start-hint')).toContainText('40.51000'); await expect(page.locator('#results-count')).toHaveText('2 found');
});
test('GPS allowed sets a distinct start marker', async ({page}) => {
  await setup(page,'allowed'); await expect(page.locator('#start-hint')).toContainText('Current GPS'); expect(await markerCount(page,'#3987ff')).toBe(1);
});
test('late GPS cannot override a manually selected start', async ({page}) => {
  await setup(page,'delayed'); await choose(page,'start'); await page.evaluate(()=>window.__gpsSuccess({coords:{longitude:10,latitude:10}}));
  await expect(page.locator('#start-hint')).toContainText('40.51000');
});
test('start and destination address searches select places', async ({page}) => {
  await setup(page); for(const kind of ['start','destination']) {
    await page.locator(`#${kind}-search`).fill('Rutgers'); await page.locator(`#${kind}-search-form button`).click();
    await page.locator(`#${kind}-search-results button`).click(); await expect(page.locator(`#${kind}-hint`)).toContainText('Rutgers result');
  }
});
test('map selection can be cancelled', async ({page}) => {
  await setup(page); await page.locator('#choose-start-button').click(); await page.keyboard.press('Escape');
  await page.locator('#mock-map-canvas').click({position:{x:750,y:200}}); expect(await markerCount(page,'#3987ff')).toBe(0);
});
test('category and name filters update cards and markers', async ({page}) => {
  await setup(page,'allowed'); await expect(page.locator('#results-count')).toHaveText('2 found');
  await page.locator('#facility-filter').selectOption('Restroom'); await expect(page.locator('#results-count')).toHaveText('1 found');
  await page.locator('#bin-search').fill('missing'); await expect(page.locator('#results-count')).toHaveText('0 found');
  expect(await markerCount(page,'#8054c8')).toBe(0);
});
test('facility details expose metadata and direct navigation', async ({page}) => {
  await setup(page,'allowed'); await page.locator('#bin-results button').first().click(); await expect(page.locator('#facility-details')).toContainText('wheelchair: yes');
  await page.getByRole('button',{name:'Walk to this facility',exact:true}).click(); await expect(page.locator('#directions-section')).toBeVisible(); await expect(page.locator('#destination-hint')).toContainText('Campus Bin');
});
test('direct route draws GeoJSON and summary', async ({page}) => {
  await trip(page); await page.locator('#direct-route-button').click(); await expect(page.locator('#route-duration')).toHaveText('10.0 min');
  expect(await page.evaluate(()=>window.__map.sources['direct-route'].data.geometry.type)).toBe('LineString');
});
test('optimized route compares routes and clears recommended marker', async ({page}) => {
  await trip(page); await page.locator('#optimize-button').click(); await expect(page.locator('#route-comparison')).toContainText('11.0 min');
  expect(await markerCount(page,'#ff9f1c')).toBe(1); await page.locator('#direct-route-button').click(); await expect(page.locator('#detour-info')).toHaveText('Direct walking route.'); expect(await markerCount(page,'#ff9f1c')).toBe(0);
});
test('zero detour and no-facility fallback render correctly', async ({page}) => {
  await trip(page); await page.route('**/api/optimized-route',r=>r.fulfill({json:{...optimized,optimized_route:route,detour_seconds:0}}));
  await page.locator('#optimize-button').click(); await expect(page.locator('#detour-info')).toContainText('0 sec');
  await page.route('**/api/optimized-route',r=>r.fulfill({json:{...optimized,optimized_route:null,facility:null,detour_seconds:null,message:'No qualifying facility found'}}));
  await page.locator('#optimize-button').click(); await expect(page.locator('#route-comparison')).toContainText('None found'); expect(await markerCount(page,'#ff9f1c')).toBe(0);
});
test('destination change invalidates in-flight route response', async ({page}) => {
  await trip(page); let release; const gate = new Promise(resolve=>release=resolve);
  await page.route('**/api/route?*',async r=>{await gate; await r.fulfill({json:route}).catch(()=>{});});
  await page.locator('#direct-route-button').click(); await choose(page,'destination'); release();
  await expect(page.locator('#directions-section')).toBeHidden(); await expect(page.locator('#direct-route-button')).toBeEnabled();
});
test('radius change ignores old facility responses', async ({page}) => {
  await setup(page,'allowed'); await expect(page.locator('#results-count')).toHaveText('2 found');
  let release; const gate = new Promise(resolve=>release=resolve);
  await page.route('**/api/resources?*',async r=> { if(new URL(r.request().url()).searchParams.get('radius')==='500'){await gate;await r.fulfill({json:[facility]}).catch(()=>{});} else await r.fulfill({json:[rest]}); });
  await page.locator('#distance-filter').selectOption('500'); await page.locator('#distance-filter').selectOption('2000');
  await expect(page.locator('#bin-results')).toContainText('Campus Restroom'); release(); await expect(page.locator('#bin-results')).not.toContainText('Campus Bin');
});
test('clear route retains locations; reset removes trip markers', async ({page}) => {
  await trip(page); await page.locator('#optimize-button').click(); await expect(page.locator('#directions-section')).toBeVisible();
  await page.locator('#clear-route-button').click(); expect(await markerCount(page,'#e34c4c')).toBe(1); expect(await markerCount(page,'#ff9f1c')).toBe(0);
  await page.locator('#reset-trip-button').click(); expect(await page.evaluate(()=>window.__map.markers.length)).toBe(0); await expect(page.locator('#directions-section')).toBeHidden();
});
test('failed routing clears stale results and releases buttons', async ({page}) => {
  await trip(page); await page.route('**/api/route?*',r=>r.fulfill({status:504,json:{detail:'Mapbox timed out.'}}));
  await page.locator('#direct-route-button').click(); await expect(page.locator('#bin-status')).toContainText('timed out'); await expect(page.locator('#direct-route-button')).toBeEnabled(); await expect(page.locator('#directions-section')).toBeHidden();
});
test('invalid detour makes no optimization request', async ({page}) => {
  await trip(page); let calls=0; await page.route('**/api/optimized-route',r=>{calls++;return r.fulfill({json:optimized});});
  await page.locator('#detour-filter').fill('31'); await page.locator('#optimize-button').click(); await expect(page.locator('#bin-status')).toContainText('between 0 and 30'); expect(calls).toBe(0);
});
test('nearest bin uses returned walking route', async ({page}) => {
  await setup(page,'allowed'); await page.locator('#nearest-button').click(); await expect(page.locator('#destination-hint')).toContainText('Campus Bin'); await expect(page.locator('#route-duration')).toHaveText('10.0 min');
});
test('mobile panel collapses for map selection and route bounds', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await setup(page,'allowed');
  await page.locator('#choose-destination-button').click(); await expect(page.locator('#bin-panel')).toBeHidden();
  await page.locator('#mock-map-canvas').click({position:{x:200,y:200}}); await expect(page.locator('#bin-panel')).toBeVisible();
  await page.locator('#direct-route-button').click(); await expect(page.locator('#bin-panel')).toBeHidden();
  await page.locator('#panel-toggle').click(); await expect(page.locator('#directions-section')).toBeVisible();
});
test('real FastAPI proxy integration: discover, route, optimize and reset', async ({page}) => {
  await setup(page,'allowed');
  await page.unroute('**/api/**');
  // Force a new nearby search through Vite -> FastAPI -> mocked upstream boundaries.
  await page.locator('#distance-filter').selectOption('2000');
  await expect(page.locator('#bin-results')).toContainText('Integrated Campus Bin');
  await choose(page,'destination'); await page.locator('#direct-route-button').click();
  await expect(page.locator('#route-duration')).toHaveText('10.0 min');
  await page.locator('#optimize-button').click(); await expect(page.locator('#route-comparison')).toContainText('11.0 min');
  await expect(page.locator('#directions-destination')).toContainText('Integrated Campus Bin');
  expect(await markerCount(page,'#ff9f1c')).toBe(1);
  await page.locator('#reset-trip-button').click(); expect(await page.evaluate(()=>window.__map.markers.length)).toBe(0);
});
test('mobile map selection has a visible cancel control', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await setup(page,'allowed');
  await page.locator('#choose-destination-button').click(); await expect(page.locator('#cancel-selection-button')).toBeVisible();
  await page.locator('#cancel-selection-button').click(); await page.locator('#mock-map-canvas').click({position:{x:200,y:200}});
  expect(await markerCount(page,'#e34c4c')).toBe(0);
  await page.screenshot({path:'/tmp/reroute-mobile.png'});
});
test('cancel route request ignores its late response', async ({page}) => {
  await trip(page); let release; const gate = new Promise(resolve=>release=resolve);
  await page.route('**/api/route?*',async r=> { await gate; await r.fulfill({json:route}).catch(()=>{}); });
  await page.locator('#direct-route-button').click(); await page.locator('#cancel-route-button').click(); release();
  await expect(page.locator('#directions-section')).toBeHidden(); await expect(page.locator('#direct-route-button')).toBeEnabled();
});
test('facility service errors are visible and retry recovers', async ({page}) => {
  await setup(page,'allowed'); await page.route('**/api/resources?*',r=>r.fulfill({status:504,json:{detail:'Overpass timed out.'}}));
  await page.locator('#distance-filter').selectOption('2000'); await expect(page.locator('#bin-results')).toContainText('Overpass timed out');
  await page.route('**/api/resources?*',r=>r.fulfill({json:[facility]})); await page.getByRole('button',{name:'Retry facility search'}).click();
  await expect(page.locator('#results-count')).toHaveText('1 found');
});
test('empty and failed place searches preserve manual selection', async ({page}) => {
  await setup(page); await page.route('**/api/search?*',r=>r.fulfill({json:{results:[],attribution:'© Mapbox'}}));
  await page.locator('#destination-search').fill('Unknown place'); await page.locator('#destination-search-form button').click();
  await expect(page.locator('#destination-search-results')).toContainText('No places found');
  await page.route('**/api/search?*',r=>r.fulfill({status:503,json:{detail:'Search permission unavailable.'}}));
  await page.locator('#destination-search-form button').click(); await expect(page.locator('#destination-search-results')).toContainText('permission unavailable');
  await expect(page.locator('#choose-destination-button')).toBeEnabled();
});
test('malformed successful route response is rejected', async ({page}) => {
  await trip(page); await page.route('**/api/route?*',r=>r.fulfill({json:{distance:10,duration:20,geometry:{type:'Point',coordinates:[-74,40]}}}));
  await page.locator('#direct-route-button').click(); await expect(page.locator('#bin-status')).toContainText('invalid route');
  await expect(page.locator('#directions-section')).toBeHidden(); await expect(page.locator('#direct-route-button')).toBeEnabled();
});
test('clear destination preserves the start and prevents another route', async ({page}) => {
  await trip(page); await page.locator('#clear-destination-button').click(); expect(await markerCount(page,'#3987ff')).toBe(1); expect(await markerCount(page,'#e34c4c')).toBe(0);
  await page.locator('#direct-route-button').click(); await expect(page.locator('#bin-status')).toContainText('Choose a start and destination');
});
test('changing start invalidates in-flight optimization', async ({page}) => {
  await trip(page); let release; const gate = new Promise(resolve=>release=resolve);
  await page.route('**/api/optimized-route',async r=>{await gate; await r.fulfill({json:optimized}).catch(()=>{});});
  await page.locator('#optimize-button').click(); await choose(page,'start'); release();
  await expect(page.locator('#directions-section')).toBeHidden(); expect(await markerCount(page,'#ff9f1c')).toBe(0);
});
test('a busy route button prevents duplicate API calls', async ({page}) => {
  await trip(page); let release,calls=0; const gate = new Promise(resolve=>release=resolve);
  await page.route('**/api/route?*',async r=>{calls++;await gate; await r.fulfill({json:route}).catch(()=>{});});
  await page.locator('#direct-route-button').click(); await expect(page.locator('#direct-route-button')).toBeDisabled();
  await page.locator('#direct-route-button').evaluate(button=>button.click()); expect(calls).toBeLessThanOrEqual(1);
  release(); await expect(page.locator('#directions-section')).toBeVisible(); expect(calls).toBe(1);
});

test('partial facilities retain cards and markers with category warnings', async ({page}) => {
  await setup(page);
  await page.route('**/api/resources?*', r => r.fulfill({json:{facilities:[facility],partial:true,complete:false,warnings:['Restroom could not be loaded: upstream unavailable'],categories:{'Trash Bin':{status:'ok',count:1,searched_radius:200},Restroom:{status:'failed',count:null,searched_radius:200},'Recycling Location':{status:'ok',count:0,searched_radius:200}}}}));
  await choose(page,'start');
  await expect(page.locator('#results-count')).toHaveText('1 found');
  await expect(page.locator('#bin-results')).toContainText('Campus Bin');
  await expect(page.locator('#facility-warnings')).toContainText('Restroom could not be loaded');
  expect(await markerCount(page,'#216b49')).toBe(1);
  await page.locator('#facility-filter').selectOption('Restroom');
  await expect(page.locator('#bin-results')).toContainText('unavailable, not empty');
  await expect(page.locator('#facility-warnings')).toContainText('Restroom');
});

test('saved OSM facilities show source warnings, cards, markers and metadata', async ({page}) => {
  await setup(page);
  const source={kind:'local_snapshot',name:'Explicit browser fixture',retrieved_at:'2026-01-01T00:00:00Z'};
  await page.route('**/api/resources?*',r=>r.fulfill({json:{facilities:[{...facility,source},{...rest,source}],categories:{'Trash Bin':{status:'ok',count:1},Restroom:{status:'ok',count:1},'Recycling Location':{status:'ok',count:0}},warnings:['Using saved OpenStreetMap data; not live. © OpenStreetMap contributors, ODbL.','Saved facility data may be stale.'],complete:true,partial:false}}));
  await choose(page,'start');
  await expect(page.locator('#facility-warnings')).toContainText('saved OpenStreetMap');
  await expect(page.locator('#results-count')).toHaveText('2 found');
  await expect(page.locator('#bin-results')).toContainText('Saved OSM data');
  expect(await markerCount(page,'#216b49')).toBe(1);
  expect(await markerCount(page,'#8054c8')).toBe(1);
  await page.locator('#facility-filter').selectOption('Restroom');
  await page.locator('#bin-results button').click();
  await expect(page.locator('#facility-details')).toContainText('retrieved 2026-01-01');
  await page.locator('#reset-trip-button').click();
  await expect(page.locator('#facility-warnings')).toBeEmpty();
  expect(await markerCount(page,'#8054c8')).toBe(0);
});

test('saved circle coverage details are optional and partial results remain visible', async ({page}) => {
  await setup(page);
  const source={kind:'local_snapshot',name:'Piscataway / New Brunswick area',retrieved_at:'2026-10-11T05:29:10Z',data_timestamp:'2026-10-09T20:21:04Z',coverage:{type:'circle',center:{latitude:40.53399,longitude:-74.45793},radius_meters:16093.44}};
  await page.route('**/api/resources?*',r=>r.fulfill({json:{facilities:[{...facility,source}],categories:{'Trash Bin':{status:'partial',source}},warnings:['Showing saved OpenStreetMap facilities for Piscataway / New Brunswick area. Retrieved 2026-10-11; not live.','Search extends beyond saved geographic coverage; results cover only the overlapping area.'],complete:false,partial:true,coverage:'partial'}}));
  await choose(page,'start');
  await expect(page.locator('.bin-card')).toHaveCount(1);
  await expect(page.locator('#facility-warnings')).toContainText('Showing saved OpenStreetMap facilities for Piscataway');
  await expect(page.locator('#facility-warnings')).toContainText('beyond saved geographic coverage');
  await expect(page.locator('#facility-warnings')).not.toContainText('Retrieved');
  await page.locator('#facility-source-details summary').click();
  await expect(page.locator('#facility-source-info')).toContainText('10.0 miles around approximate center 40.53399, -74.45793');
  await expect(page.locator('#facility-source-info')).toContainText('Saved, not live. Retrieved 2026-10-11');
  await page.locator('#reset-trip-button').click();
  await expect(page.locator('#facility-source-details')).toBeHidden();
});

test('successfully empty saved search still displays source details', async ({page}) => {
  await setup(page);
  const source={kind:'local_snapshot',name:'Piscataway area',retrieved_at:'2026-10-11T00:00:00Z'};
  await page.route('**/api/resources?*',r=>r.fulfill({json:{facilities:[],categories:{Restroom:{status:'ok',source}},warnings:['Showing saved OpenStreetMap facilities for Piscataway area.'],complete:true,partial:false}}));
  await choose(page,'start');
  await expect(page.locator('#facility-warnings')).toContainText('Showing saved OpenStreetMap');
  await expect(page.locator('#facility-source-details')).toBeVisible();
  await expect(page.locator('.bin-card')).toHaveCount(0);
});
