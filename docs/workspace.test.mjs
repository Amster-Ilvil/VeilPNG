import assert from 'node:assert/strict';
import {makePrivateBundle,unpackPrivateBundle,restoreLinks,roleFromPublicName} from './workspace.mjs';
import {sourceHash} from './return-core.mjs';
import {makeLink,exportPlan} from './bilingual.mjs';
import {readPublicZip} from './zip-read.mjs';
import {zipStore} from './core.mjs';
// Synthetic data only; newPage stands in for image decoding.
async function newPage(file,role){return {file,role,hash:await sourceHash(file),width:40,height:40,ops:[],shade:0,redo:[]};}
const p=await newPage(new File([Uint8Array.of(255,216,255,1)],'cn.jpg'),'中');
const q=await newPage(new File([Uint8Array.of(255,216,255,2)],'jp.jpg'),'日');
p.ops=[{kind:'rect',a:[5,5],b:[10,10]}];q.ops=[{kind:'rect',a:[8,9],b:[13,14]}];
const l=makeLink(p,q,[1,0,3,4]);
const privateZip=await makePrivateBundle([p,q],[l]);
const r=await unpackPrivateBundle(privateZip,newPage);
assert.deepEqual(r.pages.map(x=>x.ops),[p.ops,q.ops]);
assert.deepEqual(r.pages.map(x=>x.hash),[p.hash,q.hash]);
assert.deepEqual(r.links[0].matrix,l.matrix);
assert.equal(r.links[0].reviewed,false);
assert.equal(restoreLinks({},r.pages).length,0);
r.links[0].reviewed=true;
const plan=exportPlan(r.pages,r.links);
assert.deepEqual(plan.map(x=>x.name),['0001_CN_redacted.png','0001_JP_redacted.png']);
const publicZip=new Blob(zipStore(plan.map(x=>({name:x.name,data:Uint8Array.of(1,2,3)}))));
assert.deepEqual((await readPublicZip(publicZip,'return')).map(f=>roleFromPublicName(f.name)),['中','日']);
await assert.rejects(()=>readPublicZip(privateZip,'return'));
await assert.rejects(()=>unpackPrivateBundle(publicZip,newPage));
const bytes=new Uint8Array(await privateZip.arrayBuffer());bytes[50]^=1;
await assert.rejects(()=>unpackPrivateBundle(new Blob([bytes]),newPage));
console.log('10 workspace checks passed');
