// Validate an origin-preserving whole-frame resize using visible correspondence points.
// Do not infer translation or cropping from the image dimensions alone.
export function verifiedFrameResize(points,total,aw,ah,bw,bh){
 if(!Array.isArray(points)||total<40||aw<30||ah<30||bw<30||bh<30)return null;
 const sx=bw/aw,sy=bh/ah;
 if(Math.abs(sx/sy-1)>.04)return null;
 const errors=points.map(([x,y,u,v])=>({x,y,e:Math.hypot((x+.5)*sx-.5-u,(y+.5)*sy-.5-v)}));
 const good=errors.filter(p=>p.e<=2),ordered=errors.map(p=>p.e).sort((a,b)=>a-b);
 if(good.length<40||good.length/total<.65||ordered[Math.floor(ordered.length*.5)]>1.25||ordered[Math.floor(ordered.length*.9)]>3)return null;
 const xs=good.map(p=>p.x),ys=good.map(p=>p.y);
 if(Math.min(...xs)>.15*aw||Math.max(...xs)-Math.min(...xs)<.60*aw||Math.min(...ys)>.15*ah||Math.max(...ys)<.85*ah)return null;
 return {inliers:good.length,matches:total,median:ordered[Math.floor(ordered.length*.5)]};
}
export function frameMatrix(sw,sh,tw,th){
 const a=tw/sw,d=th/sh;return [a,0,(a-1)/2,(d-1)/2,0,d];
}
