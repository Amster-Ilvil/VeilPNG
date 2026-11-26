import assert from 'node:assert/strict';
import {matchPatchTone} from './tone.mjs';
const w=100,h=100,pad=16,a=new Uint8ClampedArray(w*h*4),b=new Uint8ClampedArray(a.length);
for(let y=0;y<h;y++)for(let x=0;x<w;x++){const k=(y*w+x)*4,v=120+Math.round(x/4);a.set([v,v,v,255],k);b.set([v+30,v+30,v+30,255],k);if(x>=pad&&x<w-pad&&y>=pad&&y<h-pad)b.set([0,0,0,255],k);}
const center=(50*w+50)*4;a.set([0,0,0,255],center);
const r=matchPatchTone(a,b,w,h,pad);assert.ok(r.applied);assert.ok(r.after<r.before*.1);assert.equal(r.data[center],0);assert.equal(r.data[0],a[0]);assert.equal(r.data[center+4],a[center+4]+30);assert.equal(matchPatchTone(a,a,w,h,pad).applied,false);assert.throws(()=>matchPatchTone(a,b,w,h,2));console.log('7 checks passed',r.before,r.after);
