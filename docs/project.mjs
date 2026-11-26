import {maskRecord} from './return-core.mjs';
export const PROJECT_FORMAT='veilpng-web-project-v1';
export const validRole=r=>['中','日','其他'].includes(r)?r:'其他';
export function pageRecord(p){
  return {name:p.file.name,role:validRole(p.role),mask:maskRecord(p.width,p.height,p.hash,p.ops,p.shade)};
}
export function projectRecord(pages){
  if(!Array.isArray(pages)||!pages.length||pages.length>32)throw Error('项目页数无效');
  return {format:PROJECT_FORMAT,pages:pages.map(pageRecord)};
}
export function matchProject(project,pages){
  if(project?.format!==PROJECT_FORMAT||!Array.isArray(project.pages)||!project.pages.length||project.pages.length>32||project.pages.length!==pages.length)throw Error('请导入与项目记录一致的全部原图');
  const unused=new Set(pages.map((_,i)=>i)),out=[];
  for(const r of project.pages){
    if(!r||typeof r.name!=='string'||!r.mask||r.mask.format!=='veilpng-web-mask-v1')throw Error('项目记录无效');
    const hits=[...unused].filter(i=>pages[i].hash===r.mask.sourceSha256&&pages[i].width===r.mask.width&&pages[i].height===r.mask.height);
    const names=hits.filter(i=>pages[i].file.name===r.name);
    const choices=names.length?names:hits;
    if(choices.length!==1)throw Error('原图缺失或有重复匹配，请检查文件：'+r.name);
    const i=choices[0],p=pages[i],m=maskRecord(p.width,p.height,p.hash,r.mask.ops,r.mask.shade);
    unused.delete(i);out.push({...p,role:validRole(r.role),ops:m.ops,shade:m.shade,redo:[],pair:null});
  }
  return out;
}
export function returnIndex(filename,n){
  const m=/^([0-9]{4})_(?:redacted|returned)\.(?:png|jpe?g)$/i.exec(filename);
  if(!m)throw Error('无法按文件名匹配：'+filename+'；请使用逐页导入');
  const i=Number(m[1])-1;
  if(i<0||i>=n)throw Error('回传页码不在当前项目：'+filename);
  return i;
}
async function openDB(){
  return new Promise((resolve,reject)=>{
    const req=indexedDB.open('veilpng-private-local-v1',1);
    req.onupgradeneeded=()=>req.result.createObjectStore('workspace');
    req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error||Error('无法打开浏览器存储'));
    req.onblocked=()=>reject(Error('请关闭其他 VeilPNG 标签页后重试'));
  });
}
export async function checkpoint(mode,value){
  const db=await openDB();
  try{return await new Promise((resolve,reject)=>{
    const tx=db.transaction('workspace',mode==='get'?'readonly':'readwrite'),store=tx.objectStore('workspace');
    const req=mode==='get'?store.get('latest'):mode==='delete'?store.delete('latest'):store.put(value,'latest');
    tx.oncomplete=()=>resolve(mode==='get'?req.result:undefined);
    tx.onabort=tx.onerror=()=>reject(tx.error||Error('本地项目存储失败'));
  });}finally{db.close();}
}
