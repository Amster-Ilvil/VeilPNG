// ==UserScript==
// @name         VeilPNG 幻影坦克黑白底查看及 Alpha 检测（需主动触发）
// @namespace    https://github.com/Amster-Ilvil/VeilPNG
// @version      0.6.4
// @description  Alt+单击网页图片，或从本机选择 PNG，查看同一图片在纯白/纯黑/灰色背景下的效果。只在浏览器本地处理，不访问平台 API。
// @match        https://*.qq.com/*
// @match        https://*.weixin.qq.com/*
// @match        https://*.wechat.com/*
// @match        https://*.xiaohongshu.com/*
// @match        https://*.xhslink.com/*
// @run-at       document-idle
// @grant        none
// @noframes
// ==/UserScript==

(() => {
  'use strict';
  // A sandboxed local viewer: no fetch, network request, localStorage,
  // clipboard writes, platform API overrides, or automatic DOM image edits.
  const ID = 'veilpng-phantom-viewer-057';
  if (document.getElementById(ID)) return;
  const style = document.createElement('style');
  style.textContent = `
    #${ID} {position:fixed!important;inset:0!important;z-index:2147483646!important;background:rgba(12,18,32,.82)!important;display:none!important;align-items:center;justify-content:center;font-family:system-ui,sans-serif!important;color:#17273f!important}
    #${ID}[data-open="true"] {display:flex!important}
    #${ID} .vp-panel {position:relative;background:#f8fafc;border-radius:14px;padding:16px;width:min(850px,94vw);max-height:94vh;box-sizing:border-box;box-shadow:0 12px 42px #0008;overflow:auto}
    #${ID} .vp-row {display:flex;flex-wrap:wrap;gap:8px;margin:8px 0}
    #${ID} button,#${ID} label.vp-file {color:#17273f;background:#dbeafe;padding:8px 12px;border-radius:8px;border:1px solid #9db5d6;cursor:pointer;display:inline-block;font-size:14px}
    #${ID} button:hover,#${ID} label.vp-file:hover {background:#bfdbfe}
    #${ID} .vp-stage {background:#fff;min-height:160px;max-height:65vh;display:flex;align-items:center;justify-content:center;border:1px solid #9da6af;border-radius:8px;overflow:auto}
    #${ID} .vp-stage img {display:block;max-width:100%;max-height:60vh;object-fit:contain;background:transparent!important;filter:none!important;mix-blend-mode:normal!important;opacity:1!important}
    #${ID} p {font-size:13px;line-height:1.5;margin:8px 0;color:#45546b}
    #${ID} h3 {margin:0 0 8px;font-size:18px;color:#17273f}
    #${ID} .vp-close {float:right}
    #${ID} input[type=file] {display:none}
  `;
  const root = document.createElement('div');
  root.id=ID;
  root.setAttribute('data-open','false');
  root.innerHTML = `<div class="vp-panel" role="dialog" aria-label="VeilPNG Alpha 黑白背景查看器" aria-modal="true">
    <button class="vp-close" type="button">关闭 ×</button>
    <h3>VeilPNG 幻影坦克预览</h3>
    <p>Alt+单击任意图片进入；或选择本机 PNG。纯浏览器本地预览，不修改上传文件。</p>
    <div class="vp-row"><button data-bg="#ffffff" type="button">白底</button><button data-bg="#000000" type="button">黑底</button><button data-bg="#808080" type="button">灰底</button><button data-action="inspect" type="button">检查 Alpha</button><label class="vp-file">从本机选择 PNG<input type="file" accept="image/png"></label></div>
    <div class="vp-stage"><img alt="选择 PNG 后查看两种显现"></div>
    <p class="vp-status" aria-live="polite">注意：平台服务器若已压平图片，脚本无法恢复透明通道；本预览不代表手机 App 接收端效果。</p>
  </div>`;
  document.documentElement.append(style,root);
  const stage=root.querySelector('.vp-stage');
  const viewer=root.querySelector('.vp-stage img');
  const status=root.querySelector('.vp-status');
  let blobUrl=null;
  let prevFocus=null;
  function releaseLocal() {if(blobUrl){URL.revokeObjectURL(blobUrl);blobUrl=null;}}
  function close() {root.dataset.open='false';releaseLocal();viewer.removeAttribute('src');if(prevFocus&&prevFocus.focus)prevFocus.focus();}
  function open(src){releaseLocal();prevFocus=document.activeElement;root.dataset.open='true';stage.style.background='#ffffff';viewer.src=src||'';status.textContent='仅在当前浏览器切换背景。若平台将 PNG 转成 JPG，颜色切换不会恢复原图。';root.querySelector('.vp-close').focus();}
  root.querySelector('.vp-close').addEventListener('click',close);
  root.addEventListener('click',event=>{if(event.target===root)close();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&root.dataset.open==='true'){event.preventDefault();close();}});
  root.querySelectorAll('button[data-bg]').forEach(btn=>btn.addEventListener('click',()=>{stage.style.background=btn.dataset.bg;}));
  root.querySelector('input[type=file]').addEventListener('change',event=>{
    const f=event.target.files?.[0]; if(!f) return;
    if(f.type!=='image/png'){status.textContent='请选择 PNG 图片。';return;}
    releaseLocal();blobUrl=URL.createObjectURL(f);viewer.src=blobUrl;
    status.textContent='本机 PNG 已加载；使用白底/黑底查看。脚本不上传或保存图片。';
    event.target.value='';
  });
  root.querySelector('button[data-action="inspect"]').addEventListener('click',()=>{
    if(!viewer.complete || !viewer.naturalWidth){status.textContent='请先加载透明 PNG，再检测 Alpha。';return;}
    try{
      const w=Math.min(viewer.naturalWidth,1024),h=Math.max(1,Math.round(viewer.naturalHeight*w/viewer.naturalWidth));
      const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;
      const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(viewer,0,0,w,h);
      const pixels=ctx.getImageData(0,0,w,h).data;
      let partly=0,transparent=0,opaque=0,alphaMin=255,alphaMax=0;
      for(let i=3;i<pixels.length;i+=4){const a=pixels[i];
        if(a===255)opaque++;else if(a===0)transparent++;else partly++;
        if(a<alphaMin)alphaMin=a;if(a>alphaMax)alphaMax=a;
      }
      const label=partly||transparent?'检测到透明度；可尝试切换黑/白背景。':'ALPHA_LOST：此图完全不透明，切换背景不会显示第二层。';
      status.textContent=`${label} 样本像素 ${w}×${h}，Alpha 范围 ${alphaMin}–${alphaMax}；部分透明 ${partly}，完全透明 ${transparent}，不透明 ${opaque}。该结果不证明客户端原生查看器背景会切换。`;
    }catch(e){
      // Web sites can display cross-origin images without allowing Canvas
      // pixel reads. Never attempt a CORS bypass or fetch with credentials.
      status.textContent='无法读取此网页图片像素（可能是跨域保护）。可先保存 PNG，再用“从本机选择 PNG”检测。';
    }
  });
  viewer.addEventListener('error',()=>{status.textContent='图片无法加载，可能受站点图片授权限制。可以选择本机下载的 PNG。';});
  document.addEventListener('click',event=>{
    if(!event.altKey || root.dataset.open==='true') return;
    const target=event.target?.closest?.('img');
    if(!target || !target.currentSrc && !target.src) return;
    event.preventDefault();event.stopPropagation();
    open(target.currentSrc||target.src);
  },true);
})();
