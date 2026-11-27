// Independent, mask-excluded context verification and return candidate selection.
export function verifyReturnGrid(a,b,mask,w,h,sw,sh){
 if(w<30||h<30||a.length!==w*h||b.length!==a.length||mask.length!==sw*sh)return null;
 const sx=sw/w,sy=sh/h,rx=Math.max(1,Math.ceil(sx*4)),ry=Math.max(1,Math.ceil(sy*4));
 let total=0,good=0,texture=0,textureGood=0;const cells=new Set(),matchedCells=new Set();
 for(let y=5;y<h-5;y+=3)for(let x=5;x<w-5;x+=3){
  const ox=Math.min(sw-1,Math.floor((x+.5)*sx)),oy=Math.min(sh-1,Math.floor((y+.5)*sy));let blocked=false;
  for(const dy of [-ry,0,ry])for(const dx of [-rx,0,rx]){
   const xx=Math.min(sw-1,Math.max(0,ox+dx)),yy=Math.min(sh-1,Math.max(0,oy+dy));
   if(mask[yy*sw+xx])blocked=true;
  }
  if(blocked)continue;
  const k=y*w+x,d=Math.abs(a[k]-b[k]);
  const ax=a[k+2]-a[k-2],ay=a[k+2*w]-a[k-2*w],bx=b[k+2]-b[k-2],by=b[k+2*w]-b[k-2*w];
  const ok=d<=32;total++;if(ok)good++;
  if(Math.abs(ax)+Math.abs(ay)<30)continue;
  const cell=Math.floor(x*3/w)+','+Math.floor(y*3/h);cells.add(cell);texture++;
  if(ok&&Math.abs(ax-bx)+Math.abs(ay-by)<=54){textureGood++;matchedCells.add(cell);}
 }
 if(total<100||texture<24||cells.size<3||matchedCells.size<3||good/total<.82||textureGood/texture<.75)return null;
 return {inliers:Math.min(650,textureGood),matches:Math.min(650,texture),gridContext:true,contextRatio:good/total,textureRatio:textureGood/texture};
}
export function scaledMatrix(sw,sh,tw,th){
 if(Math.min(sw,sh,tw,th)<2||Math.abs((tw/th)/(sw/sh)-1)>.007)return null;
 const s=Math.min((tw-1)/(sw-1),(th-1)/(sh-1));
 if(s<.2||s>5)return null;
 const x=Math.max(0,(tw-1-s*(sw-1))/2),y=Math.max(0,(th-1-s*(sh-1))/2);
 return [s,0,x,y];
}
export function returnDecision(hits,named=[],legacyRole=''){
 const strong=hits.filter(r=>r.inliers>=20&&r.inliers/r.matches>=.35);
 const weak=hits.filter(r=>!strong.includes(r)&&r.inliers>=12&&r.inliers/r.matches>=.25);
 const preferred=strong.filter(r=>named.includes(r.i));
 if(named.length===1&&preferred.length===1)return {hit:preferred[0]};
 const byRole=legacyRole&&!named.length?strong.filter(r=>r.role===legacyRole):[];
 const pool=(byRole.length?byRole:strong).slice().sort((a,b)=>b.inliers-a.inliers);
 if(pool.length&&(!pool[1]||pool[0].inliers>=1.18*pool[1].inliers)){
  // A filename pointing elsewhere is a conflict, not permission to auto-pair.
  if(!named.length||named.includes(pool[0].i))return {hit:pool[0]};
 }
 const candidates=[...strong,...weak].sort((a,b)=>Number(named.includes(b.i))-Number(named.includes(a.i))||b.inliers-a.inliers);
 return {candidates};
}
