import unreal as u
u.EditorPythonScripting.set_keep_python_script_alive(True)
u.get_editor_subsystem(u.LevelEditorSubsystem).load_level('/Game/CarrotGoose')
u.LevelSequenceEditorBlueprintLibrary.open_level_sequence(u.load_asset('/Game/Sequences/Take_00'))
u.LevelSequenceEditorBlueprintLibrary.set_current_time(0)
camera=next(a for a in u.get_editor_subsystem(u.EditorActorSubsystem).get_all_level_actors() if isinstance(a,u.CameraActor))
u.EditorLevelLibrary.set_level_viewport_camera_info(camera.get_actor_location(),camera.get_actor_rotation())
