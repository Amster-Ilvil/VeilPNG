import {verifyReturnGrid,scaledMatrix,returnDecision} from "./return-match.mjs?v=0.9.8";
import {exportFilename,matchesExportName} from "./naming.mjs?v=0.9.8";
import {maskFor,redactRGBA,zipStore} from "./core.mjs?v=0.9.8";
import {sourceHash,maskRecord,loadMaskRecord,restoreRGBA} from "./return-core.mjs?v=0.9.8";
import {pairIsCurrent,pairIsApproved,attachPair,invalidatePair,setPairApproval,reviewedPages} from "./pairing.mjs?v=0.9.8";
import {projectRecord,matchProject,validRole,checkpoint} from "./project.mjs?v=0.9.8";
import {registerGray,toPixels,invert,transform,transferMask} from "./registration.mjs?v=0.9.8";
import {projectedMask,recoverRectangles,chooseMatch} from "./recovery.mjs?v=0.9.8";
import {readPublicZip} from "./zip-read.mjs?v=0.9.8";
import {bilingual,opposite,makeLink,linkFor,other,mappedOp,snapshot,applySnapshot,exportPlan,hasMask} from "./bilingual.mjs?v=0.9.8";
import {workspaceRecord,restoreLinks,makePrivateBundle,unpackPrivateBundle,roleFromPublicName} from "./workspace.mjs?v=0.9.8";
import {webpDimensions} from "./webp.mjs?v=0.9.8";
import {rectanglePlan} from "./local-rect.mjs?v=0.9.8";
import {matchPatchTone} from "./tone.mjs?v=0.9.8";
import {alignPatchContext} from "./patch-geometry.mjs?v=0.9.8";
import {restoreBoundary} from "./return-boundary.mjs?v=0.9.8";
import {preferPairedReference} from "./paired-reference.mjs?v=0.9.8";

import {verifiedOriginal} from "./original-export.mjs?v=0.9.8";
const $=id=>document.getElementById(id);
const ui={files:$("files"),queue:$("queue"),preview:$("preview"),gesture:$("gesture"),stack:$("stack"),empty:$("empty"),status:$("status"),tool:$("tool"),radius:$("radius"),shade:$("shade"),undo:$("undo"),redo:$("redo"),clearMask:$("clearMask"),clearAll:$("clearAll"),exportOne:$("exportOne"),exportAll:$("exportAll")};
const LIMIT=12_000_000,MAX=20*1024*1024,TOTAL=80*1024*1024;
let pages=[],index=-1,bitmap=null,busy=false,drag=null,count=0;
let restoredBlob=null,restoredURL=null,returnedURL=null,compareWidth=0;
let alignment=null,links=[],partnerGeneration=0;
const current=()=>pages[index];
const marked=p=>p&&p.ops.length>0;
function status(t){ui.status.textContent=t;$("actionStatus").textContent=t;}
function controls(){
  const p=current();for(const x of [ui.files,ui.clearAll,ui.tool,ui.radius,ui.shade])x.disabled=busy;
  ui.undo.disabled=busy||!p||!p.ops.length;ui.redo.disabled=busy||!p||!p.redo.length;ui.clearMask.disabled=busy||!p||!p.ops.length;
  ui.exportOne.disabled=busy||!p||count===0||bilingual(p);ui.exportAll.disabled=busy||!pages.some(marked);
  syncReturnControls();syncProjectControls();syncEasyControls();syncDualControls();
  ui.queue.replaceChildren();
  pages.forEach((q,i)=>{const li=document.createElement("li"),b=document.createElement("button");b.type="button";b.textContent=(pairIsApproved(q)?"✓ ":pairIsCurrent(q)?"◐ ":marked(q)?"● ":"○ ")+"["+validRole(q.role)+"] "+q.file.name;b.disabled=busy;b.setAttribute("aria-current",String(i===index));b.onclick=()=>run(()=>select(i));li.append(b);ui.queue.append(li);});
}
async function run(fn){if(busy)return;busy=true;drag=null;controls();try{await fn();}catch(e){status("操作失败："+String(e.message||e));}finally{busy=false;controls();}}
async function decode(file){
  if(file.size>MAX)throw Error("文件超过 20 MB");
  const sig=new Uint8Array(await file.slice(0,24).arrayBuffer());
  const png=sig.length>=24&&[137,80,78,71,13,10,26,10].every((x,i)=>sig[i]===x);
  const jpg=sig.length>=3&&sig[0]===255&&sig[1]===216&&sig[2]===255;
  const webp=sig.length>=12&&String.fromCharCode(...sig.slice(0,4))==="RIFF"&&String.fromCharCode(...sig.slice(8,12))==="WEBP";
  if(!png&&!jpg&&!webp)throw Error("仅支持真实 PNG/JPEG/WebP");
  if(webp)webpDimensions(new Uint8Array(await file.arrayBuffer()));
  if(png){const d=new DataView(sig.buffer);const w=d.getUint32(16),h=d.getUint32(20);if(!w||!h||w*h>LIMIT||w>12000||h>12000)throw Error("PNG 尺寸超限");
    const raw=new Uint8Array(await file.arrayBuffer()),v=new DataView(raw.buffer);let i=8;
    while(i+12<=raw.length){const n=v.getUint32(i);if(n>raw.length-i-12)throw Error("PNG 数据不完整");if(raw[i+4]===97&&raw[i+5]===99&&raw[i+6]===84&&raw[i+7]===76)throw Error("不支持动画 PNG");i+=n+12;}
  }
  if(jpg){const raw=new Uint8Array(await file.arrayBuffer()),v=new DataView(raw.buffer);let i=2,found=false;while(i+4<=raw.length&&raw[i]===255){while(raw[i]===255)i++;const k=raw[i++];if(k===218||k===217)break;if(k===1||(k>=208&&k<=215))continue;if(i+2>raw.length)break;const n=v.getUint16(i);if(n<2||i+n>raw.length)break;if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(k)){if(n<8)break;const h=v.getUint16(i+3),w=v.getUint16(i+5);if(!w||!h||w*h>LIMIT||w>12000||h>12000)throw Error("JPEG 尺寸超限");found=true;break;}i+=n;}if(!found)throw Error("无法读取 JPEG 尺寸");}
  const b=await createImageBitmap(file);
  if(!b.width||!b.height||b.width*b.height>LIMIT||b.width>12000||b.height>12000){b.close();throw Error("图片尺寸超限");}return b;
}
function draw(b,p,c){
  c.width=b.width;c.height=b.height;const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
  x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.drawImage(b,0,0);
  const mask=maskFor(c.width,c.height,p.ops),im=x.getImageData(0,0,c.width,c.height);
  const n=redactRGBA(im.data,mask,p.shade);x.putImageData(im,0,0);return n;
}
function fitCanvas(){if(!bitmap)return;const w=Math.max(1,ui.stack.parentElement.clientWidth-24),h=Math.max(1,Math.floor(window.innerHeight*(window.innerWidth<=720?0.56:0.64)));const scale=Math.min(1,w/bitmap.width,h/bitmap.height);ui.stack.style.width=Math.max(1,Math.floor(bitmap.width*scale))+"px";ui.stack.style.height=Math.max(1,Math.floor(bitmap.height*scale))+"px";}
window.addEventListener("resize",fitCanvas);
function render(){clearRestored();const p=current();if(!p||!bitmap)return;count=draw(bitmap,p,ui.preview);ui.gesture.width=bitmap.width;ui.gesture.height=bitmap.height;ui.gesture.getContext("2d").clearRect(0,0,bitmap.width,bitmap.height);
  ui.shade.value=String(p.shade);ui.stack.hidden=false;ui.empty.hidden=true;refreshPartner();fitCanvas();status((index+1)+"/"+pages.length+" · "+bitmap.width+" × "+bitmap.height+" · 已遮盖 "+count+" 像素");controls();}
async function select(i){clearAlignment();const b=await decode(pages[i].file);if(bitmap)bitmap.close();bitmap=b;index=i;render();const p=current();if(pairIsCurrent(p)){try{await showPair(p);}catch(e){invalidatePair(p);throw e;}}}
ui.files.onchange=()=>{const incoming=Array.from(ui.files.files);ui.files.value="";run(async()=>{if(!incoming.length)return;if(pages.length+incoming.length>32||pages.reduce((s,p)=>s+p.file.size,0)+incoming.reduce((s,f)=>s+f.size,0)>TOTAL)throw Error("队列超过容量限制");for(const f of incoming){if(f.size>MAX)throw Error("单文件超过 20 MB");}const staged=[];for(const f of incoming){staged.push(await newPage(f,$("importRole").value));}const old=pages.length;pages.push(...staged);await select(old);markDirty();});};
function point(e){const r=ui.gesture.getBoundingClientRect();return [Math.max(0,Math.min(ui.gesture.width-1,Math.floor((e.clientX-r.left)*ui.gesture.width/r.width))),Math.max(0,Math.min(ui.gesture.height-1,Math.floor((e.clientY-r.top)*ui.gesture.height/r.height)))];}
function guide(){const c=ui.gesture,x=c.getContext("2d");x.clearRect(0,0,c.width,c.height);if(!drag)return;const d=drag;x.strokeStyle="#e84a5f";x.fillStyle="#e84a5f";x.globalAlpha=.65;if(d.kind==="rect"){x.lineWidth=Math.max(2,c.width/500);x.strokeRect(d.a[0],d.a[1],d.b[0]-d.a[0],d.b[1]-d.a[1]);}else{x.lineWidth=d.radius*2;x.lineCap="round";x.lineJoin="round";x.beginPath();x.moveTo(...d.points[0]);for(const p of d.points)x.lineTo(...p);x.stroke();x.beginPath();x.arc(...d.points[0],d.radius,0,Math.PI*2);x.fill();}x.globalAlpha=1;}
ui.gesture.onpointerdown=e=>{if(busy||!current()||drag||e.button!==0)return;e.preventDefault();const p=point(e),kind=ui.tool.value;drag=kind==="rect"?{kind,a:p,b:p}:{kind,radius:Math.max(1,Math.min(128,Math.round(Number(ui.radius.value)||12))),points:[p]};ui.gesture.setPointerCapture(e.pointerId);guide();};
ui.gesture.onpointermove=e=>{if(!drag||busy)return;const p=point(e);if(drag.kind==="rect")drag.b=p;else if(drag.points.length<2048){const q=drag.points.at(-1);if(q[0]!==p[0]||q[1]!==p[1])drag.points.push(p);}guide();};
ui.gesture.onpointerup=e=>{if(!drag||busy)return;const d=drag;drag=null;const p=point(e);if(d.kind==="rect")d.b=p;else if(d.points.length<2048)d.points.push(p);const q=current();if(q.ops.length>=128){guide();status("每页最多 128 次选区操作，请清空或撤销后再编辑。");return;}try{editLinked((p,q,l)=>{if(q){if(q.ops.length>=128)throw Error("对应页选区已达上限");q.ops.push(mappedOp(l,p,d));}p.ops.push(d);});}catch(e){guide();status(e.message);}};
ui.gesture.onpointercancel=()=>{drag=null;guide();};
ui.undo.onclick=()=>{const l=linkFor(links,current());if(l){if(l.undo.length){l.redo.push(snapshot(l));applySnapshot(l,l.undo.pop());afterLinked(l);}return;}if(current()?.ops.length){current().redo.push(current().ops.pop());invalidatePair(current());render();markDirty();}};
ui.redo.onclick=()=>{const l=linkFor(links,current());if(l){if(l.redo.length){l.undo.push(snapshot(l));applySnapshot(l,l.redo.pop());afterLinked(l);}return;}if(current()?.redo.length){current().ops.push(current().redo.pop());invalidatePair(current());render();markDirty();}};
ui.clearMask.onclick=()=>{if(current()&&confirm("清空当前选区？同步开启时清空两侧。"))editLinked((p,q)=>{p.ops=[];if(q)q.ops=[];});};
ui.shade.onchange=()=>{if(current())editLinked((p,q)=>{p.shade=Number(ui.shade.value);if(q)q.shade=p.shade;});};
ui.clearAll.onclick=()=>{if(!pages.length||confirm("清空全部图片和选区？")){if(bitmap)bitmap.close();bitmap=null;clearRestored();clearAlignment();links=[];pages=[];refreshPartner();index=-1;count=0;drag=null;ui.stack.hidden=true;ui.empty.hidden=false;for(const c of [ui.preview,ui.gesture]){c.width=1;c.height=1;}status("尚未导入图片");controls();markDirty();}};
function png(c){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(Error("PNG 编码失败")),"image/png"));}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}

async function exportPage(p){const b=await decode(p.file),c=document.createElement("canvas");try{if(!draw(b,p,c))return null;return await png(c);}finally{b.close();c.width=1;c.height=1;}}
ui.exportOne.onclick=()=>run(async()=>{if(bilingual(current()))throw Error("中日图片请一起导出 ZIP");if($("autosave").checked)await flushCheckpoint();else if(!confirm("确认已保存项目记录并保留原图？"))return;const b=await exportPage(current());if(!b)throw Error("选区为空");download(b,exportFilename(pages,index,"redacted"));status("当前 PNG 已生成");});
ui.exportAll.onclick=()=>run(async()=>{
 const plan=exportPlan(pages,links);
 if($("autosave").checked)await flushCheckpoint();else if(savedRevision!==revision){if(!confirm("同时下载私人完整工程 ZIP 和公开中日 ZIP？私人包包含原图，仅供本地恢复，请勿外传。"))return;await saveProjectRecord();}
 const entries=[];let size=0;
 for(const {page,name:filename} of plan){status("正在编码 "+filename);const b=await exportPage(page);if(!b)throw Error("选区失效，整批取消");size+=b.size;if(size>128*1024*1024)throw Error("导出超过 128 MB，请分批处理");entries.push({name:filename,data:new Uint8Array(await b.arrayBuffer())});}
 download(new Blob(zipStore(entries),{type:"application/zip"}),"veilpng_CN_JP_redacted.zip");status("已生成一个公开 ZIP，包含 "+entries.length+" 张遮盖 PNG；私人完整工程单独保存。");
});

function syncReturnControls(){
  $("saveRecord").disabled=busy||!current()||count===0;
  $("loadRecord").disabled=busy||!current();
  $("loadReturn").disabled=busy||!current()||count===0;
  const reviewed=reviewedPages(pages).length;
  $("exportRestored").disabled=busy||!restoredBlob||!pairIsCurrent(current())||!current()?.pair?.composed;
  $("exportBatch").disabled=busy||!reviewed;
  $("approvePair").disabled=busy||!restoredBlob||!pairIsCurrent(current());
  $("approvePair").checked=pairIsApproved(current());
  $("removePair").disabled=busy||!pairIsCurrent(current());
  $("compareZoom").disabled=busy||!pairIsCurrent(current());
  $("pairedReference").disabled=busy;$("fringeCleanup").disabled=busy;
  $("restoreCurrent").disabled=busy||!pairIsCurrent(current());
  $("restoreAll").disabled=busy||!pages.some(pairIsCurrent);
  $("pairSummary").textContent="已导入 "+pages.filter(pairIsCurrent).length+" 页 · 已恢复 "+pages.filter(p=>pairIsCurrent(p)&&p.pair.composed).length+" 页 · 已确认 "+reviewed+" 页（仅导出已确认页面）";
}
function clearRestored(){
  restoredBlob=null;
  if(restoredURL)URL.revokeObjectURL(restoredURL);
  restoredURL=null;if(returnedURL)URL.revokeObjectURL(returnedURL);returnedURL=null;compareWidth=0;
  $("restoredImage").removeAttribute("src");$("restoredImage").hidden=true;$("restoreWaiting").hidden=false;$("returnedImage").removeAttribute("src");$("returnPreview").hidden=true;
}
$("saveRecord").onclick=()=>run(async()=>{
  const p=current();if(!p||!bitmap||!count)throw Error("没有有效遮盖选区");
  const r=maskRecord(bitmap.width,bitmap.height,await sourceHash(p.file),p.ops,p.shade);
  download(new Blob([JSON.stringify(r)],{type:"application/json"}),exportFilename(pages,index,"local_mask"));
  status("遮盖记录已生成：仅本地保存，不要与公开预览一同上传。");
});
$("loadRecord").onclick=()=>$("recordFile").click();
$("recordFile").onchange=()=>{const f=$("recordFile").files[0];$("recordFile").value="";if(!f)return;run(async()=>{
  if(f.size>6000000)throw Error("遮盖记录超限");
  const p=current();if(!p||!bitmap)throw Error("请先导入原图");
  const r=loadMaskRecord(await f.text(),bitmap.width,bitmap.height,await sourceHash(p.file));
  if(p.ops.length&&!confirm("替换当前页遮盖记录？"))return;
  p.ops=r.ops;p.shade=r.shade;p.redo=[];invalidatePair(p);invalidateLinkReview(p);render();markDirty();status("遮盖记录已恢复，原图 SHA-256 匹配。");
});};
function rgbaOf(b){
 const c=document.createElement("canvas");c.width=b.width;c.height=b.height;const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
 try{x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.drawImage(b,0,0);return x.getImageData(0,0,c.width,c.height);}finally{c.width=c.height=1;}
}
function matchPublic(p,source,b){
 const c=document.createElement("canvas");try{
   if(!draw(source,p,c))throw Error("没有有效遮盖");
   if(c.width===b.width&&c.height===b.height){
     const a=c.getContext("2d").getImageData(0,0,c.width,c.height).data,t=rgbaOf(b).data;
     if(a.every((v,i)=>v===t[i]))return {matrix:[1,0,0,0],inliers:100000,matches:100000,pixelMedian:0,gridVerified:true};
     // Check visible context on the exact grid, without letting the mask's
     // artificial black/white edge dominate feature matching.
     const mask=maskFor(c.width,c.height,p.ops),w=c.width,h=c.height;
     let total=0,good=0,texture=0,textureGood=0;
     for(let y=16;y<h-16;y+=4)for(let x=16;x<w-16;x+=4){let i=y*w+x;if(mask[i]||mask[i-16*w-16]||mask[i-16*w+16]||mask[i+16*w-16]||mask[i+16*w+16])continue;
       let k=i*4,d=Math.max(Math.abs(a[k]-t[k]),Math.abs(a[k+1]-t[k+1]),Math.abs(a[k+2]-t[k+2]));total++;if(d<=24)good++;
       if(Math.abs(a[k]-a[k+4])+Math.abs(a[k]-a[k+4*w])>22){texture++;if(d<=24)textureGood++;}
     }
     if(total>=64&&good/total>=.90&&texture>=20&&textureGood/texture>=.85)return {matrix:[1,0,0,0],inliers:good,matches:total,pixelMedian:0,gridVerified:true};
   }
   let registered=null,registrationError=null;
   try{registered=registerImages(c,b);if(registered.inliers>=20&&registered.inliers/registered.matches>=.35)return registered;}catch(e){registrationError=e;}
   // Gemini may resize or lightly redraw a page, leaving too few corner features.
   // Accept a full-page scale only after independent texture/context verification.
   const m=scaledMatrix(c.width,c.height,b.width,b.height);
   if(m){
     const a=grayThumbnail(c),t=grayThumbnail(b,a.w,a.h);
     const mask=maskFor(c.width,c.height,p.ops);
     const verified=verifyReturnGrid(a.data,t.data,mask,a.w,a.h,c.width,c.height);
     if(verified){projectedMask(mask,c.width,c.height,b.width,b.height,m);return {...verified,matrix:m,pixelMedian:0,gridVerified:c.width===b.width&&c.height===b.height};}
   }
   if(registered)return registered;
   throw registrationError||Error("无法验证返回图与原图的画面对应关系");
 }finally{c.width=c.height=1;}
}
async function composeUsingSource(p,source,returnedFile){
 const b=await decode(returnedFile),c=document.createElement("canvas");
 try{
   const r=matchPublic(p,source,b),m=r.matrix;
   const rects=rectanglePlan(p.ops,p.shade,source.width,source.height,rgbaOf(b).data,b.width,b.height,m);
   if(!r.gridVerified&&rects&&rects.every(q=>q.dst[0]>=6&&q.dst[1]>=6&&q.dst[2]<b.width-6&&q.dst[3]<b.height-6&&q.src[0]>=6&&q.src[1]>=6&&q.src[2]<source.width-6&&q.src[3]<source.height-6&&(q.dst[2]-q.dst[0]+49)*(q.dst[3]-q.dst[1]+49)<=2000000)&&!rects.some((q,i)=>rects.some((v,j)=>i!==j&&q.dst[0]-24<=v.dst[2]&&q.dst[2]+24>=v.dst[0]&&q.dst[1]-24<=v.dst[3]&&q.dst[3]+24>=v.dst[1]))){
     c.width=b.width;c.height=b.height;const ctx=c.getContext("2d",{alpha:false,willReadFrequently:true});
     ctx.fillStyle="#fff";ctx.fillRect(0,0,c.width,c.height);ctx.drawImage(b,0,0);
     const original=document.createElement("canvas");original.width=source.width;original.height=source.height;const ox=original.getContext("2d",{alpha:false});ox.fillStyle="#fff";ox.fillRect(0,0,original.width,original.height);ox.drawImage(source,0,0);
     let n=0,tones=[];try{for(const rect of rects){const {src,dst}=rect,sw=src[2]-src[0]+1,sh=src[3]-src[1]+1,dw=dst[2]-dst[0]+1,dh=dst[3]-dst[1]+1;
       let pad=Math.min(24,Math.floor(Math.min(dst[0],dst[1],b.width-1-dst[2],b.height-1-dst[3],src[0]*dw/sw,src[1]*dh/sh,(source.width-1-src[2])*dw/sw,(source.height-1-src[3])*dh/sh)));
       // Do not estimate from a context ring intersecting another protected rectangle.
       if(rects.some(q=>q!==rect&&q.dst[0]<=dst[2]+pad&&q.dst[2]>=dst[0]-pad&&q.dst[1]<=dst[3]+pad&&q.dst[3]>=dst[1]-pad))pad=0;
       // Bound the context allocation and search work on unusually large rectangles.
       if(pad<6||(dw+2*pad)*(dh+2*pad)>2000000){ctx.drawImage(original,src[0],src[1],sw,sh,dst[0],dst[1],dw,dh);tones.push({applied:false,warning:true});}
       else{
         const patch=document.createElement("canvas");patch.width=dw+2*pad;patch.height=dh+2*pad;
         try{const px=patch.getContext("2d",{alpha:false,willReadFrequently:true});
           px.drawImage(original,src[0]-pad*sw/dw,src[1]-pad*sh/dh,sw+2*pad*sw/dw,sh+2*pad*sh/dh,0,0,patch.width,patch.height);
           const sourcePixels=px.getImageData(0,0,patch.width,patch.height),ref=ctx.getImageData(dst[0]-pad,dst[1]-pad,patch.width,patch.height);
           const geo=alignPatchContext(sourcePixels.data,ref.data,patch.width,patch.height,pad);
           const tone=matchPatchTone(geo.data,ref.data,patch.width,patch.height,pad,true);
           const localMask=maskFor(patch.width,patch.height,[{kind:"rect",a:[pad,pad],b:[pad+dw-1,pad+dh-1]}]);
           const feather=Math.min(8,Math.floor(pad/3)),maxHalo=Math.min(16,pad-feather);
           const merged=restoreBoundary(tone.data,ref.data,localMask,patch.width,patch.height,{maxHalo,feather,exact:!$("fringeCleanup").checked});
           ref.data.set(merged.data);
           const halo=merged.halo+merged.feather;
           ctx.putImageData(ref,dst[0]-pad,dst[1]-pad,pad-halo,pad-halo,dw+2*halo,dh+2*halo);
           tones.push({applied:tone.applied,geometry:geo.applied,before:tone.before,after:tone.after,contextCorrelation:geo.after,fringe:merged.changed,join:0,warning:merged.warning||tone.after===null||tone.after>18});
         }finally{patch.width=patch.height=1;}
       }n+=dw*dh;
     }}finally{original.width=original.height=1;}
     return {blob:await png(c),n,width:b.width,median:r.pixelMedian,localRects:rects.length,rects,tones};
   }
   // Use the validated global transform when local solid bounds cannot be measured (e.g. page edge).
   const mask=projectedMask(maskFor(source.width,source.height,p.ops),source.width,source.height,b.width,b.height,m);
   c.width=b.width;c.height=b.height;const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
   x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.setTransform(m[0],m[1],-m[1],m[0],m[2],m[3]);x.drawImage(source,0,0);x.setTransform(1,0,0,1,0,0);
   const original=x.getImageData(0,0,c.width,c.height);
   x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.drawImage(b,0,0);
   const returned=x.getImageData(0,0,c.width,c.height),merged=restoreBoundary(original.data,returned.data,mask,c.width,c.height,{exact:!$("fringeCleanup").checked});
   returned.data.set(merged.data);x.putImageData(returned,0,0);return {blob:await png(c),n:merged.core,width:b.width,median:r.pixelMedian,tones:[{fringe:merged.changed,warning:merged.warning||(!rects&&!r.gridVerified)}]};
 }finally{b.close();c.width=c.height=1;}
}
async function composePair(p,source,returnedFile){
 const primary=await composeUsingSource(p,source,returnedFile);
 primary.sourceLabel="对应原图";
 if(!$("pairedReference").checked||p.role!=="中"||!primary.rects)return primary;
 const l=linkFor(links,p),q=l&&other(l,p);
 if(!q||q.role!=="日"||q.shade!==p.shade||!q.ops.length){primary.referenceNote="没有可用的同页日文母版";return primary;}
 let b=null;
 try{
  b=await decode(q.file);
  const alternate=await composeUsingSource(q,b,returnedFile);
  if(preferPairedReference(primary,alternate)){alternate.sourceLabel="配对日文母版（须核对内容）";return alternate;}
  primary.referenceNote="母版未达到改善阈值，使用对应原图";
 }catch(e){primary.referenceNote="母版未通过校验，使用对应原图";}
 finally{if(b)b.close();}
 return primary;
}
for(const id of ["pairedReference","fringeCleanup"])$(id).onchange=()=>run(async()=>{
 if(id==="pairedReference"&&$(id).checked&&!confirm("仅适合中日画面一致且遮盖区无版本专属文字的页面。允许在已配对的日文母版显著改善边界时使用其像素？")){$(id).checked=false;return;}
 for(const p of pages)if(pairIsCurrent(p)){p.pair.composed=false;setPairApproval(p,false);}
 clearRestored();if(pairIsCurrent(current()))await showPair(current());
 status("恢复选项已修改，请重新恢复并检查。");
});
function applyCompareZoom(){
  const z=$("compareZoom").value;
  for(const id of ["returnedImage","restoredImage"]){
    const im=$(id);im.style.width=z==="fit"?"100%":Math.round(compareWidth*Number(z)/100)+"px";im.style.maxWidth=z==="fit"?"100%":"none";
  }
  for(const id of ["returnViewport","restoredViewport"]){$(id).scrollTop=0;$(id).scrollLeft=0;}
}
function presentPair(p,result){
  clearRestored();restoredBlob=result.blob;compareWidth=result.width;
  restoredURL=URL.createObjectURL(restoredBlob);returnedURL=URL.createObjectURL(result.alignedBlob||p.pair.file);
  $("restoredImage").src=restoredURL;$("restoredImage").hidden=false;$("restoreWaiting").hidden=true;$("returnedImage").src=returnedURL;
  $("returnPreview").hidden=false;applyCompareZoom();
  status("恢复 "+result.n+" 像素 · "+(result.sourceLabel||"对应原图")+(result.referenceNote?" · "+result.referenceNote:"")+(result.tones?" · 窄边清理 "+result.tones.reduce((n,t)=>n+(t.fringe||0),0)+" 像素 · 接缝细线修正 "+result.tones.reduce((n,t)=>n+(t.join||0),0)+" 像素":"")+" · "+(result.localRects?"局部矩形 "+result.localRects+" 处":"全局映射（请仔细核对）")+(result.tones?" · 色调校正 "+result.tones.filter(t=>t.applied).length+" 处 · 位移校正 "+result.tones.filter(t=>t.geometry).length+" 处"+(result.tones.some(t=>t.warning)?" · 注意：部分接缝仍不可靠，须人工检查":""):"")+" · 全局误差 "+result.median.toFixed(2)+" px；"+(pairIsApproved(p)?"已确认对应关系。":"请检查两图对应位置后确认。"));
}
async function showPair(p){if(!pairIsCurrent(p))return;if(p.pair.composed){presentPair(p,await composePair(p,bitmap,p.pair.file));}else{clearRestored();const b=await decode(p.pair.file);try{compareWidth=b.width;}finally{b.close();}returnedURL=URL.createObjectURL(p.pair.file);$("returnedImage").src=returnedURL;$("returnPreview").hidden=false;applyCompareZoom();status("返回图已导入："+p.pair.file.name+"。点击恢复遮盖区域。");}}
$("restoreCurrent").onclick=()=>run(async()=>{const p=current();if(!pairIsCurrent(p))throw Error("先导入对应返回图");const result=await composePair(p,bitmap,p.pair.file);p.pair.composed=true;setPairApproval(p,false);presentPair(p,result);$("returnPreview").scrollIntoView({block:"start",behavior:"smooth"});});
$("restoreAll").onclick=()=>run(async()=>{const ids=pages.flatMap((p,i)=>pairIsCurrent(p)?[i]:[]);if(!ids.length)throw Error("请先导入返回图");const results=[];for(const i of ids){const p=pages[i],b=await decode(p.file);try{status("正在恢复 "+(results.length+1)+"/"+ids.length);await composePair(p,b,p.pair.file);results.push(i);}finally{b.close();}}for(const i of results){pages[i].pair.composed=true;setPairApproval(pages[i],false);}await select(results[0]);status("已恢复 "+results.length+" 页，请逐页确认结果。");$("returnPreview").scrollIntoView({block:"start",behavior:"smooth"});});
$("loadReturn").onclick=()=>$("returnFile").click();
$("returnFile").onchange=()=>{const f=$("returnFile").files[0];$("returnFile").value="";if(!f)return;run(async()=>{
  const p=current();if(!p||!bitmap||!count)throw Error("请先准备原图及有效遮盖记录");
  if(p.pair&&!confirm("替换当前页回传图并重新确认？"))return;
  const total=pages.reduce((sum,q)=>sum+(q!==p&&pairIsCurrent(q)?q.pair.file.size:0),0);
  if(total+f.size>TOTAL)throw Error("回传队列超过 80 MB，请分批处理");
  const b=await decode(f);try{const r=matchPublic(p,bitmap,b);projectedMask(maskFor(p.width,p.height,p.ops),p.width,p.height,b.width,b.height,r.matrix);}finally{b.close();}attachPair(p,f);await showPair(p);$("returnPreview").scrollIntoView({block:"start",behavior:"smooth"});
});};
$("approvePair").onchange=()=>{try{if(!restoredBlob||!current()?.pair?.composed)throw Error("请先恢复遮盖区域");setPairApproval(current(),$("approvePair").checked);status($("approvePair").checked?"已确认当前页，可导出。":"已取消确认。");}catch(e){status(e.message);}controls();};
$("removePair").onclick=()=>{invalidatePair(current());clearRestored();status("当前回传图已移除。");controls();};
$("compareZoom").onchange=applyCompareZoom;
let syncTarget=null;
for(const [a,b] of [["returnViewport","restoredViewport"],["restoredViewport","returnViewport"]]){
  $(a).addEventListener("scroll",()=>{
    if(syncTarget===a)return;
    syncTarget=b;$(b).scrollLeft=$(a).scrollLeft;$(b).scrollTop=$(a).scrollTop;
    requestAnimationFrame(()=>{if(syncTarget===b)syncTarget=null;});
  });
}
$("exportRestored").onclick=()=>run(async()=>{
  if(!restoredBlob||!pairIsCurrent(current())||!current()?.pair?.composed)throw Error("请先恢复当前页");
  if(!pairIsApproved(current())){if(!confirm("确认当前恢复图正确？导出文件包含私人内容，请保存在本地。"))return;setPairApproval(current(),true);}
  download(restoredBlob,exportFilename(pages,index,"restored"));status("恢复 PNG 已生成");
});
$("exportBatch").onclick=()=>run(async()=>{
  const ids=reviewedPages(pages);if(!ids.length)throw Error("没有已确认的页面");
  if(!confirm("导出 "+ids.length+" 张已确认恢复图？未确认页不会导出。"))return;
  const entries=[];let total=0;
  for(const i of ids){
    const p=pages[i];if(!pairIsApproved(p))throw Error("配对状态已经失效");
    status("正在恢复 "+(entries.length+1)+"/"+ids.length);
    const source=await decode(p.file);
    try{
      const {blob}=await composePair(p,source,p.pair.file);total+=blob.size;
      if(total>128*1024*1024)throw Error("恢复 ZIP 超过 128 MB，请分批确认和导出");
      entries.push({name:exportFilename(pages,i,"restored"),data:new Uint8Array(await blob.arrayBuffer())});
    }finally{source.close();}
  }
  download(new Blob(zipStore(entries),{type:"application/zip"}),"veilpng_restored.zip");
  status("已生成 "+entries.length+" 张已确认恢复 PNG 的 ZIP。");
});

async function newPage(file,role="其他"){
  const b=await decode(file);try{return {file,width:b.width,height:b.height,hash:await sourceHash(file),role:validRole(role),ops:[],redo:[],shade:0};}finally{b.close();}
}
let saveChain=Promise.resolve(),pending=false,revision=0,savedRevision=-1;
function cpStatus(t){$("checkpointStatus").textContent=t;}
function syncProjectControls(){
  const p=current(),target=$("copyTarget"),old=target.value;
  target.replaceChildren();const placeholder=document.createElement("option");placeholder.value="";placeholder.textContent="选择目标页";target.append(placeholder);
  for(let i=0;i<pages.length;i++){if(i===index)continue;const opt=document.createElement("option");opt.value=String(i);opt.textContent="["+validRole(pages[i].role)+"] "+pages[i].file.name;target.append(opt);}
  if([...target.options].some(o=>o.value===old))target.value=old;
  $("pageRole").value=validRole(p?.role);
  for(const id of ["quickImport","importRole","autosave","resumeProject","deleteCheckpoint"])$(id).disabled=busy;
  $("pageRole").disabled=busy||!p;$("copyTarget").disabled=busy||!p||pages.length<2;
  $("registerPair").disabled=busy||!p||!target.value;
  $("copyMask").disabled=busy||!p||!validAlignment()||!opposite(p,alignment?.target);
  $("downloadOriginal").disabled=busy||!p;
  $("saveProject").disabled=busy||!pages.length;$("openProject").disabled=busy;
  $("quickExport").disabled=ui.exportAll.disabled;$("quickReturn").disabled=$("loadReturn").disabled;
  $("quickBatchReturn").disabled=busy||!pages.some(marked);$("returnRole").disabled=busy;$("recoverMasks").disabled=busy||!pages.length;$("quickRestore").disabled=$("exportBatch").disabled;
}
function markDirty(){
  revision++;if(!$("autosave").checked)return;
  pending=true;cpStatus("本地备份待保存…");
  flushCheckpoint().catch(e=>cpStatus("本地备份失败："+e.message+"；请保存项目记录。"));
}
function flushCheckpoint(){
  if(!$("autosave").checked)return Promise.resolve();
  const rev=revision,record=pages.length?workspaceRecord(pages,links):null,files=pages.map(p=>p.file);
  pending=true;cpStatus("正在保存本地备份…");
  const job=saveChain.catch(()=>{}).then(()=>record?checkpoint("put",{record,files}):checkpoint("delete"));
  saveChain=job;
  return job.then(()=>{if(rev===revision){pending=false;cpStatus(record?"本地备份已保存（含原图，刷新可恢复）":"本地备份已清空");}}).catch(e=>{if(rev===revision){pending=true;cpStatus("本地备份失败："+e.message);}throw e;});
}
$("autosave").onchange=()=>{
  if($("autosave").checked){
    if(!confirm("仅在私人设备开启：原图和选区会保存在当前网站的浏览器存储，未加密。不要在共享电脑开启。继续？")){$("autosave").checked=false;return;}
    if(pages.length)markDirty();else cpStatus("已开启自动保存；导入图片后开始。");
  }else{revision++;pending=false;cpStatus("已停止自动保存；已有备份仍保留，可点击删除浏览器备份。");}
};
window.addEventListener("beforeunload",e=>{if(pages.some(marked)&&(!$("autosave").checked||pending)){e.preventDefault();e.returnValue="";}});
$("resumeProject").onclick=()=>run(async()=>{
  await saveChain.catch(()=>{});const saved=await checkpoint("get");
  if(!saved?.record||!Array.isArray(saved.files)||saved.files.length>32||saved.files.reduce((n,f)=>n+(f?.size||0),0)>TOTAL)throw Error("没有可恢复的本地备份");
  if(pages.length&&!confirm("恢复备份将替换当前队列，继续？"))return;
  const staged=[];for(const f of saved.files){if(!(f instanceof File))throw Error("本地备份文件无效");staged.push(await newPage(f));}
  const matched=matchProject(saved.record,staged),restoredLinks=restoreLinks(saved.record,matched);links=restoredLinks;pages=matched;await select(0);cpStatus("已恢复全部原图、分组和选区；请重新导入回传图。");
});
$("deleteCheckpoint").onclick=()=>run(async()=>{
  if(!confirm("删除浏览器保存的原图和选区备份？不会删除你的本地文件。"))return;
  $("autosave").checked=false;revision++;await saveChain.catch(()=>{});await checkpoint("delete");pending=false;cpStatus("浏览器备份已删除。");
});
async function saveProjectRecord(){
 const bundle=await makePrivateBundle(pages,links);
 download(bundle,"veilpng_PRIVATE_project.zip");savedRevision=revision;
}
$("saveProject").onclick=()=>run(async()=>{await saveProjectRecord();status("私人完整工程 ZIP 下载已请求；请确认保存成功。");});
$("openProject").onclick=()=>$("projectFile").click();
$("downloadOriginal").onclick=()=>run(async()=>{
  const p=current();if(!p)throw Error("请先打开私人项目或原文件");
  if(!confirm("仅下载私人原文件的原始字节，不包含任何外部编辑。请在私人设备保存，继续？"))return;
  const r=await verifiedOriginal(p);
  download(r.file,r.name);status("原文件 SHA-256 已校验，已请求无损下载。请确认浏览器保存成功。");
});
$("projectFile").onchange=()=>{const f=$("projectFile").files[0];$("projectFile").value="";if(!f)return;run(async()=>{
 let staged,newLinks;
 if(/\.zip$/i.test(f.name)){
  const result=await unpackPrivateBundle(f,newPage);staged=result.pages;newLinks=result.links;
 }else{
  if(f.size>64*1024*1024)throw Error("项目记录超限");
  if(!pages.length)throw Error("旧 JSON 不含原图：请先导入全部原图，或打开新版私人工程 ZIP");
  const r=JSON.parse(await f.text());staged=matchProject(r,pages);newLinks=restoreLinks(r,staged);
 }
 if(pages.length&&!confirm("替换当前工程？"))return;
 links=newLinks;pages=staged;await select(0);markDirty();status("工程已恢复，原图哈希通过；已保存的中日配准关系已恢复，请检查后确认。");
});};
$("pageRole").onchange=()=>{if(current()){links=links.filter(l=>l.source!==current()&&l.target!==current());current().role=validRole($("pageRole").value);refreshPartner();controls();markDirty();}};
function grayThumbnail(source,forcedWidth=null,forcedHeight=600){
  const scale=forcedHeight/source.height,w=forcedWidth??Math.round(source.width*scale);
  if(w>1600||w<30)throw Error("图片比例超出自动配准范围");
  const c=document.createElement("canvas");c.width=w;c.height=forcedHeight;
  const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
  x.fillStyle="#fff";x.fillRect(0,0,w,forcedHeight);x.imageSmoothingQuality="high";x.drawImage(source,0,0,w,forcedHeight);
  const rgba=x.getImageData(0,0,w,forcedHeight).data,data=new Uint8Array(w*forcedHeight);
  for(let i=0;i<data.length;i++)data[i]=Math.round(.299*rgba[4*i]+.587*rgba[4*i+1]+.114*rgba[4*i+2]);
  c.width=c.height=1;return {w,h:forcedHeight,scale,data};
}
function registerImages(source,target){
  const a=grayThumbnail(source),b=grayThumbnail(target),r=registerGray(a,b);
  return {...r,matrix:toPixels(r.matrix,a.scale,b.scale),pixelMedian:r.median/b.scale};
}
function clearAlignment(){
  alignment=null;$("registrationPanel").hidden=true;
  const c=$("registrationPreview");c.width=c.height=1;
  $("registrationStatus").textContent="请选择目标图并自动配准";
}
function validAlignment(){return !!(alignment&&alignment.source===current()&&alignment.target===pages[Number($("copyTarget").value)]&&$("copyTarget").value!=="");}
function showAlignment(source,target,m){
  const c=$("registrationPreview"),scale=Math.min(1,900/target.height,900/target.width);
  c.width=Math.max(1,Math.round(target.width*scale));c.height=Math.max(1,Math.round(target.height*scale));
  const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
  x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.drawImage(target,0,0,c.width,c.height);
  const a=x.getImageData(0,0,c.width,c.height);
  x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);
  x.setTransform(m[0]*scale,m[1]*scale,-m[1]*scale,m[0]*scale,m[2]*scale,m[3]*scale);x.drawImage(source,0,0);x.setTransform(1,0,0,1,0,0);
  const b=x.getImageData(0,0,c.width,c.height);
  for(let i=0;i<a.data.length;i+=4){const u=Math.round((a.data[i]+a.data[i+1]+a.data[i+2])/3),v=Math.round((b.data[i]+b.data[i+1]+b.data[i+2])/3);a.data[i]=u;a.data[i+1]=v;a.data[i+2]=u;}
  x.putImageData(a,0,0);$("registrationPanel").hidden=false;
}
$("copyTarget").onchange=()=>{clearAlignment();controls();};
$("registerPair").onclick=()=>run(async()=>{
  const p=current(),raw=$("copyTarget").value,q=pages[Number(raw)];
  if(!p||!q||!raw||p===q)throw Error("请选择目标图");
  clearAlignment();const b=await decode(q.file);
  try{const r=registerImages(bitmap,b);alignment={source:p,target:q,matrix:r.matrix};
    showAlignment(bitmap,b,r.matrix);$("registrationStatus").textContent="配准完成：内点 "+r.inliers+"/"+r.matches+"；中位误差 "+r.pixelMedian.toFixed(2)+" px。请检查叠加。";
    status("配准完成，请检查叠加预览。");
  }finally{b.close();}
});
$("copyMask").onclick=()=>run(async()=>{
 if(!validAlignment()||!opposite(current(),alignment.target))throw Error("请先完成中日配准");
 const p=current(),q=alignment.target;
 if(!confirm("确认两图是同页且叠加位置正确？随后框选一次将同步修改两侧。"))return;
 if(linkFor(links,p)||linkFor(links,q))throw Error("请先解除已有配对");
 const l=makeLink(p,q,alignment.matrix);
 if(p.ops.length&&!q.ops.length){q.ops=p.ops.map(op=>mappedOp(l,p,op));q.shade=p.shade;q.redo=[];invalidatePair(q);markDirty();}
 links.push(l);markDirty();$("linkEdits").checked=true;clearAlignment();render();status("已绑定中日同页；框选后两侧同步遮盖，请检查两侧。");
});
$("quickImport").onclick=()=>{$("importRole").value="其他";ui.files.click();};
$("importCN").onclick=()=>{$("importRole").value="中";ui.files.click();};
$("importJP").onclick=()=>{$("importRole").value="日";ui.files.click();};
$("easySave").onclick=()=>$("saveProject").click();
$("easyResume").onclick=()=>$("resumeProject").click();
$("easyOpen").onclick=()=>$("openProject").click();
$("easyRecover").onclick=()=>$("recoverMasks").click();
$("quickExport").onclick=()=>ui.exportAll.click();
$("quickReturn").onclick=()=>$("returnFile").click();
$("quickRestore").onclick=()=>$("exportBatch").click();
$("quickBatchReturn").onclick=()=>$("batchReturnFile").click();
$("recoverMasks").onclick=()=>$("recoverFiles").click();
$("recoverFiles").onchange=()=>{const input=Array.from($("recoverFiles").files);$("recoverFiles").value="";if(!input.length)return;run(async()=>{
 const files=[];for(const f of input){if(/\.zip$/i.test(f.name))files.push(...await readPublicZip(f));else if(/\.png$/i.test(f.name))files.push(f);else throw Error("仅支持 PNG 或 ZIP");}
 if(!files.length||files.length>32||files.reduce((n,f)=>n+f.size,0)>128*1024*1024)throw Error("遮盖文件数量或大小超限");
 const staged=new Map();
 for(const f of files){
   status("正在重建 "+f.name);const b=await decode(f);
   try{
     const red=rgbaOf(b).data,hits=[];
     for(let i=0;i<pages.length;i++){const p=pages[i];if(staged.has(i)||p.width!==b.width||p.height!==b.height)continue;
       const orig=await decode(p.file);try{let r;try{r=recoverRectangles(rgbaOf(orig).data,red,b.width,b.height);}catch{continue;}hits.push({i,r});}finally{orig.close();}
     }
     if(hits.length!==1)throw Error("无法唯一识别矩形遮盖："+f.name+"；请核对原图或手动标记");
     staged.set(hits[0].i,hits[0].r);
   }finally{b.close();}
 }
 if(!confirm("识别到 "+staged.size+" 张遮盖图，重建对应选区？必须逐页检查；原本已是纯色的区域可能无法反推。"))return;
 for(const [i,r] of staged){const p=pages[i];p.ops=r.ops;p.shade=r.shade;p.redo=[];invalidatePair(p);invalidateLinkReview(p);}
 markDirty();await select(staged.keys().next().value);status("已重建选区；请逐页检查，并保存全部项目记录。");
});};
$("batchReturnFile").onchange=()=>{const input=Array.from($("batchReturnFile").files);$("batchReturnFile").value="";if(!input.length)return;run(async()=>{
 const files=[];for(const f of input){if(/\.zip$/i.test(f.name))files.push(...await readPublicZip(f,"return"));else files.push(f);}
 if(!files.length||files.length>32||files.reduce((n,f)=>n+f.size,0)>TOTAL)throw Error("回传图最多 32 张，合计 80 MB");
 const staged=new Map(),role=$("returnRole").value;
 for(const f of files){
   status("正在识别回传图 "+f.name);const b=await decode(f),hits=[],failures=[];
   try{
     const named=matchesExportName(pages,f.name),hint=roleFromPublicName(f.name);
     for(let i=0;i<pages.length;i++){
       const p=pages[i];if(staged.has(i)||!marked(p)||(role&&p.role!==role))continue;
       const src=await decode(p.file);try{let r;try{r=matchPublic(p,src,b);projectedMask(maskFor(p.width,p.height,p.ops),p.width,p.height,b.width,b.height,r.matrix);}catch(e){failures.push(p.file.name+"："+e.message);continue;}hits.push({i,role:p.role,...r});}finally{src.close();}
     }
     const decision=returnDecision(hits,named,hint);let hit=decision.hit;
     if(!hit){
       const candidates=decision.candidates;
       if(!candidates.length)throw Error("无法验证返回图 "+f.name+"；"+(failures.slice(0,3).join("；")||"没有已标记且符合分组的原图")+"。请核对原工程、图片及分组；可尝试当前页手动配对。");
       const answer=prompt("请确认返回图对应原图（输入编号，取消则终止导入）：\n"+f.name+"\n"+candidates.map((r,k)=>(k+1)+" · ["+pages[r.i].role+"] "+pages[r.i].file.name+(named.includes(r.i)?" · 文件名匹配":"")+" · 内点 "+r.inliers+(r.gridContext?" · 画面校验":" · 请核对配准")).join("\n"));
       if(answer===null)return;if(!/^[0-9]+$/.test(answer.trim())||!candidates[Number(answer)-1])throw Error("未选择有效来源");hit=candidates[Number(answer)-1];
     }
     staged.set(hit.i,f);
   }finally{b.close();}
 }
 const total=pages.reduce((n,p,i)=>n+(staged.has(i)?staged.get(i).size:pairIsCurrent(p)?p.pair.file.size:0),0);
 if(total>TOTAL)throw Error("回传队列超过 80 MB");
 if(!confirm("按画面匹配以下返回图（仍须逐页确认）：\n"+[...staged].map(([i,f])=>f.name+" → "+pages[i].file.name).join("\n")))return;
 for(const [i,f] of staged)attachPair(pages[i],f);
 await select(staged.keys().next().value);status("批量匹配完成，点击恢复遮盖区域（全部），再逐页确认。");$("returnPreview").scrollIntoView({block:"start",behavior:"smooth"});
});};

function syncEasyControls(){
 const p=current(),n=pages.filter(marked).length,k=pages.filter(pairIsCurrent).length,reviewed=reviewedPages(pages).length;
 $("nextAction").textContent=!pages.length?"第一步：导入原图":!n?"在图片上拖动矩形选区":k>reviewed?(pages.some(p=>pairIsCurrent(p)&&!p.pair.composed)?"返回图已导入：点击恢复遮盖区域":"检查恢复结果，再确认当前页"):reviewed?"已确认的结果可以导出":"标记完成后，保存项目并导出遮盖图片";
 $("easyProgress").textContent="已导入 "+pages.length+" 张 · 有选区 "+n+" 张 · 已配对 "+k+" 张 · 已确认 "+reviewed+" 张";
 for(const id of ["importCN","importJP","easyResume"])$(id).disabled=busy;
 $("easyOpen").disabled=busy;$("easySave").disabled=$("saveProject").disabled;$("easyRecover").disabled=$("recoverMasks").disabled;
 $("easyMatch").disabled=busy||!p||!!linkFor(links,p)||!pages.some(q=>opposite(p,q)&&!linkFor(links,q));
 $("easyTransfer").disabled=$("copyMask").disabled;
 $("nextReview").disabled=busy||!restoredBlob||!pairIsCurrent(p);
}
$("easyMatch").onclick=()=>run(async()=>{
 const p=current();if(!p||!bitmap)throw Error("先导入原图");
 clearAlignment();const hits=[];
 for(let i=0;i<pages.length;i++){const q=pages[i];if(q===p||!["中","日"].includes(q.role)||q.role===p.role||linkFor(links,q))continue;
  status("正在查找对应页："+q.file.name);
  const b=await decode(q.file);try{try{hits.push({i,...registerImages(bitmap,b)});}catch{}}finally{b.close();}
 }
 const r=chooseMatch(hits),q=pages[r.i];$("copyTarget").value=String(r.i);alignment={source:p,target:q,matrix:r.matrix};
 const b=await decode(q.file);try{showAlignment(bitmap,b,r.matrix);}finally{b.close();}
 $("registrationStatus").textContent="已找到对应页："+q.file.name+"，配准误差 "+r.pixelMedian.toFixed(2)+" px。";
 $("easyMatchHint").textContent="候选："+q.file.name+"。请查看叠加图，再确认迁移。";
 status("已识别候选同页，请检查叠加位置。");$("registrationPanel").scrollIntoView({block:"nearest",behavior:"smooth"});
});
$("easyTransfer").onclick=()=>$("copyMask").click();
$("nextReview").onclick=()=>run(async()=>{
 const p=current();if(!p||!restoredBlob||!pairIsCurrent(p))throw Error("没有可确认的预览");
 if(!confirm("确认当前页的对应关系及恢复预览正确？"))return;
 setPairApproval(p,true);const next=pages.findIndex(q=>pairIsCurrent(q)&&!pairIsApproved(q));
 if(next>=0){await select(next);$("returnPreview").scrollIntoView({block:"start",behavior:"smooth"});}
 else status("所有已配对页均已确认，可以导出已确认结果。");
});

function invalidateLinkReview(p){const l=linkFor(links,p);if(l){l.reviewed=false;l.undo=[];l.redo=[];}}
function afterLinked(l){l.reviewed=false;for(const p of [l.source,l.target]){p.redo=[];invalidatePair(p);}render();markDirty();}
function editLinked(fn){
 const p=current();if(!p)return;const l=linkFor(links,p);
 if(!l){fn(p,null,null);p.redo=[];invalidatePair(p);render();markDirty();return;}
 const before=snapshot(l);
 try{fn(p,$("linkEdits").checked?other(l,p):null,l);}catch(e){const reviewed=l.reviewed;applySnapshot(l,before);l.reviewed=reviewed;throw e;}
 l.undo.push(before);if(l.undo.length>32)l.undo.shift();l.redo=[];afterLinked(l);
}
function syncDualControls(){
 const p=current(),l=linkFor(links,p);
 $("dualTools").hidden=!l;$("partnerStage").hidden=!l;
 if(!l)return;
 const q=other(l,p);$("dualTitle").textContent="当前 "+p.role+" · 对应 "+q.role+(l.reviewed?" · 已确认":" · 待检查");
 for(const id of ["linkEdits","switchSide","unlinkBoth"])$(id).disabled=busy;
 $("confirmBoth").disabled=busy||!hasMask(p)||!hasMask(q)||$("partnerCanvas").dataset.ready!=="yes";
 ui.undo.disabled=busy||!l.undo.length;ui.redo.disabled=busy||!l.redo.length;
}
async function refreshPartner(){
 const gen=++partnerGeneration,p=current(),l=linkFor(links,p),c=$("partnerCanvas");
 c.dataset.ready="no";c.width=c.height=1;
 if(!l){$("partnerStage").hidden=true;return;}
 const q=other(l,p);$("partnerStage").hidden=false;$("partnerTitle").textContent="对应 "+q.role+" · "+q.file.name;
 try{const b=await decode(q.file);try{if(gen!==partnerGeneration||current()!==p||linkFor(links,p)!==l)return;draw(b,q,c);c.dataset.ready="yes";}finally{b.close();}}
 catch(e){if(gen===partnerGeneration)status("对应预览失败："+e.message);}
 if(gen===partnerGeneration)syncDualControls();
}
$("switchSide").onclick=()=>run(async()=>{const l=linkFor(links,current());if(l)await select(pages.indexOf(other(l,current())));});
$("confirmBoth").onclick=()=>{const l=linkFor(links,current());if(!l||$("partnerCanvas").dataset.ready!=="yes"||!hasMask(l.source)||!hasMask(l.target))return;if(confirm("确认两侧遮盖范围完整且正确？")){l.reviewed=true;controls();status("中日两侧均已确认，可一起导出。");}};
$("unlinkBoth").onclick=()=>{const l=linkFor(links,current());if(l&&confirm("解除配对但保留两侧现有选区？")){links=links.filter(x=>x!==l);markDirty();refreshPartner();fitCanvas();controls();}};
controls();
