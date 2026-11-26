// Remove a narrow resampling halo only when the reference is biased toward the mask color.
// The source and reference are already aligned; the returned output changes at most two pixels outside the rectangle.
export function cleanMaskFringe(source,reference,w,h,pad,shade){
 if(source.length!==w*h*4||reference.length!==source.length||pad<3||w<=2*pad||h<=2*pad||![0,255].includes(shade))throw Error('Invalid fringe context');
 const data=new Uint8ClampedArray(reference);let changed=0;
 for(let y=pad-2;y<h-pad+2;y++)for(let x=pad-2;x<w-pad+2;x++){
  const d=Math.max(pad-x,x-(w-pad-1),pad-y,y-(h-pad-1));
  if(d<=0||d>2)continue;
  const k=(y*w+x)*4,sv=(source[k]+source[k+1]+source[k+2])/3,rv=(reference[k]+reference[k+1]+reference[k+2])/3;
  const bias=shade===0?sv-rv:rv-sv;
  if(bias<12)continue;
  const a=d===1?1:.85;
  for(let c=0;c<3;c++)data[k+c]=Math.round(reference[k+c]+a*(source[k+c]-reference[k+c]));
  if(data[k]!==reference[k]||data[k+1]!==reference[k+1]||data[k+2]!==reference[k+2])changed++;
 }
 return {data,changed};
}
