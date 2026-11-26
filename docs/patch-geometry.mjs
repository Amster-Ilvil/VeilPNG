// Estimate a small local displacement using visible context only.
export function alignPatchContext(source,reference,w,h,pad){
 if(source.length!==w*h*4||reference.length!==source.length||pad<6||w<=2*pad||h<=2*pad)throw Error('Invalid patch geometry');
 const max=Math.min(10,Math.floor(pad/2)-2),none={data:source,applied:false,dx:0,dy:0,before:null,after:null};
 if(max<1)return none;
 function gray(data){const g=new Float32Array(w*h),out=new Float32Array(w*h);for(let i=0;i<g.length;i++)g[i]=.299*data[4*i]+.587*data[4*i+1]+.114*data[4*i+2];for(let y=1;y<h-1;y++)for(let x=1;x<w-1;x++){const k=y*w+x;out[k]=(g[k-w-1]+g[k-w]+g[k-w+1]+g[k-1]+g[k]+g[k+1]+g[k+w-1]+g[k+w]+g[k+w+1])/9;}return out;}
 const a=gray(source),b=gray(reference),train=[],test=[];
 // All candidates are compared on the same context samples, away from the reference mask.
 for(let y=max+2;y<h-max-2;y+=2)for(let x=max+2;x<w-max-2;x+=2){
  if(x>=pad-2&&x<w-pad+2&&y>=pad-2&&y<h-pad+2)continue;
  ((Math.floor(x/2)+Math.floor(y/2))%3===0?test:train).push(y*w+x);
 }
 if(train.length<60||test.length<30)return none;
 function score(points,dx,dy){let sx=0,sy=0,sxx=0,syy=0,sxy=0;for(const i of points){const u=a[i+dy*w+dx],v=b[i];sx+=u;sy+=v;sxx+=u*u;syy+=v*v;sxy+=u*v;}const n=points.length,xx=sxx-sx*sx/n,yy=syy-sy*sy/n;if(xx/n<25||yy/n<25)return -1;return (sxy-sx*sy/n)/Math.sqrt(xx*yy);}
 let dx=0,dy=0,best=score(train,0,0);
 for(let y=-max;y<=max;y++)for(let x=-max;x<=max;x++){const q=score(train,x,y)-.001*Math.hypot(x,y);if(q>best){best=q;dx=x;dy=y;}}
 const before=score(test,0,0),after=score(test,dx,dy);
 if((!dx&&!dy)||after<.65||after-before<.025)return {...none,before,after:before};
 const data=new Uint8ClampedArray(source.length);
 for(let y=0;y<h;y++)for(let x=0;x<w;x++){const i=(y*w+x)*4,j=(Math.max(0,Math.min(h-1,y+dy))*w+Math.max(0,Math.min(w-1,x+dx)))*4;for(let c=0;c<4;c++)data[i+c]=source[j+c];}
 return {data,applied:true,dx,dy,before,after};
}
