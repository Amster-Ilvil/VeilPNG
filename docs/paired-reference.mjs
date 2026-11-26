// Only compare candidates with precisely the same destination rectangles.
export function preferPairedReference(primary,alternate){
 if(!primary?.rects?.length||primary.rects.length!==alternate?.rects?.length||primary.tones?.length!==primary.rects.length||alternate.tones?.length!==alternate.rects.length)return false;
 const a=new Map(primary.rects.map((r,i)=>[r.dst.join(','),primary.tones[i]]));
 if(a.size!==primary.rects.length)return false;
 let old=0,next=0;
 for(let i=0;i<alternate.rects.length;i++){
   const p=a.get(alternate.rects[i].dst.join(',')),q=alternate.tones[i];
   if(!p||!Number.isFinite(p.after)||!Number.isFinite(q.after)||!Number.isFinite(q.contextCorrelation)||q.contextCorrelation<.8||q.after>p.after+.25||q.warning)return false;
   old+=p.after;next+=q.after;
 }
 return old>0&&next<=old*.8;
}
