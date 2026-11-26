import assert from 'node:assert/strict';
import {rectanglePlan} from './local-rect.mjs';
const w=100,h=100,rgba=new Uint8Array(w*h*4).fill(255),ops=[{kind:'rect',a:[20,20],b:[49,49]}];
for(let y=23;y<=52;y++)for(let x=24;x<=53;x++)rgba.fill(0,(y*w+x)*4,(y*w+x)*4+3);
assert.deepEqual(rectanglePlan(ops,0,w,h,rgba,w,h,[1,0,0,0])[0].dst,[24,23,53,52]);
assert.equal(rectanglePlan(ops,0,w,h,new Uint8Array(w*h*4).fill(255),w,h,[1,0,0,0]),null);
assert.equal(rectanglePlan(ops,0,w,h,new Uint8Array(w*h*4),w,h,[1,0,0,0]),null);
assert.equal(rectanglePlan([{kind:'brush'}],0,w,h,rgba,w,h,[1,0,0,0]),null);
console.log('4 rectangle checks passed');
