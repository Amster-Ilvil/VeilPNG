import {makeLink,mappedOp,snapshot,applySnapshot,exportPlan} from './bilingual.mjs';
import {zipStore} from './core.mjs';
const make=role=>({role,width:40,height:40,file:{name:role+'.png'},ops:[],redo:[],shade:0});
const cn=make('中'),jp=make('日'),l=makeLink(cn,jp,[1,0,3,4]),op={kind:'rect',a:[5,5],b:[10,10]};
let n=0;const ok=x=>{if(!x)throw Error('test '+(n+1));n++;};const reject=f=>{try{f();return false;}catch{return true;}};const eq=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
ok(eq(mappedOp(l,cn,op),{kind:'rect',a:[8,9],b:[13,14]}));ok(eq(mappedOp(l,jp,mappedOp(l,cn,op)),op));ok(reject(()=>mappedOp(l,cn,{kind:'rect',a:[36,36],b:[39,39]})));ok(reject(()=>exportPlan([cn,jp],[])));cn.ops=[op];ok(reject(()=>exportPlan([cn,jp],[l])));jp.ops=[mappedOp(l,cn,op)];ok(reject(()=>exportPlan([cn,jp],[l])));l.reviewed=true;const plan=exportPlan([jp,cn],[l]);ok(eq(plan.map(x=>x.name),['0001_CN_redacted.png','0001_JP_redacted.png']));const chunks=zipStore(plan.map(x=>({name:x.name,data:Uint8Array.of(1,2,3)})));ok(new DataView(chunks.at(-1).buffer).getUint16(10,true)===2);const snap=snapshot(l);cn.ops=[];applySnapshot(l,snap);ok(eq(cn.ops,[op]));ok(l.reviewed===false);l.reviewed=true;ok(reject(()=>exportPlan([cn,jp,make('中')],[l])));
console.log(n+' bilingual checks passed');
