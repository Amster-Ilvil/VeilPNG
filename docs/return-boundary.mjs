// Bounded adaptive guard + smoothstep, shared specification with veilpng/return_restore.py.
export function restoreBoundary(source,returned,mask,w,h,{maxHalo=16,feather=8,exact=false}={}){
 if(source.length!==w*h*4||returned.length!==source.length||mask.length!==w*h||maxHalo<2||maxHalo>24||feather<1||feather>12)throw Error('Invalid boundary input');
 const n=w*h,out=new Uint8ClampedArray(returned),dist=new Uint8Array(n),radius=maxHalo+feather;dist.fill(radius+1);
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
 if(noise>=8||rates.slice(1,5).some(v=>v>=.03)){guard=4;for(let d=1;d<=maxHalo;d++)if(rates[d]>=.03)guard=Math.max(guard,d);}
 let changed=0;if(guard)for(let y=t;y<=b;y++)for(let x=l;x<=r;x++){let i=y*w+x,d=dist[i];if(!d||d>=guard+feather)continue;let z=Math.max(0,Math.min(1,(d-guard)/feather)),v=1-z*z*(3-2*z),p=i*4,any=false;for(let c=0;c<4;c++){out[p+c]=Math.round(source[p+c]*v+returned[p+c]*(1-v));any||=out[p+c]!==returned[p+c];}if(any)changed++;}
 return {data:out,core,halo:guard,feather:guard?feather:0,changed,noise,warning:guard===maxHalo};
}
