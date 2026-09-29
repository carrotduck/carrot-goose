import * as T from 'three';
// Photo-based approximation. Dimensions and hinge placement are not factory CAD.
export function createRobot(scene){
 const mat=(c,m=0)=>new T.MeshStandardMaterial({color:c,metalness:m,roughness:.38});
 const white=mat('#e4e6e1',.45),black=mat('#202424',.15),metal=mat('#959f9e',.8),rubber=mat('#393d3c'),blue=mat('#183740',.5);
 const root=new T.Group();scene.add(root);const joints={};
 function group(p,n,xyz){let g=new T.Group();g.name=n;g.position.set(...xyz);p.add(g);return g;}
 function mesh(p,geo,xyz,material=white){let m=new T.Mesh(geo,material);m.position.set(...xyz);m.castShadow=true;m.receiveShadow=true;p.add(m);return m;}
 const box=(p,pos,size,m=white)=>mesh(p,new T.BoxGeometry(...size),pos,m);
 function cylinder(p,pos,r,len,m=metal){let x=mesh(p,new T.CylinderGeometry(r,r,len,32),pos,m);x.rotation.x=Math.PI/2;return x;}
 function plate(p,pos,w,h,holes=[],m=white){let s=new T.Shape();const r=.005;s.moveTo(-w/2+r,-h/2);s.lineTo(w/2-r,-h/2);s.quadraticCurveTo(w/2,-h/2,w/2,-h/2+r);s.lineTo(w/2,h/2-r);s.quadraticCurveTo(w/2,h/2,w/2-r,h/2);s.lineTo(-w/2+r,h/2);s.quadraticCurveTo(-w/2,h/2,-w/2,h/2-r);s.lineTo(-w/2,-h/2+r);s.quadraticCurveTo(-w/2,-h/2,-w/2+r,-h/2);for(const [x,y,hr]of holes){let path=new T.Path();path.absarc(x,y,hr,0,Math.PI*2,true);s.holes.push(path);}return mesh(p,new T.ExtrudeGeometry(s,{depth:.002,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:.0005,bevelThickness:.0004}),pos,m);}
 function screw(p,x,y,z,r=.0025){cylinder(p,[x,y,z],r,.0015,black);box(p,[x,y,z+.001],[r,.00065,.0004],metal);}
 function label(p,text,pos,w,h){let c=document.createElement('canvas');c.width=256;c.height=128;let ctx=c.getContext('2d');ctx.fillStyle='#242826';ctx.fillRect(0,0,256,128);ctx.fillStyle='#e0dfcc';ctx.font='bold 34px sans-serif';ctx.fillText(text,12,52);ctx.font='18px sans-serif';ctx.fillText('BUS SERVO',12,91);let tex=new T.CanvasTexture(c);tex.colorSpace=T.SRGBColorSpace;return mesh(p,new T.PlaneGeometry(w,h),pos,new T.MeshStandardMaterial({map:tex,roughness:.7}));}
 function servo(p,pos,w=.035,h=.049){box(p,pos,[w,h,.035],black);box(p,[pos[0],pos[1]+h/2,pos[2]],[w+.006,.003,.038],black);label(p,'824HV',[pos[0],pos[1],pos[2]+.0178],w*.8,h*.5);}
 function wire(p,points){let curve=new T.CatmullRomCurve3(points.map(v=>new T.Vector3(...v)));return mesh(p,new T.TubeGeometry(curve,24,.0015,6,false),[0,0,0],rubber);}
 // Torso sheet metal, exposed side cavity and circuit enclosure.
 plate(root,[0,.311,.036],.156,.104);plate(root,[0,.311,-.035],.15,.1);box(root,[0,.352,0],[.147,.005,.07]);box(root,[0,.265,0],[.123,.005,.061]);box(root,[0,.315,-.015],[.115,.07,.038],black);
 const pulse=[[-.058,.315,.039],[-.024,.315,.039],[-.015,.334,.039],[0,.291,.039],[.011,.315,.039],[.057,.315,.039]];root.add(new T.Line(new T.BufferGeometry().setFromPoints(pulse.map(p=>new T.Vector3(...p))),new T.LineBasicMaterial({color:0x172623})));
 for(const side of [-1,1]){wire(root,[[side*.061,.34,-.029],[side*.082,.3,-.031],[side*.075,.27,-.01]]);screw(root,side*.067,.352,.04);}
 // Bracketed head: yaw ring, U bracket, tilting camera casing.
 cylinder(root,[0,.371,0],.016,.006,black).rotation.x=0;
 joints.yaw=group(root,'PWM2_yaw',[0,.378,0]);box(joints.yaw,[0,0,0],[.049,.004,.034]);for(const side of [-1,1])box(joints.yaw,[side*.025,.018,0],[.003,.036,.036]);
 joints.pitch=group(joints.yaw,'PWM1_pitch',[0,.047,0]);plate(joints.pitch,[0,0,.029],.072,.068,[[0,0,.02]]);box(joints.pitch,[0,0,-.008],[.063,.059,.051],white);box(joints.pitch,[0,-.027,.001],[.063,.01,.054],white);cylinder(joints.pitch,[0,0,.03],.0205,.006,black);cylinder(joints.pitch,[0,0,.034],.0145,.006,blue);cylinder(joints.pitch,[0,0,.038],.010,.0015,black);for(const x of [-.028,.028])for(const y of [-.025,.025])screw(joints.pitch,x,y,.032,.0016);wire(joints.yaw,[[.021,0,-.017],[.031,.03,-.024],[.02,.049,-.029]]);
 // Arm joints remain explicitly provisional. Thin plates and hollow grippers follow the photo.
 for(const [side,ids]of [[1,['6','7','8']],[-1,['14','15','16']]]){
   let a=group(root,'BUS_'+ids[0],[side*.106,.344,0]);let b=group(a,'BUS_'+ids[1],[0,0,0]);let c=group(b,'BUS_'+ids[2],[0,-.09,0]);ids.forEach((id,i)=>joints[id]=[a,b,c][i]);
   plate(b,[0,0,.026],.049,.034,[[0,0,.007]]);plate(b,[0,0,-.025],.049,.034);box(b,[0,.015,0],[.044,.003,.051]);cylinder(b,[0,0,.029],.007,.005,black);for(const x of [-.017,.017])screw(b,x,0,.029,.002);
   servo(b,[0,-.048,0],.031,.044);plate(b,[0,-.049,.024],.043,.052,[[0,.014,.006],[0,-.014,.006]]);for(const y of [-.036,-.062]){cylinder(b,[0,y,.027],.005,.003,black);for(const x of [-.013,.013])screw(b,x,y,.028,.0018);}
   wire(b,[[side*.016,-.015,-.018],[side*.025,-.05,-.024],[side*.016,-.081,-.012]]);
   cylinder(c,[0,0,.022],.009,.006,black);plate(c,[0,-.012,.022],.032,.034,[[0,.01,.006]]);box(c,[0,-.038,0],[.027,.031,.027],black);
   let shape=new T.Shape();const pts=[[-.02,-.035],[-.024,-.085],[-.019,-.102],[.007,-.118],[.025,-.091],[.019,-.091],[.004,-.106],[-.01,-.093],[-.014,-.082],[-.01,-.035]];const mirror=-side;shape.moveTo(pts[0][0]*mirror,pts[0][1]);pts.slice(1).forEach(p=>shape.lineTo(p[0]*mirror,p[1]));shape.closePath();let grip=mesh(c,new T.ExtrudeGeometry(shape,{depth:.003,bevelEnabled:true,bevelSize:.0006,bevelThickness:.0005,bevelSegments:2}),[0,0,.019]);
   for(let z of [.008,-.003]){let clone=grip.clone();clone.position.z=z;c.add(clone);}box(c,[.012*side,-.039,.008],[.006,.008,.031]);
 }
 // Exposed hip/knee servos and folded leg brackets, with photographed broad feet.
 for(const side of [-1,1]){let x=side*.043;box(root,[x,.246,0],[.048,.029,.045],white);cylinder(root,[x,.248,.028],.007,.006,black);screw(root,x-side*.018,.248,.029,.002);
   servo(root,[x,.205,0],.038,.057);plate(root,[x,.185,.031],.055,.049);box(root,[x,.161,0],[.055,.003,.061]);cylinder(root,[x,.154,.033],.01,.004,black);screw(root,x-side*.018,.154,.035,.002);
   servo(root,[x,.116,0],.038,.055);plate(root,[x,.096,.033],.055,.041);box(root,[x,.075,0],[.055,.003,.061]);plate(root,[x,.053,.034],.053,.045,[[0,0,.006]]);for(const y of [.04,.066])screw(root,x,y,.037,.0025);cylinder(root,[x,.052,.037],.006,.003,black);
   plate(root,[x,.019,0],.08,.10).rotation.x=-Math.PI/2;box(root,[x,.01,.025],[.075,.009,.1],rubber);wire(root,[[x,.25,-.02],[x+side*.025,.17,-.024],[x,.081,-.029]]);
 }
 return {root,joints};
}
