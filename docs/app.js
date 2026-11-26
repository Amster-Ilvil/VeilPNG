import {maskFor,redactRGBA,zipStore} from "./core.mjs";
const $=id=>document.getElementById(id);
const ui={files:$("files"),queue:$("queue"),preview:$("preview"),gesture:$("gesture"),stack:$("stack"),empty:$("empty"),status:$("status"),tool:$("tool"),radius:$("radius"),shade:$("shade"),undo:$("undo"),redo:$("redo"),clearMask:$("clearMask"),clearAll:$("clearAll"),exportOne:$("exportOne"),exportAll:$("exportAll")};
const LIMIT=12_000_000,MAX=20*1024*1024,TOTAL=80*1024*1024;
let pages=[],index=-1,bitmap=null,busy=false,drag=null,count=0;
const current=()=>pages[index];
const marked=p=>p&&p.ops.length>0;
function status(t){ui.status.textContent=t;}
function controls(){
  const p=current();for(const x of [ui.files,ui.clearAll,ui.tool,ui.radius,ui.shade])x.disabled=busy;
  ui.undo.disabled=busy||!p||!p.ops.length;ui.redo.disabled=busy||!p||!p.redo.length;ui.clearMask.disabled=busy||!p||!p.ops.length;
  ui.exportOne.disabled=busy||!p||count===0;ui.exportAll.disabled=busy||!pages.some(marked);
  ui.queue.replaceChildren();
  pages.forEach((q,i)=>{const li=document.createElement("li"),b=document.createElement("button");b.type="button";b.textContent=(marked(q)?"● ":"○ ")+q.file.name;b.disabled=busy;b.setAttribute("aria-current",String(i===index));b.onclick=()=>run(()=>select(i));li.append(b);ui.queue.append(li);});
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
function render(){const p=current();if(!p||!bitmap)return;count=draw(bitmap,p,ui.preview);ui.gesture.width=bitmap.width;ui.gesture.height=bitmap.height;ui.gesture.getContext("2d").clearRect(0,0,bitmap.width,bitmap.height);
  ui.shade.value=String(p.shade);ui.stack.hidden=false;ui.empty.hidden=true;fitCanvas();status((index+1)+"/"+pages.length+" · "+bitmap.width+" × "+bitmap.height+" · 已遮盖 "+count+" 像素");controls();}
async function select(i){const b=await decode(pages[i].file);if(bitmap)bitmap.close();bitmap=b;index=i;render();}
ui.files.onchange=()=>{const incoming=Array.from(ui.files.files);ui.files.value="";run(async()=>{if(!incoming.length)return;if(pages.length+incoming.length>32||pages.reduce((s,p)=>s+p.file.size,0)+incoming.reduce((s,f)=>s+f.size,0)>TOTAL)throw Error("队列超过容量限制");for(const f of incoming){if(f.size>MAX)throw Error("单文件超过 20 MB");}const staged=[];for(const f of incoming){const b=await decode(f);b.close();staged.push({file:f,ops:[],redo:[],shade:0});}const old=pages.length;pages.push(...staged);if(index<0)await select(old);else render();});};
function point(e){const r=ui.gesture.getBoundingClientRect();return [Math.max(0,Math.min(ui.gesture.width-1,Math.floor((e.clientX-r.left)*ui.gesture.width/r.width))),Math.max(0,Math.min(ui.gesture.height-1,Math.floor((e.clientY-r.top)*ui.gesture.height/r.height)))];}
function guide(){const c=ui.gesture,x=c.getContext("2d");x.clearRect(0,0,c.width,c.height);if(!drag)return;const d=drag;x.strokeStyle="#e84a5f";x.fillStyle="#e84a5f";x.globalAlpha=.65;if(d.kind==="rect"){x.lineWidth=Math.max(2,c.width/500);x.strokeRect(d.a[0],d.a[1],d.b[0]-d.a[0],d.b[1]-d.a[1]);}else{x.lineWidth=d.radius*2;x.lineCap="round";x.lineJoin="round";x.beginPath();x.moveTo(...d.points[0]);for(const p of d.points)x.lineTo(...p);x.stroke();x.beginPath();x.arc(...d.points[0],d.radius,0,Math.PI*2);x.fill();}x.globalAlpha=1;}
ui.gesture.onpointerdown=e=>{if(busy||!current()||drag||e.button!==0)return;e.preventDefault();const p=point(e),kind=ui.tool.value;drag=kind==="rect"?{kind,a:p,b:p}:{kind,radius:Math.max(1,Math.min(128,Math.round(Number(ui.radius.value)||12))),points:[p]};ui.gesture.setPointerCapture(e.pointerId);guide();};
ui.gesture.onpointermove=e=>{if(!drag||busy)return;const p=point(e);if(drag.kind==="rect")drag.b=p;else if(drag.points.length<2048){const q=drag.points.at(-1);if(q[0]!==p[0]||q[1]!==p[1])drag.points.push(p);}guide();};
ui.gesture.onpointerup=e=>{if(!drag||busy)return;const d=drag;drag=null;const p=point(e);if(d.kind==="rect")d.b=p;else if(d.points.length<2048)d.points.push(p);const q=current();if(q.ops.length>=128){guide();status("每页最多 128 次选区操作，请清空或撤销后再编辑。");return;}q.ops.push(d);q.redo=[];render();};
ui.gesture.onpointercancel=()=>{drag=null;guide();};
ui.undo.onclick=()=>{if(current()?.ops.length){current().redo.push(current().ops.pop());render();}};
ui.redo.onclick=()=>{if(current()?.redo.length){current().ops.push(current().redo.pop());render();}};
ui.clearMask.onclick=()=>{if(current()&&confirm("清空本页选区？")){current().ops=[];current().redo=[];render();}};
ui.shade.onchange=()=>{if(current()){current().shade=Number(ui.shade.value);render();}};
ui.clearAll.onclick=()=>{if(!pages.length||confirm("清空全部图片和选区？")){if(bitmap)bitmap.close();bitmap=null;pages=[];index=-1;count=0;drag=null;ui.stack.hidden=true;ui.empty.hidden=false;for(const c of [ui.preview,ui.gesture]){c.width=1;c.height=1;}status("尚未导入图片");controls();}};
function png(c){return new Promise((resolve,reject)=>c.toBlob(b=>b?resolve(b):reject(Error("PNG 编码失败")),"image/png"));}
function download(blob,name){const url=URL.createObjectURL(blob),a=document.createElement("a");a.href=url;a.download=name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
const name=i=>String(i+1).padStart(4,"0")+"_redacted.png";
async function exportPage(p){const b=await decode(p.file),c=document.createElement("canvas");try{if(!draw(b,p,c))return null;return await png(c);}finally{b.close();c.width=1;c.height=1;}}
ui.exportOne.onclick=()=>run(async()=>{const b=await exportPage(current());if(!b)throw Error("选区为空");download(b,name(index));status("当前 PNG 已生成");});
ui.exportAll.onclick=()=>run(async()=>{const entries=[];let size=0;for(let i=0;i<pages.length;i++){if(!marked(pages[i]))continue;status("正在编码 "+(i+1)+"/"+pages.length);const b=await exportPage(pages[i]);if(!b)continue;size+=b.size;if(size>128*1024*1024)throw Error("导出超过 128 MB，请分批处理");entries.push({name:name(i),data:new Uint8Array(await b.arrayBuffer())});}if(!entries.length)throw Error("没有有效遮盖选区");download(new Blob(zipStore(entries),{type:"application/zip"}),"veilpng_redacted.zip");status("已生成 "+entries.length+" 张遮盖 PNG 的 ZIP");});
controls();
