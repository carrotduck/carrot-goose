# Joint mapping and editing

The model binds 16 body joints and two head channels. Editing a target updates the corresponding joint and its child segments immediately. Frames, timeline playback and saved copies use the same values.

| Body region | Robot left | Robot right |
| --- | --- | --- |
| Shoulder pitch | Bus 8 | Bus 16 |
| Shoulder lateral movement | Bus 7 | Bus 15 |
| Elbow | Bus 6 | Bus 14 |
| Hip roll | Bus 5 | Bus 13 |
| Hip pitch | Bus 4 | Bus 12 |
| Knee pitch | Bus 3 | Bus 11 |
| Ankle pitch | Bus 2 | Bus 10 |
| Ankle roll | Bus 1 | Bus 9 |
| Head pitch | PWM 1 | — |
| Head yaw | PWM 2 | — |

Select a frame, adjust its targets and choose **Update** to save an edited copy. Use the viewport selector to show the controls for the desired body region, or open **Joint values** to inspect all channels together. Scrub the timeline or play the sequence to review the result.

The photo-based geometry uses approximate pivot locations and display directions. Axis, direction and offset are available in **Joint mapping**. Numeric encoding bounds require physical calibration before use on a robot.

The torso stays fixed in world space. The preview shows joint trajectories. Optional imported channels 17 and 18 remain in sequence data.
