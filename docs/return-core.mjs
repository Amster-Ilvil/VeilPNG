const FORMAT='veilpng-web-mask-v1';
const integer=(n,min,max)=>Number.isInteger(n)&&n>=min&&n<=max;
const dimensions=(w,h)=>integer(w,1,12000)&&integer(h,1,12000)&&w*h<=12000000;
const hashOK=h=>typeof h==='string'&&/^[0-9a-f]{64}$/.test(h);
export async function sourceHash(file){
  if(!globalThis.crypto?.subtle)throw Error('请使用 HTTPS 或 localhost 打开工作台');
  return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await file.arrayBuffer())),x=>x.toString(16).padStart(2,'0')).join('');
}
export function maskRecord(w,h,hash,ops,shade){
  if(!dimensions(w,h)||!hashOK(hash)||![0,255].includes(shade)||!Array.isArray(ops)||ops.length>128)throw Error('遮盖记录无效');
  const point=p=>Array.isArray(p)&&p.length===2&&integer(p[0],0,w-1)&&integer(p[1],0,h-1);
  const clean=ops.map(o=>{
    if(!o||typeof o!=='object')throw Error('无效选区');
    if(o.kind==='rect'&&point(o.a)&&point(o.b))return {kind:'rect',a:[...o.a],b:[...o.b]};
    if(['brush','erase'].includes(o.kind)&&integer(o.radius,1,128)&&Array.isArray(o.points)&&o.points.length>=1&&o.points.length<=2048&&o.points.every(point))return {kind:o.kind,radius:o.radius,points:o.points.map(p=>[...p])};
    throw Error('无效选区');
  });
  return {format:FORMAT,width:w,height:h,sourceSha256:hash,shade,ops:clean};
}
export function loadMaskRecord(raw,w,h,hash){
  if(typeof raw!=='string'||raw.length>6000000)throw Error('遮盖记录超限');
  let r;try{r=JSON.parse(raw);}catch{throw Error('遮盖记录不是有效 JSON');}
  if(!r||r.format!==FORMAT||r.width!==w||r.height!==h||r.sourceSha256!==hash)throw Error('遮盖记录与当前原图不匹配');
  return maskRecord(w,h,hash,r.ops,r.shade);
}
export function restoreRGBA(original,returned,mask){
  if(original.length!==returned.length||original.length!==mask.length*4)throw Error('像素缓冲尺寸不匹配');
  let count=0;
  for(let i=0;i<mask.length;i++)if(mask[i]){const p=i*4;returned[p]=original[p];returned[p+1]=original[p+1];returned[p+2]=original[p+2];returned[p+3]=original[p+3];count++;}
  if(!count)throw Error('没有有效遮盖区域');
  return count;
}
