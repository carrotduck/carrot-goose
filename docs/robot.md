# TonyPi rehearsal modules

`tonypi_motion_catalog.py` compiles arm gestures and their transitions. `tonypi_motion_cache.py` binds a compiled trajectory to a starting pose. The perception and vision modules support camera targets; the registry, temperature and control modules belong to the physical rehearsal installation.

| Component | Role in the project |
| --- | --- |
| `tonypi_motion_catalog.py` | Composes arm gestures and return transitions |
| `tonypi_motion_cache.py` | Associates a trajectory with its starting pose |
| `tonypi_perception.py`, `tonypi_vision.py` | Camera target observations and vision support |
| `tonypi_seek.py` | Head orientation and target-seeking support |
| `tonypi_registry.py` | Registers available physical actions |
| `tonypi_control.py` | Control and physical command checks |
| `tonypi_temperature.py` | Temperature-related device checks |
| `protocol/` | Shared command structures used by these components |

The physical development sessions included head tracking, arm gestures, coordinated head-and-arm sequences and short voice cues. Individual trajectories required revision during rehearsal. The 137-item hosted preview library is a collection of motion data, not a statement that every item passed a physical test. The public Python tests exercise software behavior without moving hardware.

Run the Python tests from the repository root with `python -m unittest discover -s robot -p "test_*.py"`. Camera and physical execution require the TonyPi system image and its SDK. The modules retain standard installation paths such as `/home/pi/TonyPi` and the rehearsal service conventions under `/home/pi/yushi`; adapt these in the robot installation rather than assuming a new device matches them.

There are different historical left/right conventions in the physical catalog and browser model. Use servo IDs when comparing them, and calibrate each axis on the actual robot before connecting exported poses to an executor. A range observed in an action is not a mechanical limit.

The device client is included as `robot/yushi_client.py`; the scene runner and webpage transport are in `robot/rehearsal`. See [rehearsal setup](rehearsal.md). Personal connection settings and original manufacturer action backups are excluded.
