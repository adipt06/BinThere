import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const mockMap=fs.readFileSync(new URL('./mapbox.mock.js',import.meta.url),'utf8');
const image=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=','base64');
const bottle={name:'Water bottle',material:'PET plastic',bin:'recycling',steps:['Empty it.','Check local acceptance.'],tip:'Try reuse.'};
const result={answer:'Here is general guidance.',summary:'A plastic bottle.',items:[bottle],unsure:'Local rules have not been verified.'};
const facilities=[{id:'node/1',name:'Mapped recycling',type:'Recycling Location',latitude:40.505,longitude:-74.005,metadata:{'recycling:plastic_bottles':'yes'},coordinate_source:'node'},{id:'node/2',name:'Mapped bin',type:'Trash Bin',latitude:40.505,longitude:-74.005,metadata:{},coordinate_source:'node'}];
const walking={distance:1000,duration:600,geometry:{type:'LineString',coordinates:[[-74,40.5],[-74.01,40.51]]}};
async function setup(page) {
  await page.route('**/fonts.googleapis.com/**',r=>r.abort());
  await page.route('**/node_modules/.vite/deps/mapbox-gl.js*',r=>r.fulfill({contentType:'application/javascript',body:mockMap}));
  await page.addInitScript(()=>Object.defineProperty(navigator,'geolocation',{value:{getCurrentPosition(success){success({coords:{longitude:-74,latitude:40.5}});}}}));
  await page.route('**/api/**',r=>r.fulfill({json:r.request().url().includes('/resources?')?facilities:walking}));
  await page.route('**/api/ai/analyze',r=>r.fulfill({json:result}));
  await page.goto('/');await expect(page.locator('#results-count')).toHaveText('2 found');
  await page.locator('#ai-tab').click();
}
async function ask(page) {await page.locator('#ai-question').fill('How do I recycle this?');await page.locator('#ai-submit').click();await expect(page.locator('#ai-results')).toBeVisible();}
async function upload(page) {await page.locator('#ai-file').setInputFiles({name:'test.png',mimeType:'image/png',buffer:image});await expect(page.locator('#ai-preview')).toBeVisible();}

test('text-only question renders answer, preparation, tips and uncertainty safely',async({page})=>{
  await setup(page);await ask(page);
  await expect(page.locator('#ai-answer')).toHaveText(result.answer);await expect(page.locator('.ai-item')).toHaveCount(1);
  await expect(page.locator('.ai-item')).toContainText('Empty it.');await expect(page.locator('.ai-item')).toContainText('Try reuse.');
  await expect(page.locator('#ai-unsure')).toContainText('not been verified');
});
test('upload compresses to JPEG and sends image plus question and location via multipart',async({page})=>{
  await setup(page);await upload(page);await page.locator('#ai-place').fill('08854');
  const request=page.waitForRequest('**/api/ai/analyze');await ask(page);const sent=await request;
  expect(sent.headers()['content-type']).toContain('multipart/form-data');expect(sent.postDataBuffer().toString('latin1')).toContain('image/jpeg');
  expect(sent.postDataBuffer().toString('latin1')).toContain('08854');expect(sent.postDataBuffer().toString('latin1')).toContain('How do I recycle this?');
});
test('photo can be replaced and removed without submitting stale image',async({page})=>{
  await setup(page);await upload(page);await upload(page);await page.locator('#ai-remove').click();
  await expect(page.locator('#ai-preview')).toBeHidden();const request=page.waitForRequest('**/api/ai/analyze');await ask(page);
  expect((await request).postDataBuffer().toString()).not.toContain('name="image"');
});
for (const kind of ['drop','paste']) test(`${kind} accepts actual image bytes and previews them`,async({page})=>{
  await setup(page);await page.evaluate(({bytes,kind})=>{
    const file=new File([new Uint8Array(bytes)],'pasted.png',{type:'image/png'});const transfer=new DataTransfer();transfer.items.add(file);
    if(kind==='drop')document.getElementById('ai-drop').dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
    else window.dispatchEvent(new ClipboardEvent('paste',{bubbles:true,cancelable:true,clipboardData:transfer}));
  },{bytes:[...image],kind});await expect(page.locator('#ai-preview')).toBeVisible();
});
test('image-only analysis is allowed',async({page})=>{
  await setup(page);await upload(page);await page.locator('#ai-submit').click();await expect(page.locator('#ai-results')).toBeVisible();
});
test('unsupported corrupt and oversized images show errors without API calls',async({page})=>{
  await setup(page);let requests=0;page.on('request',r=>{if(r.url().includes('/ai/analyze'))requests++;});
  for (const [mimeType,buffer,message] of [['image/svg+xml',Buffer.from('<svg/>'),'JPEG, PNG or WebP'],['image/png',Buffer.from('broken'),'Cannot decode'],['image/png',Buffer.alloc(8*1024*1024+1),'8 MB']]){
    await page.locator('#ai-file').setInputFiles({name:'bad',mimeType,buffer});await expect(page.locator('#ai-status')).toContainText(message);
  }expect(requests).toBe(0);
});
test('empty inputs prevent request and duplicate submissions are blocked',async({page})=>{
  await setup(page);await page.locator('#ai-submit').click();await expect(page.locator('#ai-status')).toContainText('Add a photo');
  let count=0;await page.route('**/api/ai/analyze',async r=>{count++;await new Promise(resolve=>setTimeout(resolve,250));await r.fulfill({json:result});});
  await page.locator('#ai-question').fill('Hi');await page.locator('#ai-submit').click();await expect(page.locator('#ai-submit')).toBeDisabled();
  await page.locator('#ai-form').evaluate(form=>form.requestSubmit());await expect(page.locator('#ai-results')).toBeVisible();expect(count).toBe(1);
});
test('recycling action preserves trip and route and filters existing genuine-resource contract',async({page})=>{
  await setup(page);await page.locator('#navigation-tab').click();await page.locator('#route-planner summary').click();await page.locator('#choose-destination-button').click();await page.locator('#mock-map-canvas').click({position:{x:750,y:200}});
  await page.locator('#direct-route-button').click();await expect(page.locator('#directions-section')).toBeVisible();
  const before=await page.evaluate(()=>JSON.stringify({sources:window.__map.sources,start:window.__map.markers.find(m=>m.color==='#3987ff').coordinates}));
  await page.locator('#ai-tab').click();await ask(page);await page.getByRole('button',{name:'Find recycling locations',exact:true}).click();
  await expect(page.locator('#navigation-view')).toBeVisible();await expect(page.locator('#facility-filter')).toHaveValue('Recycling Location');
  await expect(page.locator('.bin-card')).toHaveCount(1);await expect(page.locator('.bin-card')).toContainText('Mapped recycling');
  expect(await page.evaluate(()=>JSON.stringify({sources:window.__map.sources,start:window.__map.markers.find(m=>m.color==='#3987ff').coordinates}))).toBe(before);
  await expect(page.locator('#directions-section')).toBeVisible();
});
test('ordinary trash and general recycling browsing retain distinct actions',async({page})=>{
  await setup(page);await page.route('**/api/ai/analyze',r=>r.fulfill({json:{...result,items:[{...bottle,bin:'landfill',name:'Soiled wrapper'},{...bottle,name:'Battery',bin:'hazardous'},{...bottle,name:'Old phone',bin:'ewaste'},{...bottle,bin:'unknown',material:'Unknown'},{...bottle,bin:'compost'},{...bottle,bin:'dropoff'},{...bottle,bin:'donate'}]}}));
  await ask(page);await expect(page.locator('.ai-item')).toHaveCount(7);await expect(page.locator('.ai-item button')).toHaveCount(4);
  await expect(page.locator('#ai-items')).toContainText('Acceptance is unverified');
  await expect(page.locator('#ai-items')).toContainText('does not currently have a verified');await page.getByRole('button',{name:'Find trash bins',exact:true}).click();
  await expect(page.locator('#facility-filter')).toHaveValue('Trash Bin');
});
test('malformed response is rejected and server errors recover on retry',async({page})=>{
  await setup(page);await page.route('**/api/ai/analyze',r=>r.fulfill({json:{...result,items:[{...bottle,bin:'unrecognized'}]}}));
  await page.locator('#ai-question').fill('Hi');await page.locator('#ai-submit').click();await expect(page.locator('#ai-status')).toContainText('invalid disposal guidance');await expect(page.locator('#ai-results')).toBeHidden();
  await page.route('**/api/ai/analyze',r=>r.fulfill({status:429,json:{detail:'Gemini rate limit reached. Wait a minute.'}}));
  await page.locator('#ai-submit').click();await expect(page.locator('#ai-status')).toContainText('rate limit');await expect(page.locator('#ai-submit')).toBeEnabled();
  await page.route('**/api/ai/analyze',r=>r.fulfill({json:result}));await page.locator('#ai-submit').click();await expect(page.locator('#ai-results')).toBeVisible();
});
test('cancel and edited question ignore stale responses',async({page})=>{
  await setup(page);await page.route('**/api/ai/analyze',async r=>{await new Promise(resolve=>setTimeout(resolve,300));await r.fulfill({json:result});});
  await page.locator('#ai-question').fill('Hi');await page.locator('#ai-submit').click();await page.locator('#ai-cancel').click();
  await expect(page.locator('#ai-status')).toContainText('canceled');await page.waitForTimeout(400);await expect(page.locator('#ai-results')).toBeHidden();
  await page.locator('#ai-submit').click();await page.locator('#ai-question').fill('Changed question');await page.waitForTimeout(400);await expect(page.locator('#ai-results')).toBeHidden();await expect(page.locator('#ai-submit')).toBeEnabled();
});
test('model HTML is rendered as text and empty results are explained',async({page})=>{
  await setup(page);await page.route('**/api/ai/analyze',r=>r.fulfill({json:{...result,summary:'<img src=x onerror=alert(1)>',answer:null,items:[],unsure:null}}));await ask(page);
  await expect(page.locator('#ai-summary img')).toHaveCount(0);await expect(page.locator('#ai-summary')).toContainText('<img');await expect(page.locator('#ai-unsure')).toContainText('No recognizable');
});
test('mobile tabs preserve assistant state with no horizontal overflow',async({page})=>{
  await page.setViewportSize({width:390,height:844});await setup(page);await ask(page);
  await page.locator('#navigation-tab').click();await page.locator('#ai-tab').click();await expect(page.locator('#ai-results')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});

test('request timeouts show a useful error and release the submit button',async({page})=>{
  await setup(page);await page.evaluate(()=>{const original=window.fetch;window.fetch=(url,options)=>String(url).endsWith('/ai/analyze')?Promise.reject(new DOMException('timeout','TimeoutError')):original(url,options);});
  await page.locator('#ai-question').fill('Hi');await page.locator('#ai-submit').click();await expect(page.locator('#ai-status')).toContainText('timed out');await expect(page.locator('#ai-submit')).toBeEnabled();
});
test('AI tab cancels pending map selection without resetting the trip',async({page})=>{
  await setup(page);await page.locator('#navigation-tab').click();await page.locator('#route-planner summary').click();await page.locator('#choose-destination-button').click();
  await expect(page.locator('#cancel-selection-button')).toBeVisible();await page.locator('#ai-tab').click();
  await expect(page.locator('#cancel-selection-button')).toBeHidden();
  await page.locator('#navigation-tab').click();await expect(page.locator('#start-hint')).toContainText('Start:');
});


test('battery action expands discovery and focuses closest mapped recycling location',async({page})=>{
  await setup(page);
  await page.route('**/api/ai/analyze',r=>r.fulfill({json:{...result,items:[{...bottle,name:'Lithium battery',material:'Lithium-ion',bin:'hazardous'}]}}));
  let radius;
  const closer={...facilities[0],id:'node/3',name:'Closer mapped location',latitude:40.5001,longitude:-74.0001};
  await page.route('**/api/resources?*',r=>{radius=new URL(r.request().url()).searchParams.get('radius');return r.fulfill({json:[facilities[0],closer]});});
  await ask(page);await page.getByRole('button',{name:'Find nearby recycling centers',exact:true}).click();
  await expect(page.locator('#facility-details')).toContainText('Closer mapped location');
  await expect(page.locator('#bin-status')).toContainText('Acceptance of Lithium battery is unverified');
  expect(radius).toBe('16093');await expect(page.locator('#distance-filter')).toHaveValue('16093');
  expect(await page.evaluate(()=>window.__map.fly.center)).toEqual([closer.longitude,closer.latitude]);
  expect(await page.evaluate(()=>window.__map.markers.find(m=>m.color==='#3987ff').coordinates)).toEqual([-74,40.5]);
});

test('recycling handoff reports failed discovery instead of claiming a closest facility',async({page})=>{
  await setup(page);await ask(page);
  await page.route('**/api/resources?*',r=>r.fulfill({status:503,json:{detail:'Outside saved coverage'}}));
  await page.getByRole('button',{name:'Find recycling locations',exact:true}).click();
  await expect(page.locator('#bin-results')).toContainText('Outside saved coverage');
  await expect(page.locator('#facility-details')).toBeHidden();
});

test('photo quota failure is visible on mobile and preserves the photo for retry', async ({page}) => {
  await page.setViewportSize({width:390,height:844}); await setup(page); await upload(page);
  await page.route('**/api/ai/analyze', r => r.fulfill({status:429,json:{detail:"Gemini's daily request quota is exhausted. Wait for reset or enable billing.",code:'daily_quota_exhausted',retry_after_seconds:55262}}));
  await page.locator('#ai-submit').click();
  await expect(page.locator('#ai-status')).toContainText('daily request quota');
  await expect(page.locator('#ai-status')).toBeInViewport();
  await expect(page.locator('#ai-preview')).toBeVisible();
  await expect(page.locator('#ai-submit')).toBeEnabled();
  await page.route('**/api/ai/analyze',r=>r.fulfill({json:result}));
  const sent=page.waitForRequest('**/api/ai/analyze'); await page.locator('#ai-submit').click();
  expect((await sent).postDataBuffer().toString('latin1')).toContain('image/jpeg');
  await expect(page.locator('#ai-results')).toBeInViewport();
});
test('slow recognition shows elapsed progress and editing explicitly explains cancellation', async ({page}) => {
  await setup(page); await page.clock.install();
  await page.route('**/api/ai/analyze', () => {});
  await page.locator('#ai-question').fill('Identify this'); await page.locator('#ai-submit').click();
  await page.clock.fastForward(21000); await expect(page.locator('#ai-status')).toContainText('21s elapsed');
  await page.locator('#ai-question').fill('Changed input');
  await expect(page.locator('#ai-status')).toContainText('cancelled because the inputs changed');
  await expect(page.locator('#ai-submit')).toBeEnabled();
  await page.clock.fastForward(2000); await expect(page.locator('#ai-status')).toContainText('cancelled because');
});
test('non-JSON proxy failures have a readable error instead of a blank result', async ({page}) => {
  await setup(page); await page.route('**/api/ai/analyze', r => r.fulfill({status:502,contentType:'text/html',body:'<h1>Bad Gateway</h1>'}));
  await page.locator('#ai-question').fill('Identify this'); await page.locator('#ai-submit').click();
  await expect(page.locator('#ai-status')).toContainText('HTTP 502'); await expect(page.locator('#ai-submit')).toBeEnabled();
});
