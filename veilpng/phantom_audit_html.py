"""No-network browser-based alpha checker for Mac/Windows/Linux.

The returned HTML works offline with local file selections. Nothing is
uploaded or fetched; computed results are diagnostic and not app-native proof.
"""
from __future__ import annotations


def offline_return_audit_html() -> str:
    return r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VeilPNG 本地 Alpha 回传检查</title>
<style>
:root{color-scheme:light;font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:#edf3fa;color:#243447}
main{max-width:1100px;margin:0 auto;padding:24px}h1{font-size:23px;margin:0 0 10px}
p{line-height:1.6;color:#455972}header,section{background:white;padding:18px;border-radius:14px;margin-bottom:15px;box-shadow:0 2px 12px #1729430b}
.files{display:grid;grid-template-columns:1fr 1fr;gap:12px}
label{display:block;font-weight:600}input[type=file]{display:block;width:100%;padding:8px;border:1px solid #ccd7e4;border-radius:8px;margin-top:6px}
button{padding:10px 18px;margin:8px 10px 8px 0;border:0;border-radius:8px;color:white;background:#2563b7;cursor:pointer}
#status{white-space:pre-wrap;background:#eff6ff;border-radius:8px;padding:12px;font-variant-numeric:tabular-nums;line-height:1.7}
.compare{display:grid;grid-template-columns:1fr 1fr;gap:12px}.panel{border:1px solid #d3dce9;border-radius:8px;overflow:hidden}
.panel h3{font-size:14px;margin:0;padding:8px;background:#f5f7fa}
.stage{display:grid;place-items:center;min-height:150px;aspect-ratio:3/4;overflow:hidden}
.stage img{width:100%;height:100%;object-fit:contain;max-height:55vh}
.bg-white{background:#fff}.bg-black{background:#000}
small{color:#5e6b7b}footer{font-size:12px;color:#64748b}
@media(max-width:700px){.files,.compare{grid-template-columns:1fr}}
</style></head><body><main>
<header><h1>VeilPNG · 幻影坦克回传检查</h1>
<p>适用于 Mac Safari、Chrome 和 Windows/Linux 浏览器。先选择上传前的透明 PNG，再选择从微信、QQ、小红书等平台<strong>实际保存回来</strong>的图片。所有计算在浏览器本机执行，不连接任何服务器。</p>
<div class="files"><label>① 上传前 PNG<input id="before" type="file" accept="image/png"></label>
<label>② 平台返回图片<input id="after" type="file" accept="image/png,image/jpeg,image/webp,image/avif"></label></div>
<button id="audit" type="button">检查透明度与双背景效果</button><button id="reset" type="button">清空</button>
<div id="status" role="status" aria-live="polite">选择两张图片后点击“检查”。</div>
<p><small>重要：本工具只能检查文件中的透明度和画面变化。即使显示“文件保留 Alpha”，也不能证明某个平台的聊天缩略图与点开大图采用不同背景。</small></p></header>
<section><h2>白底显示</h2><div class="compare"><div class="panel"><h3>上传前</h3><div class="stage bg-white"><img id="white-before" alt="原图白底预览"></div></div><div class="panel"><h3>平台返回</h3><div class="stage bg-white"><img id="white-after" alt="返回图白底预览"></div></div></div></section>
<section><h2>黑底显示</h2><div class="compare"><div class="panel"><h3>上传前</h3><div class="stage bg-black"><img id="black-before" alt="原图黑底预览"></div></div><div class="panel"><h3>平台返回</h3><div class="stage bg-black"><img id="black-after" alt="返回图黑底预览"></div></div></div></section>
<footer>VeilPNG · 离线回传检查；不用于解密、不上传素材。测试结果仅描述这两份本地文件。</footer>
</main><script>
(() => {
'use strict';
const get = id => document.getElementById(id);
let urls = [];
function clean(){for(const u of urls)URL.revokeObjectURL(u);urls=[];}
function message(s){get('status').textContent=s;}
function readImage(file){return new Promise((resolve,reject)=>{
 const url=URL.createObjectURL(file);urls.push(url);
 const img=new Image();img.onload=()=>resolve({img,url});img.onerror=()=>reject(new Error('无法打开：'+file.name));img.src=url;
});}
function pixels(image,w,h){const c=document.createElement('canvas');c.width=w;c.height=h;
 const ctx=c.getContext('2d',{willReadFrequently:true});ctx.clearRect(0,0,w,h);ctx.drawImage(image,0,0,w,h);return ctx.getImageData(0,0,w,h).data;}
function run(before,after){
 const aw=before.naturalWidth,ah=before.naturalHeight,bw=after.naturalWidth,bh=after.naturalHeight;
 // Keep the working set bounded on 16GB Macs and browser tabs.
 const scale=Math.min(1,1400/Math.max(bw,bh),Math.sqrt(1_500_000/(bw*bh)));
 const w=Math.max(1,Math.round(bw*scale)),h=Math.max(1,Math.round(bh*scale));
 const a=pixels(before,w,h),b=pixels(after,w,h);
 let dAlpha=0,dWhite=0,dBlack=0,nTrans=0,nTransBefore=0;
 for(let i=0;i<a.length;i+=4){
   const aa=a[i+3]/255,bb=b[i+3]/255;
   if(b[i+3]<255)nTrans++;
   if(a[i+3]<255)nTransBefore++;
   dAlpha+=Math.abs(a[i+3]-b[i+3]);
   for(let c=0;c<3;c++){
     dBlack+=Math.abs(a[i+c]*aa-b[i+c]*bb);
     dWhite+=Math.abs(a[i+c]*aa+255*(1-aa)-(b[i+c]*bb+255*(1-bb)));
   }
 }
 const count=w*h;
 const am=dAlpha/count,wm=dWhite/(count*3),bm=dBlack/(count*3);
 const mismatch=Math.abs(aw/ah-bw/bh)>0.02;
 let verdict,explanation;
 if(nTrans===0){verdict='ALPHA_LOST';explanation='返回图片全部不透明，已失去背景显现切换能力。';}
 else if(mismatch){verdict='GEOMETRY_CHANGED';explanation='返回图宽高比明显改变，可能裁切或扭曲。';}
 else if(am<=2&&wm<=5&&bm<=5){verdict=(aw===bw&&ah===bh)?'PRESERVED':'PRESERVED_RESIZED';explanation='文件层面接近原图；还需在目标 App 上检查缩略图与大图背景。';}
 else{verdict='DEGRADED';explanation='返回图仍有 Alpha，但透明度或显示内容发生明显变化。';}
 return {verdict,explanation,am,wm,bm,nTrans,nTransBefore,aw,ah,bw,bh,w,h};
}
get('audit').addEventListener('click',async()=>{
 const f1=get('before').files[0],f2=get('after').files[0];
 if(!f1||!f2){message('请先选择上传前 PNG 和平台返回图片。');return;}
 clean();try{
 const a=await readImage(f1),b=await readImage(f2);
 for(const id of ['white-before','black-before'])get(id).src=a.url;
 for(const id of ['white-after','black-after'])get(id).src=b.url;
 const r=run(a.img,b.img);
 message(`结果：${r.verdict}\n${r.explanation}\n原尺寸：${r.aw}×${r.ah}；返回尺寸：${r.bw}×${r.bh}\n返回图非不透明像素：${r.nTrans.toLocaleString()}（采样尺度：${r.w}×${r.h}）\nAlpha 平均误差：${r.am.toFixed(3)}；白底误差：${r.wm.toFixed(3)}；黑底误差：${r.bm.toFixed(3)}\n该结果不是原生客户端渲染验收。`);
 }catch(e){message('检查失败：'+e.message);}
});
get('reset').addEventListener('click',()=>{clean();get('before').value='';get('after').value='';
 for(const id of ['white-before','black-before','white-after','black-after'])get(id).removeAttribute('src');
 message('选择两张图片后点击“检查”。');});
})();
</script></body></html>'''
