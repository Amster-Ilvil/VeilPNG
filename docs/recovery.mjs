import {transform,invert} from './registration.mjs';
export function projectedMask(mask,sw,sh,tw,th,m){
 if(mask.length!==sw*sh||!m.every(Number.isFinite))throw Error('无效遮盖映射');
 let n=0,clipped=0;for(let y=0;y<sh;y++)for(let x=0;x<sw;x++)if(mask[y*sw+x]){n++;const [u,v]=transform(m,x,y);if(u<0||v<0||u>tw-1||v>th-1)clipped++;}
 if(!n||clipped)throw Error('遮盖区域超出回传图边界，拒绝恢复');
 const inv=invert(m),out=new Uint8Array(tw*th);let count=0;
 for(let y=0;y<th;y++)for(let x=0;x<tw;x++){const sx=Math.round(inv[0]*x-inv[1]*y+inv[2]),sy=Math.round(inv[1]*x+inv[0]*y+inv[3]);if(sx>=0&&sy>=0&&sx<sw&&sy<sh&&mask[sy*sw+sx]){out[y*tw+x]=1;count++;}}
 if(!count)throw Error('映射后遮盖为空');return out;
}
export function recoverRectangles(original,redacted,w,h){
 if(original.length!==w*h*4||redacted.length!==original.length)throw Error('图像尺寸不同');
 let shade=null;const runs=[];let current=null;
 for(let y=0;y<h;y++){let lo=w,hi=-1;for(let x=0;x<w;x++){const p=(y*w+x)*4;let diff=0;for(let c=0;c<3;c++)diff=Math.max(diff,Math.abs(original[p+c]-redacted[p+c]));if(diff<=4)continue;
 const v=redacted[p];if((v!==0&&v!==255)||redacted[p+1]!==v||redacted[p+2]!==v||redacted[p+3]!==255)throw Error('非纯色遮盖差异');if(shade!==null&&shade!==v)throw Error('混合遮盖颜色');shade=v;lo=Math.min(lo,x);hi=Math.max(hi,x);}
 if(hi>=lo){if(!current)current={kind:'rect',a:[lo,y],b:[hi,y]};else{current.a[0]=Math.min(current.a[0],lo);current.b[0]=Math.max(current.b[0],hi);current.b[1]=y;}}else if(current){runs.push(current);current=null;}}
 if(current)runs.push(current);if(!runs.length||runs.length>128)throw Error('无法识别矩形遮盖');
 for(const r of runs)for(let y=r.a[1];y<=r.b[1];y++)for(let x=r.a[0];x<=r.b[0];x++){const p=(y*w+x)*4;if(redacted[p]!==shade||redacted[p+1]!==shade||redacted[p+2]!==shade||redacted[p+3]!==255)throw Error('非矩形或多个同排选区，请手动标记');}
 return {ops:runs,shade};
}
export function chooseMatch(candidates){
 const ranked=candidates.filter(r=>r.inliers>=20&&r.inliers/r.matches>=.35).sort((a,b)=>b.inliers-a.inliers);
 if(!ranked.length)throw Error('没有可靠匹配，请逐页导入');
 if(ranked.length>1&&ranked[0].inliers<ranked[1].inliers*1.18)throw Error('存在多个近似匹配，请指定中日分组或逐页导入');
 return ranked[0];
}
