export function maskKey(page){return JSON.stringify([page.shade,page.ops]);}
export function pairIsCurrent(page){return !!(page?.pair?.file&&page.pair.key===maskKey(page));}
export function pairIsApproved(page){return pairIsCurrent(page)&&page.pair.approved===true;}
export function attachPair(page,file){if(!file||typeof file.size!=="number")throw Error("回传文件无效");page.pair={file,key:maskKey(page),approved:false};}
export function invalidatePair(page){if(page)page.pair=null;}
export function setPairApproval(page,approved){if(!pairIsCurrent(page))throw Error("请重新导入并检查回传图");page.pair.approved=approved===true;}
export function reviewedPages(pages){return pages.flatMap((p,i)=>pairIsApproved(p)?[i]:[]);}
export function restoredName(i){if(!Number.isInteger(i)||i<0||i>=32)throw Error("页码无效");return String(i+1).padStart(4,"0")+"_restored.png";}
