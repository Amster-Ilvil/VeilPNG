import {maskFor,redactRGBA,zipStore} from "./core.mjs?v=0.5.0";
import {sourceHash,maskRecord,loadMaskRecord,restoreRGBA} from "./return-core.mjs?v=0.5.0";
import {pairIsCurrent,pairIsApproved,attachPair,invalidatePair,setPairApproval,reviewedPages,restoredName} from "./pairing.mjs?v=0.5.0";
import {projectRecord,matchProject,validRole,returnIndex,checkpoint} from "./project.mjs?v=0.5.0";
import {registerGray,toPixels,invert,transform,transferMask} from "./registration.mjs?v=0.5.0";
import {projectedMask,recoverRectangles,chooseMatch} from "./recovery.mjs?v=0.5.0";
import {readPublicZip} from "./zip-read.mjs?v=0.5.0";
const $=id=>document.getElementById(id);
const ui={files:$("files"),queue:$("queue"),preview:$("preview"),gesture:$("gesture"),stack:$("stack"),empty:$("empty"),status:$("status"),tool:$("tool"),radius:$("radius"),shade:$("shade"),undo:$("undo"),redo:$("redo"),clearMask:$("clearMask"),clearAll:$("clearAll"),exportOne:$("exportOne"),exportAll:$("exportAll")};
const LIMIT=12_000_000,MAX=20*1024*1024,TOTAL=80*1024*1024;
let pages=[],index=-1,bitmap=null,busy=false,drag=null,count=0;
let restoredBlob=null,restoredURL=null,returnedURL=null,compareWidth=0;
let alignment=null;
const current=()=>pages[index];
const marked=p=>p&&p.ops.length>0;
function status(t){ui.status.textContent=t;}
function controls(){
  const p=current();for(const x of [ui.files,ui.clearAll,ui.tool,ui.radius,ui.shade])x.disabled=busy;
  ui.undo.disabled=busy||!p||!p.ops.length;ui.redo.disabled=busy||!p||!p.redo.length;ui.clearMask.disabled=busy||!p||!p.ops.length;
  ui.exportOne.disabled=busy||!p||count===0;ui.exportAll.disabled=busy||!pages.some(marked);
  syncReturnControls();syncProjectControls();
  ui.queue.replaceChildren();
  pages.forEach((q,i)=>{const li=document.createElement("li"),b=document.createElement("button");b.type="button";b.textContent=(pairIsApproved(q)?"✓ ":pairIsCurrent(q)?"◐ ":marked(q)?"● ":"○ ")+"["+validRole(q.role)+"] "+q.file.name;b.disabled=busy;b.setAttribute("aria-current",String(i===index));b.onclick=()=>run(()=>select(i));li.append(b);ui.queue.append(li);});
}
async function run(fn){if(busy)return;busy=true;drag=null;controls();try{await fn();}catch(e){status("操作失败："+String(e.message||e));}finally{busy=false;controls();}}
async function decode(file){
  if(file.size>MAX)throw Error("文件超过 20 MB");
  const sig=new Uint8Array(await file.slice(0,24).arrayBuffer());
  const png=sig.length>=24&&[137,80,78,71,13,10,26,10].every((x,i)=>sig[i]===x);
  const jpg=sig.length>=3&&sig[0]===255&&sig[1]===216&&sig[2]===255;
  if(!png&&!jpg)throw Error("仅支持真实 PNG/JPEG");
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
  ui.shade.value=String(p.shade);ui.stack.hidden=false;ui.empty.hidden=true;fitCanvas();status((index+1)+"/"+pages.length+" · "+bitmap.width+" × "+bitmap.height+" · 已遮盖 "+count+" 像素");controls();}
async function select(i){clearAlignment();const b=await decode(pages[i].file);if(bitmap)bitmap.close();bitmap=b;index=i;render();const p=current();if(pairIsCurrent(p)){try{await showPair(p);}catch(e){invalidatePair(p);throw e;}}}
ui.files.onchange=()=>{const incoming=Array.from(ui.files.files);ui.files.value="";run(async()=>{if(!incoming.length)return;if(pages.length+incoming.length>32||pages.reduce((s,p)=>s+p.file.size,0)+incoming.reduce((s,f)=>s+f.size,0)>TOTAL)throw Error("队列超过容量限制");for(const f of incoming){if(f.size>MAX)throw Error("单文件超过 20 MB");}const staged=[];for(const f of incoming){staged.push(await newPage(f,$("importRole").value));}const old=pages.length;pages.push(...staged);if(index<0)await select(old);else controls();markDirty();});};
function point(e){const r=ui.gesture.getBoundingClientRect();return [Math.max(0,Math.min(ui.gesture.width-1,Math.floor((e.clientX-r.left)*ui.gesture.width/r.width))),Math.max(0,Math.min(ui.gesture.height-1,Math.floor((e.clientY-r.top)*ui.gesture.height/r.height)))];}
function guide(){const c=ui.gesture,x=c.getContext("2d");x.clearRect(0,0,c.width,c.height);if(!drag)return;const d=drag;x.strokeStyle="#e84a5f";x.fillStyle="#e84a5f";x.globalAlpha=.65;if(d.kind==="rect"){x.lineWidth=Math.max(2,c.width/500);x.strokeRect(d.a[0],d.a[1],d.b[0]-d.a[0],d.b[1]-d.a[1]);}else{x.lineWidth=d.radius*2;x.lineCap="round";x.lineJoin="round";x.beginPath();x.moveTo(...d.points[0]);for(const p of d.points)x.lineTo(...p);x.stroke();x.beginPath();x.arc(...d.points[0],d.radius,0,Math.PI*2);x.fill();}x.globalAlpha=1;}
ui.gesture.onpointerdown=e=>{if(busy||!current()||drag||e.button!==0)return;e.preventDefault();const p=point(e),kind=ui.tool.value;drag=kind==="rect"?{kind,a:p,b:p}:{kind,radius:Math.max(1,Math.min(128,Math.round(Number(ui.radius.value)||12))),points:[p]};ui.gesture.setPointerCapture(e.pointerId);guide();};
ui.gesture.onpointermove=e=>{if(!drag||busy)return;const p=point(e);if(drag.kind==="rect")drag.b=p;else if(drag.points.length<2048){const q=drag.points.at(-1);if(q[0]!==p[0]||q[1]!==p[1])drag.points.push(p);}guide();};
ui.gesture.onpointerup=e=>{if(!drag||busy)return;const d=drag;drag=null;const p=point(e);if(d.kind==="rect")d.b=p;else if(d.points.length<2048)d.points.push(p);const q=current();if(q.ops.length>=128){guide();status("每页最多 128 次选区操作，请清空或撤销后再编辑。");return;}q.ops.push(d);q.redo=[];invalidatePair(q);render();markDirty();};
ui.gesture.onpointercancel=()=>{drag=null;guide();};
ui.undo.onclick=()=>{if(current()?.ops.length){current().redo.push(current().ops.pop());invalidatePair(current());render();markDirty();}};
ui.redo.onclick=()=>{if(current()?.redo.length){current().ops.push(current().redo.pop());invalidatePair(current());render();markDirty();}};
ui.clearMask.onclick=()=>{if(current()&&confirm("清空本页选区？")){current().ops=[];current().redo=[];invalidatePair(current());render();markDirty();}};
ui.shade.onchange=()=>{if(current()){current().shade=Number(ui.shade.value);invalidatePair(current());render();markDirty();}};
ui.clearAll.onclick=()=>{if(!pages.length||confirm("清空全部图片和选区？")){if(bitmap)bitmap.close();bitmap=null;clearRestored();clearAlignment();pages=[];index=-1;count=0;drag=null;ui.stack.hidden=true;ui.empty.hidden=false;for(const c of [ui.preview,ui.gesture]){c.width=1;c.height=1;}status("尚未导入图片");controls();markDirty();}};
function png(c){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(Error("PNG 编码失败")),"image/png"));}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
const name=i=>String(i+1).padStart(4,"0")+"_redacted.png";
async function exportPage(p){const b=await decode(p.file),c=document.createElement("canvas");try{if(!draw(b,p,c))return null;return await png(c);}finally{b.close();c.width=1;c.height=1;}}
ui.exportOne.onclick=()=>run(async()=>{if($("autosave").checked)await flushCheckpoint();else if(!confirm("确认已保存项目记录并保留原图？"))return;const b=await exportPage(current());if(!b)throw Error("选区为空");download(b,name(index));status("当前 PNG 已生成");});
ui.exportAll.onclick=()=>run(async()=>{if($("autosave").checked)await flushCheckpoint();else if(!confirm("确认已保存项目记录并保留原图？刷新可能丢失未保存选区。"))return;const entries=[];let size=0;for(let i=0;i<pages.length;i++){if(!marked(pages[i]))continue;status("正在编码 "+(i+1)+"/"+pages.length);const b=await exportPage(pages[i]);if(!b)continue;size+=b.size;if(size>128*1024*1024)throw Error("导出超过 128 MB，请分批处理");entries.push({name:name(i),data:new Uint8Array(await b.arrayBuffer())});}if(!entries.length)throw Error("没有有效遮盖选区");download(new Blob(zipStore(entries),{type:"application/zip"}),"veilpng_redacted.zip");status("已生成 "+entries.length+" 张遮盖 PNG 的 ZIP");});

function syncReturnControls(){
  $("saveRecord").disabled=busy||!current()||count===0;
  $("loadRecord").disabled=busy||!current();
  $("loadReturn").disabled=busy||!current()||count===0;
  const reviewed=reviewedPages(pages).length;
  $("exportRestored").disabled=busy||!restoredBlob||!pairIsApproved(current());
  $("exportBatch").disabled=busy||!reviewed;
  $("approvePair").disabled=busy||!restoredBlob||!pairIsCurrent(current());
  $("approvePair").checked=pairIsApproved(current());
  $("removePair").disabled=busy||!pairIsCurrent(current());
  $("compareZoom").disabled=busy||!restoredBlob;
  $("pairSummary").textContent="已配对 "+pages.filter(pairIsCurrent).length+" / "+pages.length+" 页 · 已确认 "+reviewed+" 页（仅导出已确认页面）";
}
function clearRestored(){
  restoredBlob=null;
  if(restoredURL)URL.revokeObjectURL(restoredURL);
  restoredURL=null;if(returnedURL)URL.revokeObjectURL(returnedURL);returnedURL=null;compareWidth=0;
  $("restoredImage").removeAttribute("src");$("returnedImage").removeAttribute("src");$("returnPreview").hidden=true;
}
$("saveRecord").onclick=()=>run(async()=>{
  const p=current();if(!p||!bitmap||!count)throw Error("没有有效遮盖选区");
  const r=maskRecord(bitmap.width,bitmap.height,await sourceHash(p.file),p.ops,p.shade);
  download(new Blob([JSON.stringify(r)],{type:"application/json"}),String(index+1).padStart(4,"0")+"_local_mask.json");
  status("遮盖记录已生成：仅本地保存，不要与公开预览一同上传。");
});
$("loadRecord").onclick=()=>$("recordFile").click();
$("recordFile").onchange=()=>{const f=$("recordFile").files[0];$("recordFile").value="";if(!f)return;run(async()=>{
  if(f.size>6000000)throw Error("遮盖记录超限");
  const p=current();if(!p||!bitmap)throw Error("请先导入原图");
  const r=loadMaskRecord(await f.text(),bitmap.width,bitmap.height,await sourceHash(p.file));
  if(p.ops.length&&!confirm("替换当前页遮盖记录？"))return;
  p.ops=r.ops;p.shade=r.shade;p.redo=[];invalidatePair(p);render();markDirty();status("遮盖记录已恢复，原图 SHA-256 匹配。");
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
     if(a.every((v,i)=>v===t[i]))return {matrix:[1,0,0,0],inliers:100000,matches:100000,pixelMedian:0};
   }
   return registerImages(c,b);
 }finally{c.width=c.height=1;}
}
async function composePair(p,source,returnedFile){
 const b=await decode(returnedFile),c=document.createElement("canvas");
 try{
   const r=matchPublic(p,source,b),m=r.matrix;
   const mask=projectedMask(maskFor(source.width,source.height,p.ops),source.width,source.height,b.width,b.height,m);
   c.width=b.width;c.height=b.height;const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
   x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.setTransform(m[0],m[1],-m[1],m[0],m[2],m[3]);x.drawImage(source,0,0);x.setTransform(1,0,0,1,0,0);
   const original=x.getImageData(0,0,c.width,c.height);
   x.fillStyle="#fff";x.fillRect(0,0,c.width,c.height);x.drawImage(b,0,0);
   const returned=x.getImageData(0,0,c.width,c.height),n=restoreRGBA(original.data,returned.data,mask);
   x.putImageData(returned,0,0);return {blob:await png(c),n,width:b.width,median:r.pixelMedian};
 }finally{b.close();c.width=c.height=1;}
}
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
  $("restoredImage").src=restoredURL;$("returnedImage").src=returnedURL;
  $("returnPreview").hidden=false;applyCompareZoom();
  status("恢复 "+result.n+" 像素 · 配准误差 "+result.median.toFixed(2)+" px；"+(pairIsApproved(p)?"已确认对应关系。":"请检查两图对应位置后确认。"));
}
async function showPair(p){if(!pairIsCurrent(p))return;presentPair(p,await composePair(p,bitmap,p.pair.file));}
$("loadReturn").onclick=()=>$("returnFile").click();
$("returnFile").onchange=()=>{const f=$("returnFile").files[0];$("returnFile").value="";if(!f)return;run(async()=>{
  const p=current();if(!p||!bitmap||!count)throw Error("请先准备原图及有效遮盖记录");
  if(p.pair&&!confirm("替换当前页回传图并重新确认？"))return;
  const total=pages.reduce((sum,q)=>sum+(q!==p&&pairIsCurrent(q)?q.pair.file.size:0),0);
  if(total+f.size>TOTAL)throw Error("回传队列超过 80 MB，请分批处理");
  const result=await composePair(p,bitmap,f);attachPair(p,f);presentPair(p,result);
});};
$("approvePair").onchange=()=>{try{setPairApproval(current(),$("approvePair").checked);status($("approvePair").checked?"已确认当前页，可导出。":"已取消确认。");}catch(e){status(e.message);}controls();};
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
  if(!restoredBlob||!pairIsApproved(current()))throw Error("请先检查并确认当前页");
  download(restoredBlob,restoredName(index));status("恢复 PNG 已生成");
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
      entries.push({name:restoredName(i),data:new Uint8Array(await blob.arrayBuffer())});
    }finally{source.close();}
  }
  download(new Blob(zipStore(entries),{type:"application/zip"}),"veilpng_restored.zip");
  status("已生成 "+entries.length+" 张已确认恢复 PNG 的 ZIP。");
});

async function newPage(file,role="其他"){
  const b=await decode(file);try{return {file,width:b.width,height:b.height,hash:await sourceHash(file),role:validRole(role),ops:[],redo:[],shade:0};}finally{b.close();}
}
let saveChain=Promise.resolve(),pending=false,revision=0;
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
  $("copyMask").disabled=busy||!p||!count||!validAlignment();
  $("saveProject").disabled=busy||!pages.length;$("openProject").disabled=busy||!pages.length;
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
  const rev=revision,record=pages.length?projectRecord(pages):null,files=pages.map(p=>p.file);
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
  const matched=matchProject(saved.record,staged);pages=matched;await select(0);cpStatus("已恢复全部原图、分组和选区；请重新导入回传图。");
});
$("deleteCheckpoint").onclick=()=>run(async()=>{
  if(!confirm("删除浏览器保存的原图和选区备份？不会删除你的本地文件。"))return;
  $("autosave").checked=false;revision++;await saveChain.catch(()=>{});await checkpoint("delete");pending=false;cpStatus("浏览器备份已删除。");
});
$("saveProject").onclick=()=>run(async()=>{
  const r=projectRecord(pages);download(new Blob([JSON.stringify(r)],{type:"application/json"}),"veilpng_local_project.json");
  status("全部项目记录已生成：仅保存本地，需同时保留原图。");
});
$("openProject").onclick=()=>$("projectFile").click();
$("projectFile").onchange=()=>{const f=$("projectFile").files[0];$("projectFile").value="";if(!f)return;run(async()=>{
  if(f.size>64*1024*1024)throw Error("项目记录超限");
  const r=JSON.parse(await f.text()),matched=matchProject(r,pages);
  if(pages.some(marked)&&!confirm("替换当前全部选区并按项目记录排序？"))return;
  pages=matched;await select(0);markDirty();status("项目记录已恢复，所有原图 SHA-256 均匹配。");
});};
$("pageRole").onchange=()=>{if(current()){current().role=validRole($("pageRole").value);controls();markDirty();}};
function grayThumbnail(source){
  const scale=600/source.height,w=Math.round(source.width*scale);
  if(w>1600||w<30)throw Error("图片比例超出自动配准范围");
  const c=document.createElement("canvas");c.width=w;c.height=600;
  const x=c.getContext("2d",{alpha:false,willReadFrequently:true});
  x.fillStyle="#fff";x.fillRect(0,0,w,600);x.imageSmoothingQuality="high";x.drawImage(source,0,0,w,600);
  const rgba=x.getImageData(0,0,w,600).data,data=new Uint8Array(w*600);
  for(let i=0;i<data.length;i++)data[i]=Math.round(.299*rgba[4*i]+.587*rgba[4*i+1]+.114*rgba[4*i+2]);
  c.width=c.height=1;return {w,h:600,scale,data};
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
  if(!validAlignment()||!count)throw Error("请先完成配准与选区标记");
  const p=current(),q=alignment.target,i=pages.indexOf(q);
  if(!confirm("确认配准预览无明显错位？将替换目标页选区，请务必在目标图检查并修正。"))return;
  q.ops=transferMask(p.ops,alignment.matrix,q.width,q.height);q.shade=p.shade;q.redo=[];invalidatePair(q);markDirty();
  await select(i);status("已迁移选区，请检查目标页完整覆盖后再导出。");
});
$("quickImport").onclick=()=>ui.files.click();
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
 for(const [i,r] of staged){const p=pages[i];p.ops=r.ops;p.shade=r.shade;p.redo=[];invalidatePair(p);}
 markDirty();await select(staged.keys().next().value);status("已重建选区；请逐页检查，并保存全部项目记录。");
});};
$("batchReturnFile").onchange=()=>{const files=Array.from($("batchReturnFile").files);$("batchReturnFile").value="";if(!files.length)return;run(async()=>{
 if(files.length>32)throw Error("回传图最多 32 张");
 const staged=new Map(),role=$("returnRole").value;
 for(const f of files){
   status("正在识别回传图 "+f.name);const b=await decode(f),hits=[];
   try{
     for(let i=0;i<pages.length;i++){const p=pages[i];if(!marked(p)||(role&&p.role!==role))continue;
       const src=await decode(p.file);try{let r;try{r=matchPublic(p,src,b);projectedMask(maskFor(p.width,p.height,p.ops),p.width,p.height,b.width,b.height,r.matrix);}catch{continue;}hits.push({i,...r});}finally{src.close();}
     }
     const hit=chooseMatch(hits);
     if(staged.has(hit.i))throw Error("多个返回图匹配到同一原图："+f.name);
     staged.set(hit.i,f);
   }finally{b.close();}
 }
 const total=pages.reduce((n,p,i)=>n+(staged.has(i)?staged.get(i).size:pairIsCurrent(p)?p.pair.file.size:0),0);
 if(total>TOTAL)throw Error("回传队列超过 80 MB");
 if(!confirm("按画面匹配以下返回图（仍须逐页确认）：\n"+[...staged].map(([i,f])=>f.name+" → "+pages[i].file.name).join("\n")))return;
 for(const [i,f] of staged)attachPair(pages[i],f);
 await select(staged.keys().next().value);status("批量匹配完成，请逐页确认对应关系。");
});};
controls();
