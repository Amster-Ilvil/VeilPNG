import assert from 'node:assert/strict';
import {repairJoinLines} from './join-lines.mjs';

const w=96,h=80,rect=[24,20,71,59],base=new Uint8ClampedArray(w*h*4);
for(let y=0;y<h;y++)for(let x=0;x<w;x++){
 const p=(y*w+x)*4;const edge=x-y>18?60:0;
 base.set([90+Math.floor(x/5)+edge,115+Math.floor(y/5)+edge,140+Math.floor(x/8)+edge,255],p);
}
const damaged=base.slice();
for(let y=25;y<54;y++){let p=(y*w+24)*4;for(let c=0;c<3;c++)damaged[p+c]-=24;}
for(let x=48;x<66;x++){let p=(20*w+x)*4;for(let c=0;c<3;c++)damaged[p+c]+=20;}
const result=repairJoinLines(damaged,w,h,rect);
let before=0,after=0,outside=0,alpha=0,untouched=0;
for(let y=0;y<h;y++)for(let x=0;x<w;x++){
 const p=(y*w+x)*4;
 for(let c=0;c<3;c++){before+=Math.abs(damaged[p+c]-base[p+c]);after+=Math.abs(result.data[p+c]-base[p+c]);}
 const near=((x>=22&&x<=25||x>=70&&x<=73)&&y>=20&&y<=59)||((y>=18&&y<=21||y>=58&&y<=61)&&x>=24&&x<=71);
 if(!near&&[0,1,2].some(c=>damaged[p+c]!==result.data[p+c]))outside++;
 if(result.data[p+3]!==damaged[p+3])alpha++;
 if([0,1,2].every(c=>base[p+c]===damaged[p+c])&&[0,1,2].some(c=>result.data[p+c]!==base[p+c]))untouched++;
}
const gray=base.slice();for(let i=0;i<gray.length;i+=4)gray[i]=gray[i+1]=gray[i+2]=120;
const halo=gray.slice();for(let y=26;y<52;y++)for(let x=70;x<=71;x++){const p=(y*w+x)*4;halo[p]=halo[p+1]=halo[p+2]=92;}
const g=repairJoinLines(halo,w,h,rect);
const crossing=gray.slice();for(let y=0;y<h;y++)for(let x=24;x<w;x++){const p=(y*w+x)*4;crossing[p]=crossing[p+1]=crossing[p+2]=190;}
const checks=[result.changed>0,after<before*.25,outside===0,alpha===0,untouched===0,repairJoinLines(base,w,h,rect).changed===0,repairJoinLines(crossing,w,h,rect).changed===0,repairJoinLines(base,w,h,[0,0,12,12]).changed===0,g.changed===52,g.data.every((v,i)=>v===gray[i])];

assert.ok(checks.every(Boolean),JSON.stringify(checks));console.log('10 join-line tests passed', {before,after,outside,alpha,untouched});
