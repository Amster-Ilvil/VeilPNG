import {exportFilename} from "./naming.mjs?v=0.9.6-export1";
import {maskFor} from './core.mjs';
import {transform,transferMask,invert} from './registration.mjs';
export const bilingual=p=>p?.role==='中'||p?.role==='日';
export const opposite=(p,q)=>bilingual(p)&&bilingual(q)&&p.role!==q.role;
const clone=x=>JSON.parse(JSON.stringify(x));
export function makeLink(source,target,matrix){
 if(!opposite(source,target)||!Array.isArray(matrix)||matrix.length!==4||!matrix.every(Number.isFinite)||Math.hypot(matrix[0],matrix[1])<1e-5)throw Error('无效中日配对');
 return {source,target,matrix:[...matrix],reviewed:false,undo:[],redo:[]};
}
export const linkFor=(links,p)=>links.find(l=>l.source===p||l.target===p);
export const other=(l,p)=>l.source===p?l.target:l.source;
export function mappedOp(l,p,op){
 const q=other(l,p),m=l.source===p?l.matrix:invert(l.matrix);
 const pts=op.kind==='rect'?[op.a,[op.a[0],op.b[1]],[op.b[0],op.a[1]],op.b]:op.points;
 if(pts.map(z=>transform(m,...z)).some(([x,y])=>x<0||y<0||x>q.width-1||y>q.height-1))throw Error('对应选区越界，请关闭同步并分别标记');
 return transferMask([op],m,q.width,q.height)[0];
}
export const snapshot=l=>[l.source,l.target].map(p=>({ops:clone(p.ops),shade:p.shade}));
export function applySnapshot(l,s){[l.source,l.target].forEach((p,i)=>{p.ops=clone(s[i].ops);p.shade=s[i].shade;p.redo=[];});l.reviewed=false;}
export const hasMask=p=>!!p?.ops?.length&&maskFor(p.width,p.height,p.ops).some(Boolean);
export function exportPlan(pages,links){
 const out=[],used=new Set();
 for(const p of pages){if(used.has(p))continue;
 if(bilingual(p)){
 const l=linkFor(links,p),q=l&&other(l,p);
 if(!q||!pages.includes(q)||!opposite(p,q)||used.has(q))throw Error('请完成中日同页配对：'+p.file.name);
 if(!hasMask(p)||!hasMask(q))throw Error('中日两侧必须都有有效选区：'+p.file.name);
 if(!l.reviewed)throw Error('请确认两侧遮盖：'+p.file.name);
 used.add(p);used.add(q);
 for(const v of (p.role==='中'?[p,q]:[q,p]))out.push({page:v,name:exportFilename(pages,pages.indexOf(v),'redacted')});
 }else if(hasMask(p)){used.add(p);out.push({page:p,name:exportFilename(pages,pages.indexOf(p),'redacted')});}
 }if(!out.length)throw Error('没有可导出的选区');return out;
}
