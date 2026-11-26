import {sourceHash} from './return-core.mjs';

// Archival export only: never read a returned image, canvas, or selection.
export async function verifiedOriginal(page){
  if(!page?.file || typeof page.file.arrayBuffer !== 'function')throw Error('没有可用原文件');
  const file=page.file,name=file.name;
  if(typeof name!=='string'||!name||name==='.'||name==='..'||/[\\/\x00-\x1f\x7f]/.test(name))throw Error('原文件名无效');
  if(typeof page.hash!=='string'||!/^[0-9a-f]{64}$/.test(page.hash))throw Error('缺少原文件 SHA-256');
  if(await sourceHash(file)!==page.hash)throw Error('原文件校验失败，已停止下载');
  return {file,name,hash:page.hash};
}
