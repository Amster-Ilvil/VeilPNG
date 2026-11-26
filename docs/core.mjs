function maskFor(w,h,ops){
  const m=new Uint8Array(w*h);
  const put=(x,y,r,v)=>{const y0=Math.max(0,Math.ceil(y-r)),y1=Math.min(h-1,Math.floor(y+r));for(let j=y0;j<=y1;j++){const dx=Math.sqrt(Math.max(0,r*r-(j-y)*(j-y)));const a=Math.max(0,Math.ceil(x-dx)),b=Math.min(w-1,Math.floor(x+dx));if(b>=a)m.fill(v,j*w+a,j*w+b+1);}};
  for(const o of ops){
    if(o.kind==="rect"){const x0=Math.max(0,Math.min(o.a[0],o.b[0])),x1=Math.min(w-1,Math.max(o.a[0],o.b[0])),y0=Math.max(0,Math.min(o.a[1],o.b[1])),y1=Math.min(h-1,Math.max(o.a[1],o.b[1]));for(let y=y0;y<=y1;y++)if(x1>=x0)m.fill(1,y*w+x0,y*w+x1+1);}
    else{const v=o.kind==="erase"?0:1,r=o.radius;for(let i=0;i<o.points.length;i++){const b=o.points[i],a=o.points[Math.max(0,i-1)],n=Math.max(1,Math.ceil(Math.hypot(b[0]-a[0],b[1]-a[1])/Math.max(1,r/2)));for(let j=0;j<=n;j++)put(a[0]+(b[0]-a[0])*j/n,a[1]+(b[1]-a[1])*j/n,r,v);}}
  }return m;
}

function redactRGBA(data,mask,shade){
  if(data.length!==mask.length*4)throw Error("Invalid pixel buffer");
  let count=0;
  for(let i=0;i<mask.length;i++){if(!mask[i])continue;const p=i*4;data[p]=shade;data[p+1]=shade;data[p+2]=shade;data[p+3]=255;count++;}
  return count;
}

function crc32(bytes){let c=0xffffffff;for(const b of bytes){c^=b;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xedb88320:0);}return(c^0xffffffff)>>>0;}

function zipStore(entries){
  const chunks=[],central=[],seen=new Set();let offset=0,cs=0;
  for(const e of entries){
    const name=Uint8Array.from(e.name,c=>c.charCodeAt(0));const data=e.data;
    if(!/^[0-9]{4}_(?:redacted|restored)\.png$/.test(e.name)||seen.has(e.name))throw Error("Invalid or duplicate output filename");seen.add(e.name);
    const crc=crc32(data),a=new Uint8Array(30+name.length),v=new DataView(a.buffer);
    v.setUint32(0,0x04034b50,true);v.setUint16(4,20,true);v.setUint16(12,33,true);v.setUint32(14,crc,true);v.setUint32(18,data.length,true);v.setUint32(22,data.length,true);v.setUint16(26,name.length,true);a.set(name,30);
    const b=new Uint8Array(46+name.length),z=new DataView(b.buffer);
    z.setUint32(0,0x02014b50,true);z.setUint16(4,20,true);z.setUint16(6,20,true);z.setUint16(14,33,true);z.setUint32(16,crc,true);z.setUint32(20,data.length,true);z.setUint32(24,data.length,true);z.setUint16(28,name.length,true);z.setUint32(42,offset,true);b.set(name,46);
    chunks.push(a,data);central.push(b);offset+=a.length+data.length;cs+=b.length;
  }
  if(offset+cs>0xffffffff||entries.length>65535)throw Error("ZIP too large");
  const end=new Uint8Array(22),v=new DataView(end.buffer);v.setUint32(0,0x06054b50,true);v.setUint16(8,entries.length,true);v.setUint16(10,entries.length,true);v.setUint32(12,cs,true);v.setUint32(16,offset,true);
  return [...chunks,...central,end];
}
export {maskFor,redactRGBA,crc32,zipStore};
