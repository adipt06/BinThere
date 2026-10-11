import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const mockMap = fs.readFileSync(new URL('./mapbox.mock.js', import.meta.url), 'utf8');
const image = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aSp0AAAAASUVORK5CYII=', 'base64');
const facility = { id: 'community/test', name: 'Public recycling center', type: 'Recycling Location', latitude: 40.5, longitude: -74,
  source: { kind: 'community' }, metadata: {}, report_count: 0, report_threshold: 3 };
async function setup(page, options = {}) {
  let published = false;
  await page.route('**/fonts.googleapis.com/**', r => r.abort());
  await page.route('**/node_modules/.vite/deps/mapbox-gl.js*', r => r.fulfill({ contentType: 'application/javascript', body: mockMap }));
  await page.addInitScript(denied => {
    Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition(success, error) {
      if (denied) error({ code: 1 }); else success({ coords: { longitude: -74, latitude: 40.5, accuracy: 6 } });
    } } });
  }, options.denied || false);
  await page.route('**/api/**', async r => {
    const path = new URL(r.request().url()).pathname;
    if (path.endsWith('/recognize')) return r.fulfill({ json: { recognition: { facility_type: options.unknown ? 'unknown' : facility.type, description: 'A recycling facility.', suggested_name: facility.name }, recognition_token: options.unknown ? null : 'photo-ticket' } });
    if (path.endsWith('/address-search')) return r.fulfill({ json: { results: [{ name: '123 Park Road', coordinates: [-74, 40.5], address_token: 'address-ticket' }], attribution: '© Mapbox' } });
    if (path.endsWith('/reports')) return r.fulfill({ json: { report_count: 3, report_threshold: 3, removed: true } });
    if (path.endsWith('/community/facilities')) { published = true; return r.fulfill({ status: 201, json: { facility } }); }
    if (path.endsWith('/resources')) return r.fulfill({ json: published || options.existing ? [facility] : [] });
    return r.fulfill({ json: { distance: 100, duration: 60, geometry: { type: 'LineString', coordinates: [[-74, 40.5], [-74.01, 40.51]] } } });
  });
  await page.goto('/'); await expect(page.locator('#choose-start-button')).toBeEnabled();
  if (!options.existing) await page.locator('#community-tab').click();
}
async function recognize(page) {
  await page.locator('#community-file').setInputFiles({ name: 'fixture.png', mimeType: 'image/png', buffer: image });
  await page.locator('#community-recognize').click();
}
test('photo recognition, GPS confirmation, publishing and map discovery', async ({ page }) => {
  await setup(page); await recognize(page);
  await expect(page.locator('#community-recognition')).toContainText('Recycling Location');
  await expect(page.locator('#community-publish')).toBeDisabled();
  await page.locator('#community-gps').click(); await expect(page.locator('#community-location')).toContainText('accuracy ±6 m');
  await page.locator('#community-public').check();
  const sent = page.waitForRequest(r => r.url().endsWith('/community/facilities'));
  await page.locator('#community-publish').click();
  expect((await sent).postDataJSON()).toMatchObject({ latitude: 40.5, longitude: -74, location_source: 'gps', public_access_confirmed: true });
  await expect(page.locator('#community-status')).toContainText('Published!');
  await expect(page.locator('.bin-card')).toContainText('Community submission');
  await expect(page.locator('#facility-details')).toContainText('Public recycling center');
  expect(await page.evaluate(() => window.__map.markers.some(m => m.color === '#247ce3'))).toBe(true);
});
test('manual address works with denied GPS and sends selected address token', async ({ page }) => {
  await setup(page, { denied: true }); await recognize(page);
  await expect(page.locator('#community-recognition')).toContainText('Recycling Location');
  await page.locator('#community-gps').click(); await expect(page.locator('#community-status')).toContainText('Could not get GPS');
  await page.locator('#community-address').fill('123 Park Road'); await page.locator('#community-address-form button').click();
  await page.locator('#community-address-results button').click(); await page.locator('#community-public').check();
  const sent = page.waitForRequest(r => r.url().endsWith('/community/facilities'));
  await page.locator('#community-publish').click();
  expect((await sent).postDataJSON()).toMatchObject({ location_source: 'address', address_token: 'address-ticket' });
  await expect(page.locator('#community-status')).toContainText('Published!');
});
test('uncertain recognition and upstream errors never permit publishing', async ({ page }) => {
  await setup(page, { unknown: true }); await recognize(page);
  await expect(page.locator('#community-status')).toContainText('does not clearly show');
  await page.locator('#community-gps').click(); await expect(page.locator('#community-publish')).toBeDisabled();
  await page.route('**/api/community/recognize', r => r.fulfill({ status: 504, json: { detail: 'Gemini timed out. Please try again.' } }));
  await page.locator('#community-recognize').click(); await expect(page.locator('#community-status')).toContainText('Gemini timed out');
  await expect(page.locator('#community-publish')).toBeDisabled();
});
test('changing a photo invalidates recognition and ignores stale responses', async ({ page }) => {
  await setup(page);
  let release; const gate = new Promise(resolve => { release = resolve; });
  await page.route('**/api/community/recognize', async r => { await gate; await r.fulfill({ json: { recognition: { facility_type: 'Trash Bin', description: 'Old photo.', suggested_name: 'Old bin' }, recognition_token: 'stale-token' } }); });
  await recognize(page);
  await page.locator('#community-file').setInputFiles({ name: 'new.png', mimeType: 'image/png', buffer: image });
  release(); await expect(page.locator('#community-recognition')).toHaveText('');
  await expect(page.locator('#community-publish')).toBeDisabled();
});
test('report threshold removes community marker and stale route', async ({ page }) => {
  await setup(page, { existing: true });
  await page.locator('.facility-card-directions').click(); await expect(page.locator('#directions-section')).toBeVisible();
  await page.locator('.facility-card-details').click();
  await page.route('**/api/resources?*', r => r.fulfill({ json: [] }));
  await page.locator('.community-report button').click();
  await expect(page.locator('#results-count')).toHaveText('0 found');
  await expect(page.locator('#directions-section')).toBeHidden();
  expect(await page.evaluate(() => window.__map.markers.filter(m => m.color === '#247ce3').length)).toBe(0);
});
test('mobile submission controls fit the panel', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await setup(page); await recognize(page);
  await expect(page.locator('#community-status')).toContainText('Facility identified');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test('community photo quota errors appear by recognition controls without losing the photo', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await setup(page);
  await page.route('**/api/community/recognize', r => r.fulfill({status:429,json:{detail:"Gemini's daily request quota is exhausted. Wait for reset or enable billing.",code:'daily_quota_exhausted'}}));
  await recognize(page);
  await expect(page.locator('#community-photo-status')).toContainText('daily request quota');
  await expect(page.locator('#community-photo-status')).toBeInViewport();
  await expect(page.locator('#community-preview')).toBeVisible();
  await expect(page.locator('#community-recognize')).toBeEnabled();
  await expect(page.locator('#community-publish')).toBeDisabled();
});

test('unsupported camera formats show a visible message before any recognition request', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await setup(page);
  let calls=0; await page.route('**/api/community/recognize',r=>{calls++;return r.fulfill({json:{}});});
  await page.locator('#community-file').setInputFiles({name:'camera.heic',mimeType:'image/heic',buffer:Buffer.from('fixture')});
  await expect(page.locator('#community-photo-status')).toContainText('Convert HEIC');
  await expect(page.locator('#community-photo-status')).toBeInViewport(); expect(calls).toBe(0);
});
