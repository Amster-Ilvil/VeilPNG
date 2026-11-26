export function webpDimensions(raw){
 const v=new DataView(raw.buffer,raw.byteOffset,raw.byteLength),tag=i=>String.fromCharCode(...raw.subarray(i,i+4));
 if(raw.length<20||tag(0)!=='RIFF'||tag(8)!=='WEBP'||v.getUint32(4,true)+8!==raw.length)throw Error('WebP 文件不完整');
 let w=0,h=0,xw=0,xh=0,found=0,i=12;
 const u24=j=>raw[j]+256*raw[j+1]+65536*raw[j+2];
 while(i+8<=raw.length){
 const t=tag(i),n=v.getUint32(i+4,true),p=i+8,end=p+n+(n&1);
 if(end>raw.length)throw Error('WebP 数据不完整');
 if(t==='ANIM'||t==='ANMF')throw Error('不支持动画 WebP');
 if(t==='VP8X'){if(n!==10||raw[p]&2)throw Error('不支持动画或无效 WebP');xw=1+u24(p+4);xh=1+u24(p+7);}
 if(t==='VP8 '){if(n<10||raw[p]&1||raw[p+3]!==157||raw[p+4]!==1||raw[p+5]!==42)throw Error('无效 WebP VP8');w=v.getUint16(p+6,true)&16383;h=v.getUint16(p+8,true)&16383;found++;}
 if(t==='VP8L'){if(n<5||raw[p]!==47)throw Error('无效 WebP VP8L');const bits=v.getUint32(p+1,true);w=(bits&16383)+1;h=((bits>>>14)&16383)+1;found++;}
 i=end;
 }
 if(i!==raw.length||found!==1||!w||!h||(xw&&(xw!==w||xh!==h))||w>12000||h>12000||w*h>12000000)throw Error('WebP 尺寸超限或数据无效');
 return {width:w,height:h};
}
