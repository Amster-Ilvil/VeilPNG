// Bounded adaptive guard + smoothstep; configurable web restoration.
export function restoreBoundary(source,returned,mask,w,h,{maxHalo=16,feather=8,exact=false}={}){
 if(source.length!==w*h*4||returned.length!==source.length||mask.length!==w*h||!Number.isInteger(maxHalo)||!Number.isInteger(feather)||maxHalo<1||maxHalo>24||feather<0||feather>12)throw Error('Invalid boundary input');
 const n=w*h,out=new Uint8ClampedArray(returned),dist=new Uint8Array(n),radius=maxHalo+Math.max(1,feather);dist.fill(radius+1);
 let core=0,l=w,t=h,r=-1,b=-1;
 for(let i=0;i<n;i++)if(mask[i]){dist[i]=0;out.set(source.subarray(i*4,i*4+4),i*4);core++;let x=i%w,y=Math.floor(i/w);l=Math.min(l,x);r=Math.max(r,x);t=Math.min(t,y);b=Math.max(b,y);}
 if(!core||core===n)throw Error('Mask must leave visible context');
 if(exact)return {data:out,core,halo:0,feather:0,changed:0};
 l=Math.max(0,l-radius);t=Math.max(0,t-radius);r=Math.min(w-1,r+radius);b=Math.min(h-1,b+radius);
 // Two-pass chessboard distance transform (linear time, no repeated dilation).
 for(let y=t;y<=b;y++)for(let x=l;x<=r;x++){let i=y*w+x,v=dist[i];if(x>l)v=Math.min(v,dist[i-1]+1);if(y>t){v=Math.min(v,dist[i-w]+1);if(x>l)v=Math.min(v,dist[i-w-1]+1);if(x<r)v=Math.min(v,dist[i-w+1]+1);}dist[i]=v;}
 for(let y=b;y>=t;y--)for(let x=r;x>=l;x--){let i=y*w+x,v=dist[i];if(x<r)v=Math.min(v,dist[i+1]+1);if(y<b){v=Math.min(v,dist[i+w]+1);if(x>l)v=Math.min(v,dist[i+w-1]+1);if(x<r)v=Math.min(v,dist[i+w+1]+1);}dist[i]=v;}
 const diff=i=>Math.max(Math.abs(source[i*4]-returned[i*4]),Math.abs(source[i*4+1]-returned[i*4+1]),Math.abs(source[i*4+2]-returned[i*4+2]));
 const hist=new Uint32Array(256);let count=0;
 for(let y=t;y<=b;y++)for(let x=l;x<=r;x++){let i=y*w+x,d=dist[i];if(d>maxHalo&&d<=radius){hist[diff(i)]++;count++;}}
 let noise=0,s=0;for(let k=0;k<256;k++){s+=hist[k];if(s>count/2){noise=k;break;}}
 const threshold=Math.max(8,noise+6),tot=new Uint32Array(maxHalo+1),hits=new Uint32Array(maxHalo+1);
 for(let y=t;y<=b;y++)for(let x=l;x<=r;x++){let i=y*w+x,d=dist[i];if(d&&d<=maxHalo){tot[d]++;if(diff(i)>=threshold)hits[d]++;}}
 const rates=Array.from(tot,(v,i)=>v?hits[i]/v:0);let guard=0;
 if(noise>=8||rates.slice(1,5).some(v=>v>=.03)){guard=Math.min(4,maxHalo);for(let d=1;d<=maxHalo;d++)if(rates[d]>=.03)guard=Math.max(guard,d);}
 let changed=0;if(guard)for(let y=t;y<=b;y++)for(let x=l;x<=r;x++){let i=y*w+x,d=dist[i];if(!d||d>guard+feather)continue;let z=feather?Math.max(0,Math.min(1,(d-guard)/feather)):0,v=1-z*z*(3-2*z),p=i*4,any=false;for(let c=0;c<4;c++){out[p+c]=Math.round(source[p+c]*v+returned[p+c]*(1-v));any||=out[p+c]!==returned[p+c];}if(any)changed++;}
 return {data:out,core,halo:guard,feather:guard?feather:0,changed,noise,warning:guard===maxHalo};
}

// Final write-domain guard: keep the returned image byte-for-byte outside the mapped mask.
export function preserveOutsideMask(candidate,returned,mask){
 if(candidate.length!==returned.length||candidate.length!==mask.length*4)throw Error('Invalid protection mask');
 let blocked=0;for(let i=0;i<mask.length;i++){if(mask[i])continue;const p=i*4;if(candidate[p]!==returned[p]||candidate[p+1]!==returned[p+1]||candidate[p+2]!==returned[p+2]||candidate[p+3]!==returned[p+3]){candidate.set(returned.subarray(p,p+4),p);blocked++;}}
 return blocked;
}

 // Normalize controls, including a smaller patch-local context budget.
 export function boundaryOptions(enabled,halo,fade,pad=Infinity){
  const integer=(v,min,max,def)=>{const n=String(v).trim()===''?NaN:Number(v);return Number.isFinite(n)?Math.max(min,Math.min(max,Math.round(n))):def;};
  const maxHalo=Math.min(integer(halo,1,16,4),Math.max(1,pad));
  const feather=Math.min(integer(fade,0,8,2),Math.max(0,pad-maxHalo));
  return {maxHalo,feather,exact:!enabled};
 }
 // A local rectangle fit may disagree with the global projected selection.
 // Never let that fit write farther than the user-selected total exterior budget.
 export function boundedWriteMask(mask,w,h,radius){
  if(mask.length!==w*h||!Number.isInteger(radius)||radius<0||radius>24)throw Error('Invalid write radius');
  if(!radius)return mask;
  const dist=new Uint8Array(mask.length);dist.fill(radius+1);
  for(let y=0;y<h;y++)for(let x=0;x<w;x++){
   const i=y*w+x;if(mask[i]){dist[i]=0;continue;}
   let v=dist[i];if(x)v=Math.min(v,dist[i-1]+1);
   if(y){v=Math.min(v,dist[i-w]+1);if(x)v=Math.min(v,dist[i-w-1]+1);if(x+1<w)v=Math.min(v,dist[i-w+1]+1);}dist[i]=v;
  }
  for(let y=h-1;y>=0;y--)for(let x=w-1;x>=0;x--){
   const i=y*w+x;let v=dist[i];if(x+1<w)v=Math.min(v,dist[i+1]+1);
   if(y+1<h){v=Math.min(v,dist[i+w]+1);if(x)v=Math.min(v,dist[i+w-1]+1);if(x+1<w)v=Math.min(v,dist[i+w+1]+1);}dist[i]=v;
  }
  for(let i=0;i<dist.length;i++)dist[i]=dist[i]<=radius?1:0;
  return dist;
 }
