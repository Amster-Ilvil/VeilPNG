import {projectRecord,matchProject} from './project.mjs';
import {makeLink,linkFor} from './bilingual.mjs';
import {zipStore} from './core.mjs';
import {readPublicZip} from './zip-read.mjs';
export function workspaceRecord(pages,links){
 const r=projectRecord(pages);
 r.links=links.map(l=>({source:pages.indexOf(l.source),target:pages.indexOf(l.target),matrix:[...l.matrix]}));
 return r;
}
export function restoreLinks(record,pages){
 const out=[];if(record.links===undefined)return out;
 if(!Array.isArray(record.links)||record.links.length>16)throw Error('项目配对无效');
 for(const l of record.links){
  if(!Number.isInteger(l.source)||!Number.isInteger(l.target)||l.source<0||l.target<0||l.source>=pages.length||l.target>=pages.length)throw Error('项目配对索引无效');
  const p=pages[l.source],q=pages[l.target];if(linkFor(out,p)||linkFor(out,q))throw Error('重复配对');
  out.push(makeLink(p,q,l.matrix));
 }return out;
}
export async function makePrivateBundle(pages,links){
 const record=workspaceRecord(pages,links),entries=[];
 for(let i=0;i<pages.length;i++){
  const f=pages[i].file,data=new Uint8Array(await f.arrayBuffer());
  const ext=data[0]===137&&data[1]===80?'png':data[0]===82&&data[1]===73&&data[8]===87&&data[9]===69?'webp':'jpg';
  entries.push({name:'original_'+String(i+1).padStart(4,'0')+'.'+ext,data});
 }
 entries.push({name:'project.json',data:new TextEncoder().encode(JSON.stringify(record))});
 if(entries.reduce((n,e)=>n+e.data.length,0)>120*1024*1024)throw Error('私人项目超过容量上限');
 return new Blob(zipStore(entries,'private'),{type:'application/zip'});
}
export async function unpackPrivateBundle(blob,newPage){
 const files=await readPublicZip(blob,'private'),meta=files.find(f=>f.name==='project.json');
 if(!meta)throw Error('不是私人项目 ZIP：公开遮盖 ZIP 请使用回传导入');
 const record=JSON.parse(await meta.text());
 if(!Array.isArray(record.pages)||record.pages.length<1||record.pages.length>32||files.length!==record.pages.length+1)throw Error('项目文件数量不一致');
 const staged=[];let total=0;
 for(let i=0;i<record.pages.length;i++){
  const prefix='original_'+String(i+1).padStart(4,'0')+'.',hits=files.filter(f=>f.name.startsWith(prefix));
  if(hits.length!==1)throw Error('缺少原图 '+prefix);
  const f=hits[0],name=record.pages[i]?.name;
  if(typeof name!=='string'||!name||name.length>1024)throw Error('原文件名无效');
  if((total+=f.size)>80*1024*1024)throw Error('原图容量超限');
  staged.push(await newPage(new File([f],name,{type:f.type}),record.pages[i].role));
 }
 const pages=matchProject(record,staged),links=restoreLinks(record,pages);
 return {pages,links};
}
export function roleFromPublicName(name){
 const m=/^\d{4}_(CN|JP)_(?:redacted|returned)\.(?:png|jpe?g|webp)$/i.exec(name);
 return m?(m[1].toUpperCase()==='CN'?'中':'日'):'';
}
