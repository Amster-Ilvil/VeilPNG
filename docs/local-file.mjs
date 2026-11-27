// Detach browser-picked files from their on-disk backing store before use.
const owned=new WeakSet();
export function readableError(e,name=''){
 if(['NotFoundError','NotReadableError','SecurityError'].includes(e?.name))return Error('无法读取本地文件'+(name?'「'+name+'」':'')+'：文件可能已移动、被替换或尚未下载到本机。请重新选择完整的本地文件。');
 return e;
}
export async function snapshotFile(file,maxBytes){
 if(!file||!Number.isSafeInteger(file.size)||file.size<1||file.size>maxBytes)throw Error('文件为空或超过容量限制');
 if(owned.has(file))return file;
 let bytes;try{bytes=await file.arrayBuffer();}catch(e){throw readableError(e,file.name);}
 if(bytes.byteLength!==file.size)throw Error('文件读取不完整，请重新选择：'+file.name);
 const copy=new File([bytes],file.name,{type:file.type,lastModified:file.lastModified});
 owned.add(copy);return copy;
}
export async function snapshotInputs(files,maxTotal,maxEach,maxCount=32){
 if(!files.length||files.length>maxCount||files.reduce((n,f)=>n+f.size,0)>maxTotal)throw Error('导入文件数量或容量超限');
 for(const f of files)if(f.size<1||f.size>maxEach)throw Error('文件为空或超过容量限制：'+f.name);
 return Promise.all(files.map(f=>snapshotFile(f,maxEach)));
}
