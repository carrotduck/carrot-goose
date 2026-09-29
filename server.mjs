import {createWorkbenchRouter} from './integrations/duck/workbench.js';
import express from 'express';
import {fileURLToPath} from 'node:url';
import {createSimulationRouter} from './integrations/duck/simulation.js';
const app=express();app.use(express.json({limit:'150kb'}));
const port=Number(process.env.PORT||8770);
async function generate(messages){
 if(!process.env.LLM_API_KEY)throw Error('Set LLM_API_KEY to use motion planning');
 const base=(process.env.LLM_BASE_URL||'https://api.deepseek.com').replace(/\/$/,'');
 const r=await fetch(base+'/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${process.env.LLM_API_KEY}`},body:JSON.stringify({model:process.env.LLM_MODEL||'deepseek-chat',messages,max_tokens:2200,temperature:.25}),signal:AbortSignal.timeout(45000)});
 if(!r.ok)throw Error('Provider request failed');const j=await r.json();return {text:j.choices?.[0]?.message?.content||''};
}
app.use('/api/workbench',createWorkbenchRouter({generate,origins:['http://localhost:'+port,'http://127.0.0.1:'+port]}));
app.get('/api/health',(_req,res)=>res.json({ok:true,app:'carrot-goose'}));
app.use(express.static(fileURLToPath(new URL('./apps/studio/',import.meta.url))));
app.listen(port,'127.0.0.1',()=>console.log(`Carrot Goose: http://127.0.0.1:${port}`));
