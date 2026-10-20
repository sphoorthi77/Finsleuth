export type Role='analyst'|'manager'|'admin';
export interface User {id:string;name:string;email:string;role:Role;scope:string;status:string;organisation:string;}
export type RecordData=Record<string,any>;
export async function api<T=RecordData>(path:string,options:RequestInit={}):Promise<T>{
 const form=options.body instanceof FormData;
 const controller=new AbortController();
 const timer=setTimeout(()=>controller.abort(),path==='/health'?8000:120000);
 try{
  let res:Response;
  try{res=await fetch('/api/v1'+path,{...options,signal:options.signal||controller.signal,credentials:'include',headers:{'X-Finsleuth':'1',...(!form?{'Content-Type':'application/json'}:{}),...options.headers}})}catch(e){throw new Error((e as Error).name==='AbortError'?'The service took too long. Check that the backend and MongoDB are running, then retry.':'Cannot reach the server. Check the backend connection, then retry.');}
  if(!res.ok){
   if(res.status===401&&!path.startsWith('/auth/'))window.dispatchEvent(new Event('finsleuth-session-expired'));
   let message=res.status>=500?'Service unavailable. Check MongoDB and the backend, then retry.':'Request failed';
   try{const data=await res.json();if(data.detail)message=typeof data.detail==='string'?data.detail:Array.isArray(data.detail)?data.detail.map((v:{msg?:string})=>v.msg||'Invalid input').join('; '):JSON.stringify(data.detail);}catch{}
   throw new Error(message);
  }
  return res.status===204?{} as T:await res.json();
 }finally{clearTimeout(timer)}
}
export const post=<T=RecordData>(path:string,data:unknown={})=>api<T>(path,{method:'POST',body:JSON.stringify(data)});
export const money=(n:number)=>new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR',maximumFractionDigits:0}).format(n);
export const date=(s:string)=>s?new Date(s).toLocaleString('en-IN',{dateStyle:'medium',timeStyle:'short'}):'—';

export const channelLabel=(value:string)=>({API:"Banking integration (API)",Mobile_App:"Mobile banking",POS_Terminal:"Point of sale",Web:"Internet banking",ATM:"ATM"}[value]||value.replaceAll("_"," "));
