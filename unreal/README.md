# Unreal preview

Open `CarrotGoose.uproject` in UE 5.7. Enable the Python and Editor Scripting plugins, then run `Content/Python/build_studio.py` from the editor's Python console. It reads `apps/studio/library.json`, creates a block-model scene and Level Sequences, and stops if the scene already exists. After generation, run `Content/Python/open_studio.py` to open the first sequence.

This directory contains the Unreal Engine preview model. The detailed model and language planner are in the browser workbench.
