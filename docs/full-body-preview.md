# Full-body motion preview

The model binds 16 bus-servo channels and two head channels. Choose **Legs** above the viewport to edit hip, knee and ankle targets; choose **Head and arms** to return to the upper-body controls. Editing a target updates its joint and child segments immediately. Frames, timeline playback and saved copies use the same channel values.

| Robot side | Hip roll | Hip pitch | Knee pitch | Ankle pitch | Ankle roll |
| --- | --- | --- | --- | --- | --- |
| Left | 5 | 4 | 3 | 2 | 1 |
| Right | 13 | 12 | 11 | 10 | 9 |

The photo-based geometry uses approximate pivot locations and display directions. The straight-leg display reference uses knee values 303 and 696; it is a visualization reference, not a device reset command. Axis, direction and offset can be inspected in Joint mapping. Numeric encoding bounds are not calibrated physical travel limits.

A hip rotation carries the thigh, shin and foot; a knee rotation carries the shin and foot; ankle rotations orient the foot. The torso stays fixed in world space. This supports full-body joint preview, but does not simulate walking displacement, balance, ground contact or actuator forces. Optional imported channels 17 and 18 remain in sequence data and are not assigned invented joints.
