// Context-only, bounded color correction for local image patches.
// The reference interior is never sampled. The caller copies back only the requested rectangle.
export function matchPatchTone(source,reference,w,h,pad,fullContext=false){
 if(source.length!==w*h*4||reference.length!==source.length||!Number.isInteger(pad)||pad<6||w<=2*pad||h<=2*pad)throw Error('Invalid patch context');
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 const mid=a=>{const s=[...a].sort((x,y)=>x-y);return s[Math.floor(s.length/2)];};
 const train=[],test=[];
 for(let y=2;y<h-2;y+=3)for(let x=2;x<w-2;x+=3){
  if(x>=pad-3&&x<w-pad+3&&y>=pad-3&&y<h-pad+3)continue;
  const a=[0,0,0],b=[0,0,0];let amin=255,amax=0,bmin=255,bmax=0;
  for(let j=-2;j<=2;j++)for(let i=-2;i<=2;i++){
   const k=((y+j)*w+x+i)*4;for(let c=0;c<3;c++){a[c]+=source[k+c];b[c]+=reference[k+c];}
   const u=(source[k]+source[k+1]+source[k+2])/3,v=(reference[k]+reference[k+1]+reference[k+2])/3;
   amin=Math.min(amin,u);amax=Math.max(amax,u);bmin=Math.min(bmin,v);bmax=Math.max(bmax,v);
  }
  if(amax-amin>55||bmax-bmin>55)continue;
  for(let c=0;c<3;c++){a[c]/=25;b[c]/=25;}
  if(Math.min(...a,...b)<24)continue;
  ((Math.floor(x/3)+Math.floor(y/3))%3===0?test:train).push([a,b]);
 }
 const identity={data:source,applied:false,samples:train.length+test.length,before:null,after:null};
 if(train.length<24||test.length<8)return identity;
 function fit(rows,c){
  const delta=mid(rows.map(([a,b])=>b[c]-a[c]));
  const clean=rows.filter(([a,b])=>Math.abs(b[c]-a[c]-delta)<=38);
  if(clean.length<16)return [1,0];
  let x=0,y=0;for(const [a,b] of clean){x+=a[c];y+=b[c];}x/=clean.length;y/=clean.length;
  let xx=0,xy=0;for(const [a,b] of clean){xx+=(a[c]-x)**2;xy+=(a[c]-x)*(b[c]-y);}
  const slope=xx/clean.length<100?1:clamp(xy/xx,.7,1.35);
  return [slope,clamp(y-slope*x,-55,55)];
 }
 const params=[0,1,2].map(c=>fit(train,c));
 const corrected=(v,c)=>{const [a,b]=params[c],gate=clamp((v-12)/48,0,1);return clamp(v+gate*clamp(a*v+b-v,-55,55),0,255);};
 let before=0,after=0;for(const [a,b] of test)for(let c=0;c<3;c++){before+=Math.abs(a[c]-b[c]);after+=Math.abs(corrected(a[c],c)-b[c]);}
 before/=test.length*3;after/=test.length*3;
 if(before<1||after>before*.94)return {...identity,before,after:before};
 const data=new Uint8ClampedArray(source);
 for(let y=fullContext?0:pad;y<(fullContext?h:h-pad);y++)for(let x=fullContext?0:pad;x<(fullContext?w:w-pad);x++){const k=(y*w+x)*4;for(let c=0;c<3;c++)data[k+c]=Math.round(corrected(data[k+c],c));}
 return {data,applied:true,samples:train.length+test.length,before,after};
}
