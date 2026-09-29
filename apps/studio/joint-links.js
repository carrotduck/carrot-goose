import * as T from 'three';
const s=window.studio,view=document.getElementById('view'),ns='http://www.w3.org/2000/svg';
const svg=document.createElementNS(ns,'svg');svg.id='joint-links';svg.setAttribute('aria-hidden','true');view.append(svg);
let active=null;
const entries=Object.entries(s.joints).map(([id,joint])=>{
 const line=document.createElementNS(ns,'path'),dot=document.createElementNS(ns,'circle');line.setAttribute('class','joint-link');dot.setAttribute('class','joint-dot');dot.setAttribute('r','3');svg.append(line,dot);
 const card=document.querySelector('.servo-'+id);
 const activate=()=>{active=id;document.querySelectorAll('.servo-card').forEach(el=>el.classList.toggle('active',el===card));};card.addEventListener('pointerdown',activate);card.addEventListener('focusin',activate);document.getElementById('edit-'+id).addEventListener('focus',activate);
 return {id,joint,line,dot,card};
});
function tick(){
 s.scene.updateMatrixWorld(true);s.camera.updateMatrixWorld(true);
 const rect=view.getBoundingClientRect();
 for(const {id,joint,line,dot,card} of entries){
  const p=joint.localToWorld(new T.Vector3(0,['7','15'].includes(id)?-.036:0,.027)).project(s.camera),cr=card.getBoundingClientRect();
  const x=(p.x+1)*rect.width/2,y=(1-p.y)*rect.height/2;
  const left=cr.left+cr.width/2<rect.left+rect.width/2;
  const sx=(left?cr.right:cr.left)-rect.left,sy=cr.top+cr.height/2-rect.top;
  line.setAttribute('d',`M${sx},${sy} L${sx+(left?14:-14)},${sy} L${x},${y}`);line.classList.toggle('active',id===active);dot.setAttribute('cx',x);dot.setAttribute('cy',y);
  line.style.display=dot.style.display=p.z>1||p.z< -1?'none':'';
 }
 requestAnimationFrame(tick);
}requestAnimationFrame(tick);
