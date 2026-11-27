// Use original upload stems for every public and restored export.
const encoder=new TextEncoder();
const key=s=>s.normalize('NFC').toLowerCase();
function fit(s,max=200){let out='',n=0;for(const ch of s){const k=encoder.encode(ch).length;if(n+k>max)break;out+=ch;n+=k;}return out;}
export function sourceStem(name){
 const base=String(name||'').replace(/^.*[\\/]/,'').replace(/\.[^.]+$/,'').normalize('NFC');
 return fit(base.replace(/[<>:"/\\|?*\x00-\x1f\x7f]/g,'_').replace(/[\u202a-\u202e\u2066-\u2069]/g,'_').trim().replace(/[. ]+$/,'')).replace(/[. ]+$/,'')||'image';
}
export function exportPrefixes(pages){
 const stems=pages.map(p=>sourceStem(p.file.name)),reserved=new Set(stems.map(key)),used=new Set();
 return stems.map(stem=>{
   let candidate=stem,n=2;
   if(used.has(key(candidate))){do{const suffix='_'+n++;candidate=fit(stem,200-suffix.length)+suffix;}while(used.has(key(candidate))||reserved.has(key(candidate)));}
   used.add(key(candidate));return candidate;
 });
}
export function exportFilename(pages,index,kind){
 if(!['redacted','restored','local_mask'].includes(kind)||!Number.isInteger(index)||!pages[index])throw Error('无效导出文件名');
 return exportPrefixes(pages)[index]+'_'+kind+(kind==='local_mask'?'.json':'.png');
}
export function safePublicName(name){
 return typeof name==='string'&&/^[^<>:"/\\|?*\x00-\x1f\x7f]+_(?:redacted|restored)\.png$/iu.test(name)&&encoder.encode(name).length<=255;
}
export function matchesExportName(pages,filename){
 const stem=String(filename).replace(/\.(?:png|jpe?g|webp)$/i,'');
 return exportPrefixes(pages).flatMap((p,i)=>[p,p+'_redacted',p+'_returned',p+'_restored'].some(n=>key(n)===key(stem))?[i]:[]);
}
