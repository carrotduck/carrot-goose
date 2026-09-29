# TonyPi rehearsal modules

`tonypi_motion_catalog.py` compiles arm gestures and their transitions. `tonypi_motion_cache.py` binds a compiled trajectory to a starting pose. The perception and vision modules support camera targets; the registry, temperature and control modules belong to the physical rehearsal installation.

Run the Python tests from the repository root with `python -m unittest discover -s robot -p "test_*.py"`. Camera and physical execution require the TonyPi system image and its SDK. The modules retain standard installation paths such as `/home/pi/TonyPi` and the rehearsal service conventions under `/home/pi/yushi`; adapt these in the robot installation rather than assuming a new device matches them.

There are different historical left/right conventions in the physical catalog and browser model. Use servo IDs when comparing them, and calibrate each axis on the actual robot before connecting exported poses to an executor. A range observed in an action is not a mechanical limit.

The full device service, personal connection settings and original action-file backups are maintained outside this repository. The public modules provide the motion and perception components used by that service.
