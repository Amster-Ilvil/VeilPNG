import assert from 'node:assert/strict';
import {alignPatchContext} from './patch-geometry.mjs';
const w=120,h=120,pad=24,a=new Uint8ClampedArray(w*h*4),b=new Uint8ClampedArray(a.length);
for(let y=0;y<h;y++)for(let x=0;x<w;x++){const k=(y*w+x)*4,v=Math.round(128+60*Math.sin(x*.27)+50*Math.cos(y*.21));a.set([v,v,v,255],k);}
for(let y=0;y<h;y++)for(let x=0;x<w;x++){const k=(y*w+x)*4,j=(Math.max(0,Math.min(h-1,y-3))*w+Math.max(0,Math.min(w-1,x+4)))*4;b.set(a.subarray(j,j+4),k);if(x>=pad&&x<w-pad&&y>=pad&&y<h-pad)b.set([0,0,0,255],k);}
const r=alignPatchContext(a,b,w,h,pad);assert.ok(r.applied);assert.equal(r.dx,4);assert.equal(r.dy,-3);assert.ok(r.after>r.before);assert.equal(alignPatchContext(a,a,w,h,pad).applied,false);assert.equal(alignPatchContext(new Uint8ClampedArray(a.length),new Uint8ClampedArray(a.length),w,h,pad).applied,false);console.log('6 checks passed',r.before,r.after);
