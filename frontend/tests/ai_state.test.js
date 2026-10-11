import test from 'node:test';
import assert from 'node:assert/strict';
import { validateFile, imageDimensions, navigationAction, validateAnalysis } from '../src/ai_state.js';
const item={name:'Bottle',material:'PET plastic',bin:'recycling',steps:['Empty and confirm local acceptance.'],tip:null};
const result={answer:null,summary:'A bottle',items:[item],unsure:null};
test('images enforce supported MIME, nonempty input and size limits', () => {
  for (const type of ['image/jpeg','image/png','image/webp']) assert.doesNotThrow(()=>validateFile({type,size:100}));
  for (const file of [null,{type:'image/heic',size:100},{type:'image/png',size:0},{type:'image/png',size:9*1024*1024}]) assert.throws(()=>validateFile(file));
});
test('image sizing caps longest edge and pixel count without upscaling', () => {
  assert.deepEqual(imageDimensions(4000,2000),[1024,512]);assert.deepEqual(imageDimensions(50,100),[50,100]);
  assert.throws(()=>imageDimensions(6000,6000));assert.throws(()=>imageDimensions(0,100));
});
test('ordinary disposal links use existing resource categories', () => {
  assert.equal(navigationAction(item),'Recycling Location');assert.equal(navigationAction({...item,bin:'landfill'}),'Trash Bin');
});
test('special waste browses recycling locations without routing it to trash', () => {
  for (const bin of ['hazardous','ewaste','dropoff']) assert.equal(navigationAction({...item,bin}),'Recycling Location');
  for (const bin of ['compost','donate','unknown']) assert.equal(navigationAction({...item,bin}),null);
  for (const name of ['Battery','Electronics','Lithium cell','Plastic film','Plastic bag']) assert.equal(navigationAction({...item,name,bin:'landfill'}),'Recycling Location');
  for (const name of ['Needle','Paint']) assert.equal(navigationAction({...item,name,bin:'landfill'}),null);
});
test('response validation accepts text-only, multi-item and unknown results', () => {
  assert.equal(validateAnalysis(result),result);
  assert.doesNotThrow(()=>validateAnalysis({...result,items:[],answer:'General guidance'}));
  assert.doesNotThrow(()=>validateAnalysis({...result,items:[item,{...item,bin:'unknown',material:'Unknown'}],unsure:'Unclear item'}));
});
test('invalid categories and missing fields never become landfill', () => {
  for (const bad of [{...result,items:[{...item,bin:'oops'}]},{...result,summary:undefined},{...result,items:[{...item,steps:'Empty'}]},{...result,items:[{...item,tip:42}]},{...result,items:Array(9).fill(item)}]) assert.throws(()=>validateAnalysis(bad));
});
