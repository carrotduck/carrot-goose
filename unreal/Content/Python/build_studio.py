"""UE 5.7 editor-only generator. Creates assets in this isolated project only."""
import unreal as u
import json, math, traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
data=json.loads((ROOT/'apps/studio/library.json').read_text('utf-8'))
tools=u.AssetToolsHelpers.get_asset_tools()
actors=u.get_editor_subsystem(u.EditorActorSubsystem)
levels=u.get_editor_subsystem(u.LevelEditorSubsystem)
def build():
    if u.EditorAssetLibrary.does_asset_exist('/Game/CarrotGoose'):
        raise RuntimeError('Studio already exists. Preserve edited assets; generate into a fresh project instead.')
    levels.new_level('/Game/CarrotGoose')
    def mat(name,col):
        m=tools.create_asset(name,'/Game/Materials',u.Material,u.MaterialFactoryNew())
        e=u.MaterialEditingLibrary.create_material_expression(m,u.MaterialExpressionConstant3Vector,0,0)
        e.set_editor_property('constant',u.LinearColor(*col,1))
        u.MaterialEditingLibrary.connect_material_property(e,'',u.MaterialProperty.MP_BASE_COLOR)
        u.MaterialEditingLibrary.recompile_material(m)
        return m
    ivory=mat('Ivory',(.78,.8,.72)); dark=mat('Dark',(.025,.05,.04)); accent=mat('Sage',(.13,.38,.27))
    cube=u.load_asset('/Engine/BasicShapes/Cube.Cube')
    sphere=u.load_asset('/Engine/BasicShapes/Sphere.Sphere')
    joints={}; locs={}
    def obj(name,pos,parent=None,size=None,material=None,mesh=None):
        a=actors.spawn_actor_from_class(u.StaticMeshActor,u.Vector())
        a.set_actor_label(name);a.static_mesh_component.set_mobility(u.ComponentMobility.MOVABLE)
        a.static_mesh_component.set_collision_enabled(u.CollisionEnabled.NO_COLLISION)
        if size:
            a.static_mesh_component.set_static_mesh(mesh or cube)
            a.static_mesh_component.set_material(0,material or ivory)
        if parent:a.attach_to_actor(parent,'',u.AttachmentRule.KEEP_RELATIVE,u.AttachmentRule.KEEP_RELATIVE,u.AttachmentRule.KEEP_RELATIVE,False)
        a.set_actor_relative_location(u.Vector(*pos),False,False)
        if size:a.set_actor_relative_scale3d(u.Vector(*(v/100 for v in size)))
        return a
    root=obj('XIAOJI_SIM_ONLY_UNCALIBRATED',[0,0,0])
    obj('Torso',[0,0,31],root,[15.8,6.5,11.6]);obj('Electronics',[0,-4,31],root,[12.7,4,9],dark)
    # UE centimeters: x = robot left; y = front; z = up.
    for side,ids in [(1,['6','7','8']),(-1,['14','15','16'])]:
        a=obj('BUS_'+ids[0]+'_PROVISIONAL',[side*10.7,0,34.5],root)
        b=obj('BUS_'+ids[1]+'_PROVISIONAL',[0,0,0],a)
        c=obj('BUS_'+ids[2]+'_PROVISIONAL',[0,0,-9.2],b)
        for sid,v,p in [(ids[0],a,[side*10.7,0,34.5]),(ids[1],b,[0,0,0]),(ids[2],c,[0,0,-9.2])]:joints[sid]=v;locs[sid]=p
        obj('Shoulder',[0,0,0],b,[5.2,5.2,3.8]);obj('UpperMotor',[0,0,-5.2],b,[3.8,4.2,6.4],dark);obj('UpperPlate',[0,2.6,-5.2],b,[4.5,.8,6.4]);obj('Pivot',[0,2.8,0],c,[2.6,.8,2.6],dark,sphere)
        obj('Forearm',[0,0,-4.1],c,[3.6,2.8,7.2]);obj('Palm',[0,0,-8.5],c,[4.2,2.3,1.8])
        for x in [-1.5,-.5,.5,1.5]:obj('Finger',[x,.3,-10.8],c,[.5,1.7,2.7])
        x=side*4.5
        for name,p,size,m in [('Hip',[x,0,23.2],[4.6,5.4,3.1],ivory),('Thigh',[x,0,19.4],[4.2,4.9,6.1],dark),('ThighPlate',[x,3,19],[5.4,.8,6.9],ivory),('Shin',[x,0,11],[4.3,5,6.4],dark),('ShinPlate',[x,3,10.6],[5.5,.8,6.6],ivory),('Ankle',[x,0,5.2],[5.5,4.5,3.5],ivory),('Foot',[x,1.6,2],[8.3,10.5,1.6],ivory)]:obj(name,p,root,size,m)
    joints['yaw']=obj('PWM2_YAW',[0,0,39],root);locs['yaw']=[0,0,39]
    obj('Neck',[0,0,0],joints['yaw'],[4,3.8,3.5])
    joints['pitch']=obj('PWM1_PITCH',[0,0,4.3],joints['yaw']);locs['pitch']=[0,0,4.3]
    obj('Head',[0,0,0],joints['pitch'],[7.7,6.1,7.6]);obj('Camera',[0,3.5,0],joints['pitch'],[4.4,1.2,4.4],dark,sphere)
    obj('Floor',[0,0,-.5],None,[220,220,1],accent)
    light=actors.spawn_actor_from_class(u.DirectionalLight,u.Vector(40,70,100),u.Rotator(-50,-100,0));light.light_component.set_intensity(3)
    sky=actors.spawn_actor_from_class(u.SkyLight,u.Vector(0,0,90));sky.light_component.set_intensity(1.5)
    fill=actors.spawn_actor_from_class(u.PointLight,u.Vector(20,80,65));fill.set_actor_label('XJ_Fill');fill.point_light_component.set_intensity(1.0);fill.point_light_component.set_attenuation_radius(250)
    cam=actors.spawn_actor_from_class(u.CameraActor,u.Vector(80,175,70));cam.set_actor_rotation(u.MathLibrary.find_look_at_rotation(cam.get_actor_location(),u.Vector(0,0,24)),False);cam.camera_component.set_field_of_view(35)
    levels.save_current_level()
    wanted=[a['name'] for a in data['actions'][:6]]
    manifest=[]
    for n,action in enumerate(a for a in data['actions'] if a['name'] in wanted):
        seq=tools.create_asset('Take_'+str(n).zfill(2),'/Game/Sequences',u.LevelSequence,u.LevelSequenceFactoryNew())
        seq.set_display_rate(u.FrameRate(100,1));end=math.ceil(action['duration']*100)+1;seq.set_playback_end(end)
        for sid,actor in joints.items():
            binding=seq.add_possessable(actor);track=binding.add_track(u.MovieScene3DTransformTrack);section=track.add_section();section.set_range(0,end)
            channels=section.get_channels_by_type(u.MovieSceneScriptingDoubleChannel)
            m=data['mapping'][sid]
            # Basis swap from browser Y-up to UE Z-up is a reflection: negate axis angles.
            channel={'x':3,'y':5,'z':4}[m['axis']]
            for i,v in enumerate(locs[sid]+[0,0,0]+[1,1,1]):channels[i].set_default(float(v))
            for f in action['frames']:
                for t,p in [(f['start'],f['from']),(f['start']+f['move'],f['target']),(f['start']+f['duration'],f['target'])]:
                    angle=-(p[sid]-m['neutral'])*m['degrees_per_unit']*m['sign']
                    if sid=='7':angle-=math.degrees(.1)
                    if sid=='15':angle+=math.degrees(.1)
                    channels[channel].add_key(u.FrameNumber(round(t*100)),angle,interpolation=u.MovieSceneKeyInterpolation.LINEAR)
        camera_binding=seq.add_possessable(cam)
        cut=seq.add_track(u.MovieSceneCameraCutTrack).add_section();cut.set_range(0,end)
        bid=u.MovieSceneObjectBindingID();bid.set_editor_property('guid',camera_binding.get_id());cut.set_camera_binding_id(bid)
        u.EditorAssetLibrary.save_loaded_asset(seq)
        manifest.append({'asset':seq.get_path_name(),'action':action['name'],'seconds':action['duration'],'bindings':len(seq.get_bindings())})
    u.EditorAssetLibrary.save_directory('/Game',True,True)
    levels.save_current_level()
    (ROOT/'ue-build-result.json').write_text(json.dumps({'success':True,'sequences':manifest},ensure_ascii=False,indent=2),'utf-8')
try:build()
except Exception:
    (ROOT/'ue-build-error.txt').write_text(traceback.format_exc(),'utf-8')
    raise
