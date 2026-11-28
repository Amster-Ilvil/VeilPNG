// Browser-only, dependency-free coarse similarity registration. No image data leaves the browser.
function features(g,w,h){
  const candidates=[], step=3, margin=14;
  for(let y=margin;y<h-margin;y+=step)for(let x=margin;x<w-margin;x+=step){
    let xx=0,yy=0,xy=0;
    for(let j=-3;j<=3;j++)for(let i=-3;i<=3;i++){const k=(y+j)*w+x+i,dx=g[k+1]-g[k-1],dy=g[k+w]-g[k-w];xx+=dx*dx;yy+=dy*dy;xy+=dx*dy;}
    const score=(xx+yy-Math.hypot(xx-yy,2*xy))/2;
    if(score>15000)candidates.push({x,y,score});
  }
  candidates.sort((a,b)=>b.score-a.score);
  const out=[], occupied=new Set();
  for(const p of candidates){const k=Math.floor(p.x/9)+','+Math.floor(p.y/9);if(occupied.has(k))continue;occupied.add(k);
    const d=[];let sum=0,ss=0;
    for(let j=-10;j<=10;j+=3)for(let i=-10;i<=10;i+=3){let v=0;for(let vj=-1;vj<=1;vj++)for(let vi=-1;vi<=1;vi++)v+=g[(p.y+j+vj)*w+p.x+i+vi];v/=9;d.push(v);sum+=v;ss+=v*v;}
    const mean=sum/d.length,norm=Math.sqrt(ss-sum*mean);if(norm<80)continue;p.d=d.map(v=>(v-mean)/norm);out.push(p);if(out.length>=650)break;
  }return out;
}
function matches(a,b){const out=[];for(const p of a){let d1=Infinity,d2=Infinity,best=null;for(const q of b){let d=0;for(let k=0;k<p.d.length;k++){const t=p.d[k]-q.d[k];d+=t*t;}if(d<d1){d2=d1;d1=d;best=q;}else if(d<d2)d2=d;}if(best&&d1<0.55&&d1<.75*d2)out.push([p,best]);}return out;}
function fit(ps){let x=0,y=0,u=0,v=0;for(const [p,q] of ps){x+=p.x;y+=p.y;u+=q.x;v+=q.y;}x/=ps.length;y/=ps.length;u/=ps.length;v/=ps.length;let den=0,a=0,b=0;for(const [p,q] of ps){const dx=p.x-x,dy=p.y-y,du=q.x-u,dv=q.y-v;den+=dx*dx+dy*dy;a+=dx*du+dy*dv;b+=dx*dv-dy*du;}if(den<1)throw Error('对应点分布不足');a/=den;b/=den;return [a,b,u-a*x+b*y,v-b*x-a*y];}
export function transform(m,x,y){return [m[0]*x+(m[4]??-m[1])*y+m[2],m[1]*x+(m[5]??m[0])*y+m[3]];}
export function registerGray(a,b,includePoints=false){
  if(a.w<30||b.w<30||a.h!==b.h||a.h>800||a.w>1600||b.w>1600||a.data.length!==a.w*a.h||b.data.length!==b.w*b.h)throw Error('配准缩略图无效');
  const pairs=matches(features(a.data,a.w,a.h),features(b.data,b.w,b.h));let best=[];const limit=Math.min(pairs.length,160);
  function inliers(m){return pairs.filter(([p,q])=>{const [x,y]=transform(m,p.x,p.y);return Math.hypot(x-q.x,y-q.y)<=3.5;});}
  for(let i=0;i<limit;i++)for(let j=i+1;j<limit;j++){const p=pairs[i][0],q=pairs[j][0];if(Math.hypot(p.x-q.x,p.y-q.y)<45)continue;const m=fit([pairs[i],pairs[j]]),s=Math.hypot(m[0],m[1]);if(s<.7||s>1.4||Math.abs(Math.atan2(m[1],m[0]))>.3)continue;const inl=inliers(m);if(inl.length>best.length)best=inl;}
  if(best.length<12||best.length/pairs.length<.25)throw Error('自动配准置信度不足，请分别标记');
  const m=fit(best),refined=inliers(m),final=fit(refined),xs=refined.map(p=>p[0].x),ys=refined.map(p=>p[0].y);
  if(Math.max(...xs)-Math.min(...xs)<a.w*.3||Math.max(...ys)-Math.min(...ys)<a.h*.3)throw Error('对应点覆盖不足，请分别标记');
  const errs=refined.map(([p,q])=>{const [x,y]=transform(final,p.x,p.y);return Math.hypot(x-q.x,y-q.y);}).sort((x,y)=>x-y);
  return {matrix:final,inliers:refined.length,matches:pairs.length,median:errs[Math.floor(errs.length/2)],...(includePoints?{points:refined.map(([p,q])=>[p.x,p.y,q.x,q.y])}:{})};
}
export function toPixels(m,sourceScale,targetScale){return [m[0]*sourceScale/targetScale,m[1]*sourceScale/targetScale,m[2]/targetScale,m[3]/targetScale];}
export function invert(m){if(m.length===6){const [a,b,x,y,c,d]=m,det=a*d-b*c;if(Math.abs(det)<1e-10)throw Error('无效变换');return [d/det,-b/det,(c*y-d*x)/det,(b*x-a*y)/det,-c/det,a/det];}const [a,b,x,y]=m,d=a*a+b*b;if(d<1e-10)throw Error('无效变换');return [a/d,-b/d,(-a*x-b*y)/d,(b*x-a*y)/d];}
export function transferMask(ops,m,w,h){
  const map=p=>{const [x,y]=transform(m,...p);return [Math.max(0,Math.min(w-1,Math.round(x))),Math.max(0,Math.min(h-1,Math.round(y)))];};
  const scale=Math.hypot(m[0],m[1]);
  return ops.map(o=>{if(o.kind==='rect'){const [x,y]=o.a,[u,v]=o.b;const points=[[x,y],[x,v],[u,y],[u,v]].map(map);return {kind:'rect',a:[Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1]))],b:[Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))]};}return {kind:o.kind,radius:Math.max(1,Math.min(128,Math.round(o.radius*scale))),points:o.points.map(map)};});
}
