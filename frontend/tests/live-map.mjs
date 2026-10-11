// Explicit smoke test against real Mapbox; no facility queries are triggered.
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
const server = spawn(process.execPath, ['node_modules/vite/bin/vite.js','--port','5181'], {stdio:'ignore'});
let browser;
try {
  for(let i=0;i<50;i++) { try { if((await fetch('http://127.0.0.1:5181')).ok) break; } catch {} await new Promise(r=>setTimeout(r,100)); }
  const executablePath = process.env.PLAYWRIGHT_CHROME_PATH || (existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome') ? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' : undefined);
  browser = await chromium.launch({headless:true,executablePath});
  const page = await browser.newPage({viewport:{width:1280,height:900}});
  await page.addInitScript(()=>Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(_success,error){error({code:1});}}}));
  await page.goto('http://127.0.0.1:5181', {waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>!document.getElementById('choose-start-button').disabled,null,{timeout:45000});
  await page.screenshot({path:'/tmp/reroute-live-map.png'});
  console.log('PASS: real Mapbox/WebGL map loaded; manual start controls enabled after GPS denial.');
} catch {
  console.log('FAIL: real map did not initialize within the smoke-test deadline; check token URL restrictions, network and WebGL.');
  process.exitCode=1;
} finally { await browser?.close(); server.kill(); }
