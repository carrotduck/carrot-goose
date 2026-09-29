export const IDS=['6','7','8','14','15','16','pitch','yaw'];
export const IDLE={'6':535,'7':803,'8':690,'14':425,'15':200,'16':275,pitch:1500,yaw:1530};
export const BOUNDS=Object.fromEntries(IDS.map(k=>[k,k==='pitch'||k==='yaw'?[1000,2000]:[0,1000]]));
export function number(v,min,max,name){if(typeof v!=='number'||!Number.isFinite(v)||v<min||v>max)throw Error(`${name} 必须在 ${min}–${max} 之间`);return v;}
export function pose(value,base=IDLE){if(!value||typeof value!=='object'||Array.isArray(value))throw Error('姿势格式错误');let p={...base};for(const [k,v]of Object.entries(value)){if(!IDS.includes(k))throw Error(`不支持关节 ${k}；当前仅双臂和头部`);p[k]=Math.round(number(v,...BOUNDS[k],k));}return p;}
export function makeMotion(name,steps,initial=IDLE,source='manual'){
 if(!Array.isArray(steps)||steps.length<1||steps.length>100)throw Error('需要1–100帧');let prev=pose(initial),t=0;const frames=steps.map(s=>{let target=pose(s.pose??s.target,prev),move=number(s.move_s??s.move,0,10,'运动时长'),hold=number(s.hold_s??Math.max(0,(s.duration??move)-move),0,10,'停留时长'),f={from:prev,target,start:t,move,duration:move+hold,label:String(s.label||'姿势').slice(0,100),gate:null,utterance:null};if(f.duration<=0)throw Error("动作时长必须大于0");prev=target;t+=f.duration;return f;});if(t>120)throw Error('单段模拟最长120秒');return {name:String(name||'新动作').slice(0,100),frames,initial:pose(initial),duration:t,status:'模拟候选 · 未验证机械路径',source};
}
export function ranges(a){return Object.fromEntries(IDS.map(k=>{const values=[a.initial[k],...a.frames.map(f=>f.target[k])];return [k,[Math.min(...values),Math.max(...values)]];}));}
export function compilePlan(spec,library,current){
 if(!spec||typeof spec!=='object'||Array.isArray(spec))throw Error('模型输出不是动作对象');if(spec.unsupported_reason)throw Error(String(spec.unsupported_reason).slice(0,300));
 let result;
 if(spec.base_action){let base=spec.base_action==='current'?current:library.actions.find(a=>a.name===spec.base_action);if(!base)throw Error('动作库中没有这个动作');let scale=number(spec.amplitude??1,.1,1.5,'幅度倍率'),speed=number(spec.speed??1,.25,2,'速度倍率'),repeat=number(spec.repetitions??1,1,3,'重复次数');if(!Number.isInteger(repeat))throw Error('重复次数应为整数');let initial=Object.fromEntries(IDS.map(k=>[k,base.initial[k]??IDLE[k]]));let steps=[];for(let i=0;i<repeat;i++)for(const f of base.frames){let target=Object.fromEntries(IDS.map(k=>[k,Math.round(initial[k]+((f.target[k]??initial[k])-initial[k])*scale)]));steps.push({pose:target,move_s:Math.max(.05,f.move/speed),hold_s:Math.max(0,(f.duration-f.move)/speed),label:f.label});}result=makeMotion(spec.name||base.name,steps,initial,'llm_simulation');
 }else result=makeMotion(spec.name,spec.steps,current?.initial??IDLE,'llm_simulation');
 return {...result,explanation:String(spec.explanation||'已生成模拟候选。').slice(0,600),ranges:ranges(result),hardware_executed:false,mode:'simulation_only'};
}
