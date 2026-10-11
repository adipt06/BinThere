import { defineConfig } from '@playwright/test';
import { existsSync } from 'node:fs';
const chrome = process.env.PLAYWRIGHT_CHROME_PATH || (existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome') ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : '');
export default defineConfig({
  testDir: './tests/browser', timeout: 20000, workers: 1,
  use: { baseURL: 'http://127.0.0.1:5179', headless: true,
    launchOptions: chrome ? { executablePath: chrome } : {} },
  webServer: [{ command: '../.venv/bin/python ../backend/tests/browser_server.py', url: 'http://127.0.0.1:8011/health' }, { command: 'npm run dev -- --port 5179', url: 'http://127.0.0.1:5179', reuseExistingServer: false, env: { VITE_MAPBOX_TOKEN: 'pk.browser-test-placeholder', VITE_API_BASE_URL: '/api', API_PROXY_TARGET: 'http://127.0.0.1:8011' } }],
  reporter: 'list'
});
