// Conservative narrow-line correction on a completed composite.
export function repairJoinLines(input,w,h,rect){
 if(!Number.isInteger(w)||!Number.isInteger(h)||w<1||h<1||input.length!==w*h*4||!Array.isArray(rect)||rect.length!==4||!rect.every(Number.isInteger))throw Error('Invalid join image');
 const [l,t,r,b]=rect;
 if(l<0||t<0||r>=w||b>=h||l>r||t>b)throw Error('Invalid join rectangle');
 const data=new Uint8ClampedArray(input),changes=new Map();
 let segments=0;
 const pos=(vertical,fixed,along)=>vertical?(along*w+fixed)*4:(fixed*w+along)*4;
 const close=(a,b)=>[0,1,2].every(c=>Math.abs(input[a+c]-input[b+c])<=10);
 function side(vertical,edge,lo,hi){
  const extent=vertical?w:h;if(hi-lo<8)return;
  for(const [offset,span] of [[-2,2],[-1,2],[0,2],[-1,1],[0,1],[1,1],[-2,1]]){
   const start=edge+offset,end=start+span-1,left=start-1,right=end+1;
   if(left<1||right>=extent-1||start<edge-2||end>edge+1)continue;
   const candidates=[];
   for(let z=lo+2;z<=hi-2;z++){
    const a=pos(vertical,left,z),b=pos(vertical,right,z);
    if(!close(a,b)||!close(a,pos(vertical,left-1,z))||!close(b,pos(vertical,right+1,z))){candidates.push(null);continue;}
    const patches=[];let sign=0,good=true;
    for(let f=start;f<=end;f++){
     const p=pos(vertical,f,z),alpha=(f-left)/(right-left);
     const v=[0,1,2].map(c=>input[a+c]+alpha*(input[b+c]-input[a+c]));
     const delta=v.reduce((n,v,c)=>n+input[p+c]-v,0)/3,s=Math.sign(delta);
     if(Math.abs(delta)<12||Math.abs(delta)>100||(sign&&s!==sign)||![0,1,2].every(c=>s<0?input[p+c]<=Math.min(input[a+c],input[b+c])-5:input[p+c]>=Math.max(input[a+c],input[b+c])+5)){good=false;break;}
     sign=s;patches.push({p,v});
    }
    candidates.push(good?{sign,patches}:null);
   }
   for(let i=0;i<candidates.length;){
    if(!candidates[i]){i++;continue;}
    let j=i+1;while(j<candidates.length&&candidates[j]?.sign===candidates[i].sign)j++;
    if(j-i>=5){segments++;for(let k=i;k<j;k++)for(const {p,v} of candidates[k].patches)if(!changes.has(p))changes.set(p,v);}
    i=j;
   }
  }
 }
 side(true,l,t,b);side(true,r+1,t,b);side(false,t,l,r);side(false,b+1,l,r);
 let changed=0;
 for(const [p,v] of changes){let different=false;for(let c=0;c<3;c++){data[p+c]=Math.round(v[c]);different||=data[p+c]!==input[p+c];}if(different)changed++;}
 return {data,changed,segments};
}
