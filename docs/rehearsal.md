# Physical rehearsal runtime

The robot demonstration combines webpage cues, head and arm movement, short voice cues and execution feedback. The scene runner is distinct from the independent browser workbench.

## Components

- `robot/yushi_client.py`: device command polling, motion/perception dispatch, speech synthesis and durable completion receipts. Configure its service and credentials through environment variables; `robot/secrets.env.example` lists the connection fields.
- `robot/rehearsal/run_scene_take.py`: one-take orchestration with explicit execution modes.
- `scene_sequence.py`: ordered scene state, event validation and per-action completion.
- `scene_transport.py`: authenticated webpage events and correlated execution acknowledgements.
- `scene_hardware.py`: servo transport, coordinated targets and WAV playback.
- `scene_camera.py` and `live_gaze.py`: camera observations and head-following support.
- `rehearsal_listener.py`: claims a webpage Start and launches a take on the configured robot installation.

The listener and persistent client are alternative execution paths. Their installation-specific ownership rules prevent concurrent controllers from writing to the device. They are not automatically launched by `npm start`.

## Event flow

The web companion exposes `/api/chat/:userId/rehearsal/body-events`. `WebLink` reads events associated with a take and sends execution acknowledgements to that same endpoint. `Scene` checks the take, user, sequence, expiry and matching message identifiers before advancing. Text cues, withdrawal cues and physical completion have separate meanings. An authored withdrawal cue is explicitly marked as choreography rather than a camera observation.

The companion web backend belongs to the separate [Carrot Duck project](https://github.com/carrotduck/carrot-duck). These Python components expect its rehearsal event contract; they do not provide a replacement chat server.

## Installation inputs

The physical runtime targets the TonyPi Linux image and its Hiwonder SDK. Install the Python requirements and use the matching device SDK, OpenCV and MediaPipe versions from that image. The implementation retains installation paths under `/home/pi/TonyPi` and `/home/pi/yushi`.

For the persistent client, copy `secrets.env.example` to `secrets.env` on the device and supply your own endpoint and credentials. For webpage rehearsal, the listener reads a local `.scene-session.json` containing `user_id` and `token`; keep that file outside version control. A valid companion session is used for physical rehearsal only. The standalone workbench requires no companion login.

Voice playback expects `robot/rehearsal/audio/mm.wav` and `hey.wav` (mono, 16-bit PCM at 22050 Hz). Supply voice assets you have permission to use. The release includes audio playback code and a synthetic offline test fixture; personal voice recordings are not bundled.

Before running `full_scene_candidate.json`, review servo IDs, initial pose, motion ranges and installed action files for the device. Adapt exported frames to the controller's expected format.

For offline checks, run the commands in the repository README. `run_scene_take.py --help` describes available modes without running a take. Hardware execution requires an explicit `--run`; do not treat a successful software test as physical commissioning.
