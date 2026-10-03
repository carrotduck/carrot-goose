# Physical expression for an AI companion

When does a hug gesture feel like a response to the person, rather than an action played beside the dialogue? Carrot Goose explores this question through a physical extension of a web companion.

Using TonyPi, I designed interaction sequences and connected webpage dialogue cues to a local controller. I also built a browser workbench with AI-assisted coding to inspect movement before physical testing.

## What the workbench adds

The original TonyPi editor makes joint IDs and per-frame values available for action programming. The new workbench retains that structure and adds a rotatable model, timeline inspection, editable copies and language-assisted motion drafts. This makes it possible to compare the amplitude of a first reach with a stronger invitation, adjust a pause after a reply, and review the return into the next gesture.

The procedural model was refined using photographs of the physical robot. Head, arm and leg targets drive a hierarchical joint model for full-body pose review.

## System architecture

The [architecture diagram](diagrams/architecture.svg) shows the demonstrated rehearsal path: web dialogue, cue-based sequence coordination, local command checks, physical movement and execution feedback. The [authoring diagram](diagrams/workflow.svg) shows the separate motion-planning path used by the browser workbench.

The motion planner receives the requested change and the current sequence. It returns structured frame targets and timing that are validated before preview. A reviewed handoff is required to adapt exported data to the physical controller. Browser playback completion and robot execution completion are separate records.

## Iteration on the robot

Physical rehearsals exposed starting-pose differences, arm-to-leg clearance and movement under load. Those observations informed revisions to transitions and return paths. A virtual preview provides another place to inspect a sequence while keeping physical testing part of the process.

## Further research

A proposed comparison would keep the reply and hug motion unchanged while placing the arm raise before or after the reply. Participants would describe whether the gesture felt responsive to the exchange and explain their interpretation. The comparison would examine the immediate exchange before extending the work to recognition across repeated conversations.
