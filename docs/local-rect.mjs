import {transform} from './registration.mjs';
// Refine rectangular selections using observed solid-color bounds, not arbitrary dilation.
export function rectanglePlan(ops,shade,sw,sh,rgba,w,h,m){
 if(!ops.length||ops.some(o=>o.kind!=='rect'))return null;
 if(![0,255].includes(shade)||rgba.length!==w*h*4||!m.every(Number.isFinite))throw Error('无效矩形配准输入');
 const clamp=(v,lo,hi)=>Math.min(hi,Math.max(lo,v));
 const solid=(x,y)=>{const i=(y*w+x)*4;return Math.max(Math.abs(rgba[i]-shade),Math.abs(rgba[i+1]-shade),Math.abs(rgba[i+2]-shade))<=48;};
 const run=(a,k)=>{if(k<0||k>=a.length||!a[k])return null;let lo=k,hi=k;while(lo>0&&a[lo-1])lo--;while(hi+1<a.length&&a[hi+1])hi++;return [lo,hi];};
 const overlaps=(a,b)=>a[0]<=b[2]&&b[0]<=a[2]&&a[1]<=b[3]&&b[1]<=a[3];
 const out=[];
 for(const op of ops){
  const src=[Math.min(op.a[0],op.b[0]),Math.min(op.a[1],op.b[1]),Math.max(op.a[0],op.b[0]),Math.max(op.a[1],op.b[1])];
  if(src[0]<0||src[1]<0||src[2]>=sw||src[3]>=sh)throw Error('原选区越界');
  const pts=[[src[0],src[1]],[src[0],src[3]],[src[2],src[1]],[src[2],src[3]]].map(p=>transform(m,...p));
  const l=Math.min(...pts.map(p=>p[0])),t=Math.min(...pts.map(p=>p[1])),r=Math.max(...pts.map(p=>p[0])),b=Math.max(...pts.map(p=>p[1])),dx=r-l,dy=b-t;
  if(dx<8||dy<8||l<0||t<0||r>w-1||b>h-1)return null;
  const x0=clamp(Math.floor(l-dx*.25),0,w-1),x1=clamp(Math.ceil(r+dx*.25),0,w-1),y0=clamp(Math.floor(t-dy*.25),0,h-1),y1=clamp(Math.ceil(b+dy*.25),0,h-1);
  const ax=Math.ceil(l+dx*.25),bx=Math.floor(r-dx*.25),ay=Math.ceil(t+dy*.25),by=Math.floor(b-dy*.25);
  const rows=[],cols=[];
  for(let y=y0;y<=y1;y++){let n=0;for(let x=ax;x<=bx;x++)if(solid(x,y))n++;rows.push(n/(bx-ax+1)>=.97);}
  for(let x=x0;x<=x1;x++){let n=0;for(let y=ay;y<=by;y++)if(solid(x,y))n++;cols.push(n/(by-ay+1)>=.97);}
  const yr=run(rows,Math.floor((t+b)/2)-y0),xr=run(cols,Math.floor((l+r)/2)-x0);
  if(!yr||!xr||yr[0]===0||xr[0]===0||yr[1]===rows.length-1||xr[1]===cols.length-1)return null;
  // A dark/white background touching the cover can join the loose solid run.
  // Only shrink an inflated run when a tighter shade band agrees with the
  // registered geometry; never extend a rectangle based on surrounding ink.
  const tight=(x,y)=>{const i=(y*w+x)*4;return Math.max(Math.abs(rgba[i]-shade),Math.abs(rgba[i+1]-shade),Math.abs(rgba[i+2]-shade))<=8;};
  function calibrate(lo,hi,p0,p1,origin,flags,center){
   const span=p1-p0+1,tol=Math.max(3,Math.min(6,Math.round(span*.025)));
   if(hi-lo+1<=span+tol)return [lo,hi];
   const q=run(flags,center-origin);if(!q)return null;
   const a=origin+q[0],b=origin+q[1];
   if(a<lo||b>hi||Math.abs(a-p0)>tol||Math.abs(b-p1)>tol||Math.abs(b-a+1-span)>tol)return null;
   return [a,b];
  }
  const tightCols=[],tightRows=[];
  for(let x=x0;x<=x1;x++){let n=0;for(let y=ay;y<=by;y++)if(tight(x,y))n++;tightCols.push(n/(by-ay+1)>=.75);}
  for(let y=y0;y<=y1;y++){let n=0;for(let x=ax;x<=bx;x++)if(tight(x,y))n++;tightRows.push(n/(bx-ax+1)>=.75);}
  const xx=calibrate(x0+xr[0],x0+xr[1],l,r,x0,tightCols,Math.floor((l+r)/2));
  const yy=calibrate(y0+yr[0],y0+yr[1],t,b,y0,tightRows,Math.floor((t+b)/2));
  if(!xx||!yy)return null;
  const dst=[xx[0],yy[0],xx[1],yy[1]],dw=dst[2]-dst[0]+1,dh=dst[3]-dst[1]+1;
  if(dw/dx<.75||dw/dx>1.25||dh/dy<.75||dh/dy>1.25)return null;
  let count=0;for(let y=dst[1];y<=dst[3];y++)for(let x=dst[0];x<=dst[2];x++)if(solid(x,y))count++;
  if(count/(dw*dh)<.98||out.some(q=>overlaps(q.dst,dst)||overlaps(q.src,src)))return null;
  out.push({src,dst,density:count/(dw*dh),calibrated:dst[0]!==x0+xr[0]||dst[1]!==y0+yr[0]||dst[2]!==x0+xr[1]||dst[3]!==y0+yr[1]});
 }
 return out;
}
