// Explicit live smoke: one small real API search, real Mapbox, no invented facilities.
import { chromium } from '@playwright/test';
import { spawn } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';
const server=spawn(process.execPath,['node_modules/vite/bin/vite.js','--port','5181'],{stdio:'ignore',env:{...process.env,API_PROXY_TARGET:process.env.REROUTE_SMOKE_API || 'http://127.0.0.1:8000'}});
let browser, timer;
const localOnly=process.env.REROUTE_LOCAL_ONLY_SMOKE==='true';
const snapshotMode=localOnly || process.env.REROUTE_SNAPSHOT_SMOKE==='true';
const apiRoot=process.env.REROUTE_SMOKE_API || 'http://127.0.0.1:8000';
const latitude=localOnly?40.53399:snapshotMode?40.5008:40.7681, longitude=localOnly?-74.45793:snapshotMode?-74.4474:-73.9819;
const record={kind:localOnly?'genuine 10-mile saved OSM + real Mapbox rendering; local_only backend':snapshotMode?'genuine saved OSM + real Mapbox; test server forces only Overpass failure':'real backend + real Mapbox; controlled starting coordinates; small single-category request'};
try {
  for(let i=0;i<50;i++){try{if((await fetch('http://127.0.0.1:5181')).ok)break;}catch{} await new Promise(r=>setTimeout(r,100));}
  const executablePath=process.env.PLAYWRIGHT_CHROME_PATH || (existsSync('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')?'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome':undefined);
  browser=await chromium.launch({headless:true,executablePath});
  const page=await browser.newPage({viewport:{width:1280,height:900}});
  await page.addInitScript(({latitude,longitude})=>Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(success){success({coords:{latitude,longitude}});}}}),{latitude,longitude});
  let completed;
  const done=new Promise(resolve=>completed=resolve);
  await page.route('**/api/resources?*',async route=>{
    const url=new URL(apiRoot+'/resources');
    url.search=new URLSearchParams(snapshotMode?{latitude,longitude,radius:localOnly?16093:1000,include_metadata:true}:{latitude,longitude,radius:200,include_metadata:true,facility_type:'Trash Bin'}).toString();
    const started=Date.now();
    try{
      const response=await route.fetch({url:url.toString(),timeout:110000});
      record.status=response.status(); record.seconds=(Date.now()-started)/1000; record.request=url.toString();
      record.response=await response.json();
      await route.fulfill({response});
    }catch(error){record.error=error.name;await route.abort();}
    completed();
  });
  await page.goto('http://127.0.0.1:5181',{waitUntil:'domcontentloaded'});
  await Promise.race([done,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Live deadline')),115000);})]);
  clearTimeout(timer);
  if(record.status!==200)throw new Error('Facility API failed');
  await page.waitForFunction(()=>document.querySelectorAll('#bin-results .bin-card').length>0,null,{timeout:10000});
  record.cards=await page.locator('#bin-results .bin-card').count();
  record.allMarkers=await page.locator('.mapboxgl-marker').count();
  record.warning=await page.locator('#facility-warnings').textContent();
  await page.screenshot({path:snapshotMode?'/tmp/reroute-snapshot-facilities.png':'/tmp/reroute-live-facilities.png'});
  console.log(JSON.stringify({status:record.status,seconds:record.seconds,cards:record.cards,allMarkers:record.allMarkers,warning:record.warning}));
}catch(error){record.failure=error.message;console.log('Live facility browser check failed; see /tmp/reroute-live-facilities.json');process.exitCode=1;}
finally{clearTimeout(timer);writeFileSync(snapshotMode?'/tmp/reroute-snapshot-facilities.json':'/tmp/reroute-live-facilities.json',JSON.stringify(record,null,2));await browser?.close();server.kill();}
