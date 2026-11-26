import {crc32} from './core.mjs';
export async function readPublicZip(blob,mode='public'){
 const cap=128*1024*1024;if(blob.size>cap)throw Error('ZIP 超限');const bytes=new Uint8Array(await blob.arrayBuffer()),v=new DataView(bytes.buffer);let end=-1;
 for(let i=bytes.length-22;i>=Math.max(0,bytes.length-65557);i--)if(v.getUint32(i,true)===0x06054b50&&i+22+v.getUint16(i+20,true)===bytes.length){end=i;break;}
 if(end<0||v.getUint16(end+4,true)||v.getUint16(end+6,true))throw Error('无效 ZIP');const n=v.getUint16(end+10,true),offset=v.getUint32(end+16,true),size=v.getUint32(end+12,true);if(!n||n>(mode==='private'?33:32)||v.getUint16(end+8,true)!==n||offset+size!==end)throw Error('ZIP 目录无效');
 let pos=offset,total=0;const out=[],seen=new Set();
 for(let i=0;i<n;i++){
 if(pos+46>end||v.getUint32(pos,true)!==0x02014b50)throw Error('ZIP 目录损坏');const flags=v.getUint16(pos+8,true),method=v.getUint16(pos+10,true),crc=v.getUint32(pos+16,true),compressed=v.getUint32(pos+20,true),raw=v.getUint32(pos+24,true),nl=v.getUint16(pos+28,true),ex=v.getUint16(pos+30,true),comment=v.getUint16(pos+32,true),local=v.getUint32(pos+42,true);if(pos+46+nl+ex+comment>end||flags&1||![0,8].includes(method)||!raw||raw>(mode==='private'?64:20)*1024*1024||(total+=raw)>cap)throw Error('ZIP 条目不支持或超限');
 const name=new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(pos+46,pos+46+nl));if(!(mode==='private'?/^(?:project\.json|original_[0-9]{4}\.(?:png|jpg))$/:mode==='return'?/^[^/\\\x00-\x1f]+\.(?:png|jpe?g)$/i:/^[^/\\\x00-\x1f]+\.png$/i).test(name)||seen.has(name))throw Error('ZIP 仅支持无重复的平面 PNG 文件');seen.add(name);pos+=46+nl+ex+comment;
 if(local+30>offset||v.getUint32(local,true)!==0x04034b50||v.getUint16(local+8,true)!==method)throw Error('ZIP 本地头损坏');const start=local+30+v.getUint16(local+26,true)+v.getUint16(local+28,true);if(start+compressed>offset)throw Error('ZIP 数据越界');
 let data=bytes.subarray(start,start+compressed);if(method===8){const reader=new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw')).getReader();const parts=[];let length=0;try{while(true){const r=await reader.read();if(r.done)break;length+=r.value.length;if(length>raw)throw Error('ZIP 解压超限');parts.push(r.value);}}finally{await reader.cancel();}data=new Uint8Array(length);let at=0;for(const p of parts){data.set(p,at);at+=p.length;}}
 if(data.length!==raw||crc32(data)!==crc)throw Error('ZIP CRC 校验失败');out.push(new File([data],name,{type:/\.json$/i.test(name)?'application/json':/\.jpe?g$/i.test(name)?'image/jpeg':'image/png'}));
 }if(pos!==end)throw Error('ZIP 目录长度不符');return out;
}
