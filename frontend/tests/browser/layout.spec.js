import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const mockMap = fs.readFileSync(new URL('./mapbox.mock.js', import.meta.url), 'utf8');
async function setup(page) {
  await page.route('**/fonts.googleapis.com/**', r => r.abort());
  await page.route('**/node_modules/.vite/deps/mapbox-gl.js*', r => r.fulfill({ contentType: 'application/javascript', body: mockMap }));
  await page.addInitScript(() => Object.defineProperty(navigator, 'geolocation', { value: { getCurrentPosition(success) { success({ coords: { longitude: -74, latitude: 40.5 } }); } } }));
  await page.route('**/api/resources?*', r => r.fulfill({ json: [
    { id: 'node/1', name: 'Riverside recycling', type: 'Recycling Location', latitude: 40.501, longitude: -74.001, metadata: {} },
    { id: 'node/2', name: 'Park restroom', type: 'Restroom', latitude: 40.502, longitude: -74.002, metadata: {} }
  ] }));
  await page.goto('/'); await expect(page.locator('#results-count')).toHaveText('2 found');
}
test('Explore prioritizes discovery and keeps optional trip controls tucked away', async ({ page }) => {
  await setup(page);
  await expect(page.locator('#navigation-view')).toBeVisible();
  await expect(page.locator('#route-planner')).not.toHaveAttribute('open', '');
  await expect(page.locator('#destination-search')).toBeHidden();
  await expect(page.locator('#community-file')).toBeHidden();
  await expect(page.locator('#ai-form')).toBeHidden();
  await page.locator('#route-planner summary').click(); await expect(page.locator('#destination-search')).toBeVisible();
  await page.locator('#destination-search').fill('Keep this destination');
  await page.locator('#community-tab').click(); await expect(page.locator('#community-panel')).toBeVisible();
  await page.locator('#navigation-tab').click(); await expect(page.locator('#destination-search')).toHaveValue('Keep this destination');
});
test('three-tab keyboard navigation has one active view and preserves form state', async ({ page }) => {
  await setup(page); await page.locator('#navigation-tab').focus();
  await page.keyboard.press('ArrowRight'); await expect(page.locator('#ai-tab')).toBeFocused();
  await page.locator('#ai-question').fill('Can I recycle this?');
  await page.locator('#ai-tab').focus(); await page.keyboard.press('End'); await expect(page.locator('#community-tab')).toBeFocused();
  await expect(page.locator('#community-view')).toBeVisible(); await expect(page.locator('#ai-view')).toBeHidden();
  await page.keyboard.press('ArrowRight'); await expect(page.locator('#navigation-tab')).toBeFocused();
  await page.keyboard.press('ArrowRight'); await expect(page.locator('#ai-question')).toHaveValue('Can I recycle this?');
  await expect(page.locator('[role="tab"][aria-selected="true"]')).toHaveCount(1);
});
test('desktop panel keeps navigation visible while content scrolls', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 }); await setup(page);
  await page.screenshot({ path: '/tmp/reroute-explore-desktop.png' });
  const before = await page.locator('#navigation-tab').boundingBox();
  await page.locator('.panel-content').evaluate(node => { node.scrollTop = node.scrollHeight; });
  expect((await page.locator('#navigation-tab').boundingBox()).y).toBe(before.y);
  await expect(page.locator('.facility-card-directions').first()).toBeInViewport();
  await page.locator('#community-tab').click(); await page.screenshot({ path: '/tmp/reroute-contribute-desktop.png' });
  await page.locator('#ai-tab').click(); await page.screenshot({ path: '/tmp/reroute-ai-desktop.png' });
});
test('small mobile panels scroll internally without clipping controls', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 568 }); await setup(page);
  for (const tab of ['navigation', 'ai', 'community']) {
    await page.locator(`#${tab}-tab`).click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    expect(await page.locator('.panel-content').evaluate(n => n.scrollWidth <= n.clientWidth)).toBe(true);
    await expect(page.locator(`#${tab}-tab`)).toBeInViewport();
  }
  await page.setViewportSize({ width: 390, height: 844 }); await page.locator('#navigation-tab').click();
  await page.screenshot({ path: '/tmp/reroute-explore-mobile.png' });
  await page.locator('#panel-toggle').click(); await expect(page.locator('#bin-panel')).toBeHidden();
  await page.locator('#panel-toggle').click(); await expect(page.locator('#navigation-view')).toBeVisible();
});
