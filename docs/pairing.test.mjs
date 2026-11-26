import {maskKey,pairIsCurrent,pairIsApproved,attachPair,invalidatePair,setPairApproval,reviewedPages,restoredName} from './pairing.mjs';
function runChecks(){
 const page=()=>({shade:0,ops:[{kind:"rect",a:[0,0],b:[1,1]}]});
 const a=page(),b=page(),c=page(),file={size:12};
 let n=0;
 const ok=(v,msg)=>{if(!v)throw Error(msg);n++;};
 ok(!pairIsCurrent(a),"empty");
 attachPair(a,file);ok(pairIsCurrent(a),"pair");ok(!pairIsApproved(a),"new pair unapproved");
 setPairApproval(a,true);ok(pairIsApproved(a),"approval");
 attachPair(b,file);setPairApproval(b,true);ok(JSON.stringify(reviewedPages([a,b,c]))==="[0,1]","queue indexes");
 a.ops.push({kind:"erase",radius:1,points:[[0,0]]});ok(!pairIsCurrent(a),"mask changed");
 ok(JSON.stringify(reviewedPages([a,b,c]))==="[1]","stale excluded");
 let rejected=false;try{setPairApproval(a,true);}catch{rejected=true;}ok(rejected,"stale approval rejected");
 attachPair(a,file);ok(!pairIsApproved(a),"replacement resets");
 b.shade=255;ok(!pairIsApproved(b),"shade changed");
 invalidatePair(a);ok(!pairIsCurrent(a),"invalidate");
 ok(restoredName(0)==="0001_restored.png"&&restoredName(31)==="0032_restored.png","filename");
 rejected=false;try{restoredName(-1);}catch{rejected=true;}ok(rejected,"invalid index");
 return n;
}
console.log(runChecks()+' pairing checks passed');
