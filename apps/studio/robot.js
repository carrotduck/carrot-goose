import * as T from 'three';
// Photo-based approximation. Dimensions and hinge placement are not factory CAD.
export function createRobot(scene){
 const mat=(c,m=0)=>new T.MeshStandardMaterial({color:c,metalness:m,roughness:.38});
 const white=mat('#f7f8fb',.12),black=mat('#171a20',.08),metal=mat('#959f9e',.8),rubber=mat('#393d3c'),blue=mat('#322632',.3);
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
 function polygon(p,points,z,material=white){const s=new T.Shape();s.moveTo(...points[0]);points.slice(1).forEach(v=>s.lineTo(...v));s.closePath();return mesh(p,new T.ExtrudeGeometry(s,{depth:.002,bevelEnabled:true,bevelSize:.001,bevelThickness:.0008,bevelSegments:3}),[0,0,z],material);}
 // Folded shield panels and waist bracket follow the front reference.

 polygon(root,[[-.077,.353],[-.055,.359],[0,.354],[.055,.359],[.077,.353],[.077,.284],[.052,.272],[0,.259],[-.052,.272],[-.077,.284]],.036);
 plate(root,[0,.311,-.042],.15,.099);box(root,[0,.353,0],[.147,.004,.07]);box(root,[0,.279,-.012],[.118,.004,.052]);box(root,[0,.32,-.017],[.112,.062,.031],black);
 polygon(root,[[-.066,.282],[.066,.282],[.052,.231],[-.052,.231]],.004);
 for(const side of [-1,1]){const wall=plate(root,[side*.076,.315,-.003],.077,.075,[[0,0,.022]]);wall.rotation.y=Math.PI/2;
 const ports=group(root,'side_ports_'+side,[side*.077,.315,-.006]);ports.rotation.y=side*Math.PI/2;
 box(ports,[0,0,0],[.029,.06,.005],black);
 for(const y of [-.019,.004,.022]){box(ports,[0,y,.003],[.023,.014,.007],metal);box(ports,[0,y,.007],[.018,.01,.002],y===.004?blue:black);}
for(const y of [.346,.283,.254])screw(root,side*(y<.26?.047:.069),y,.04,.0018);}

 const pulse=[[-.058,.315,.039],[-.024,.315,.039],[-.015,.334,.039],[0,.291,.039],[.011,.315,.039],[.057,.315,.039]];root.add(new T.Line(new T.BufferGeometry().setFromPoints(pulse.map(p=>new T.Vector3(...p))),new T.LineBasicMaterial({color:0x172623})));
 for(const side of [-1,1]){wire(root,[[side*.061,.34,-.029],[side*.082,.3,-.031],[side*.075,.27,-.01]]);screw(root,side*.067,.352,.04);}
 // Rear camera cable and low display, visible in the supplied rear view.
 wire(root,[[.063,.329,-.045],[.075,.346,-.074],[.012,.311,-.084],[-.055,.329,-.072],[-.026,.387,-.027]]);
 box(root,[0,.247,-.027],[.024,.012,.003],black);
 for(const side of [-1,1]){const rearLabel=label(root,'824HV',[side*.043,.12,-.021],.035,.022);rearLabel.rotation.y=Math.PI;wire(root,[[side*.043,.233,-.024],[side*.056,.191,-.047],[side*.044,.158,-.03],[side*.049,.094,-.025]]);}
 // Bracketed head: yaw ring, U bracket, tilting camera casing.
 cylinder(root,[0,.371,0],.016,.006,black).rotation.x=0;
 joints.yaw=group(root,'PWM2_yaw',[0,.378,0]);box(joints.yaw,[0,0,0],[.049,.004,.034]);for(const side of [-1,1]){const bracket=plate(joints.yaw,[side*.029,.018,0],.033,.044,[[0,.005,.003]]);bracket.rotation.y=Math.PI/2;}

 joints.pitch=group(joints.yaw,'PWM1_pitch',[0,.047,0]);polygon(joints.pitch,[[-.026,.027],[-.021,.035],[.021,.035],[.026,.027],[.026,-.016],[.018,-.03],[-.018,-.03],[-.026,-.016]],.029);
 box(joints.pitch,[0,.012,-.008],[.05,.043,.046],white);box(joints.pitch,[0,-.018,-.006],[.037,.019,.027],black);
 for(const side of [-1,1]){const cheek=polygon(joints.pitch,[[-.025,.035],[.014,.035],[.024,.023],[.023,-.019],[.005,-.024],[-.006,-.011],[-.023,-.009]],0);cheek.rotation.y=side*Math.PI/2;cheek.position.x=side*.029;const rim=box(joints.pitch,[side*.027,.035,-.002],[.003,.01,.047]);rim.rotation.z=side*.3;const screwAxis=group(joints.pitch,'head_side_screws',[side*.031,0,0]);screwAxis.rotation.y=side*Math.PI/2;screw(screwAxis,0,.015,0,.0022);screw(screwAxis,.009,-.009,0,.0022);}
box(joints.pitch,[0,-.027,.001],[.05,.007,.047],white);cylinder(joints.pitch,[0,0,.03],.015,.004,black);cylinder(joints.pitch,[0,0,.034],.0105,.003,blue);cylinder(joints.pitch,[0,0,.038],.0078,.001,blue);for(const x of [-.02,.02])for(const y of [-.032,.032])screw(joints.pitch,x,y,.032,.0016);box(joints.pitch,[0,.022,.031],[.0012,.025,.0007],metal);wire(joints.yaw,[[.021,0,-.017],[.031,.03,-.024],[.02,.049,-.029]]);
 // Arm joints remain explicitly provisional. Thin plates and hollow grippers follow the photo.
 for(const [side,ids]of [[1,['6','7','8']],[-1,['14','15','16']]]){
   let a=group(root,'BUS_'+ids[0],[side*.106,.344,0]);let b=group(a,'BUS_'+ids[1],[0,0,0]);let c=group(b,'BUS_'+ids[2],[0,-.09,0]);ids.forEach((id,i)=>joints[id]=[a,b,c][i]);
   plate(b,[0,0,.026],.049,.034,[[0,0,.007]]);plate(b,[0,0,-.025],.049,.034);box(b,[0,.015,0],[.044,.003,.051]);cylinder(b,[0,0,.029],.007,.005,black);for(const x of [-.017,.017])screw(b,x,0,.029,.002);
   servo(b,[0,-.048,0],.031,.044);plate(b,[0,-.049,.024],.043,.052,[[0,.014,.006],[0,-.014,.006]]);for(const y of [-.036,-.062]){cylinder(b,[0,y,.027],.005,.003,black);for(const x of [-.013,.013])screw(b,x,y,.028,.0018);}
   wire(b,[[side*.016,-.015,-.018],[side*.025,-.05,-.024],[side*.016,-.081,-.012]]);
   cylinder(c,[0,0,.022],.009,.006,black);plate(c,[0,-.012,.022],.032,.034,[[0,.01,.006]]);box(c,[0,-.038,0],[.027,.031,.027],black);
   // A folded palm with a side cutout and three curved finger layers.
   const palm=group(c,'palm_'+side,[0,0,0]);
   const wallShape=new T.Shape();wallShape.moveTo(-.022,-.026);wallShape.lineTo(.022,-.026);wallShape.lineTo(.022,-.093);wallShape.lineTo(.015,-.102);wallShape.lineTo(-.022,-.102);wallShape.closePath();
   const hole=new T.Path();hole.moveTo(-.011,-.057);hole.lineTo(.011,-.057);hole.lineTo(.011,-.075);hole.lineTo(0,-.084);hole.lineTo(-.011,-.075);hole.closePath();wallShape.holes.push(hole);
   for(const z of [-.006,.006,.018]){const hole=new T.Path();hole.absarc(z,-.094,.0023,0,Math.PI*2,true);wallShape.holes.push(hole);}
   const wall=mesh(palm,new T.ExtrudeGeometry(wallShape,{depth:.002,bevelEnabled:true,bevelSize:.0005,bevelThickness:.0004,bevelSegments:2}),[side*.014,0,-.001]);wall.rotation.y=side*Math.PI/2;
   plate(palm,[0,-.039,.023],.03,.026,[[side*.008,0,.0014]]);
   for(const z of [-.016,-.002,.012]){const shape=new T.Shape();const pts=[[-.016,-.061],[-.02,-.095],[-.012,-.11],[.009,-.122],[.017,-.119],[.017,-.114],[.008,-.116],[-.007,-.106],[-.012,-.093],[-.009,-.061]];const mirror=-side;shape.moveTo(pts[0][0]*mirror,pts[0][1]);pts.slice(1).forEach(p=>shape.lineTo(p[0]*mirror,p[1]));shape.closePath();mesh(palm,new T.ExtrudeGeometry(shape,{depth:.003,bevelEnabled:true,bevelSize:.0008,bevelThickness:.0005,bevelSegments:3}),[0,0,z]);}
   const thumb=polygon(palm,[[side*.013,-.065],[side*-.012,-.08],[side*-.018,-.087],[side*-.012,-.093],[side*.015,-.079]],.027);screw(palm,0,-.032,.026,.0018);

 }
 // Exposed hip/knee servos and folded leg brackets, with photographed broad feet.
 for(const side of [-1,1]){let x=side*.043;box(root,[x,.246,0],[.048,.029,.045],white);cylinder(root,[x,.248,.028],.007,.006,black);screw(root,x-side*.018,.248,.029,.002);
   servo(root,[x,.209,.003],.047,.047);plate(root,[x,.179,.033],.055,.04);for(const side2 of [-1,1]){box(root,[x+side2*.028,.199,0],[.002,.075,.06]);for(const y of [.218,.167])screw(root,x+side2*.022,y,.034,.0017);}box(root,[x,.161,0],[.055,.003,.061]);cylinder(root,[x,.154,.033],.01,.004,black);screw(root,x-side*.018,.154,.035,.002);
   servo(root,[x,.116,.016],.048,.047);for(const side2 of [-1,1])box(root,[x+side2*.028,.115,.006],[.002,.064,.062]);box(root,[x,.083,.006],[.057,.002,.063]);box(root,[x,.075,0],[.055,.003,.061]);plate(root,[x,.053,.034],.053,.045,[[0,0,.006]]);for(const y of [.04,.066])screw(root,x,y,.037,.0025);cylinder(root,[x,.052,.037],.006,.003,black);
   const foot=polygon(root,[[-.04,-.045],[.04,-.045],[.04,.032],[.029,.051],[-.029,.051],[-.04,.032]],0);foot.rotation.x=-Math.PI/2;foot.position.set(x,.017,.018);
   for(const edge of [-1,1]){box(root,[x+edge*.039,.02,.012],[.0015,.011,.083]);screw(root,x+edge*.022,.021,.048,.0015);}servo(root,[x,.033,.009],.04,.022);
box(root,[x,.01,.025],[.077,.005,.098],rubber);wire(root,[[x,.25,-.02],[x+side*.025,.17,-.024],[x,.081,-.029]]);
 }
 return {root,joints};
}
