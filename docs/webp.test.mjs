import assert from 'node:assert/strict';
import {webpDimensions} from './webp.mjs';
const data=new Uint8Array(26);const v=new DataView(data.buffer);for(const [i,s] of [[0,'RIFF'],[8,'WEBP'],[12,'VP8L']])data.set(new TextEncoder().encode(s),i);v.setUint32(4,18,true);v.setUint32(16,5,true);data[20]=47;v.setUint32(21,724|(1023<<14),true);assert.deepEqual(webpDimensions(data),{width:725,height:1024});assert.throws(()=>webpDimensions(data.slice(0,-1)));data[12]=65;assert.throws(()=>webpDimensions(data));console.log('3 WebP header tests passed');
