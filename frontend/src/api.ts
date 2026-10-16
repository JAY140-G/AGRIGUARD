export async function api<T>(path:string,method='GET',data?:unknown):Promise<T>{
 const isForm=data instanceof FormData;
 const response=await fetch('/api'+path,{method,credentials:'include',headers:{'X-AgriScan':'1',...(!isForm&&data?{'Content-Type':'application/json'}:{})},body:data?(isForm?data:JSON.stringify(data)):undefined});
 if(!response.ok){let detail;try{detail=(await response.json()).detail}catch{detail=response.statusText}throw new Error(typeof detail==='string'?detail:JSON.stringify(detail))}
 return response.json();
}
