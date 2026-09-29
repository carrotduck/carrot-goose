# Carrot Goose

Carrot Goose is a physical companion project built on TonyPi, connecting hand-following, coordinated head and arm gestures, and speech to a web conversation.

I designed and tested interaction sequences in which the robot shifts attention, responds playfully and offers a hug. The demonstration uses an authored exchange; live hand-following was also tested separately. A supporting 3D workbench helps me review poses, edit timing and prepare movements for rehearsal.

[Open the workbench](https://carrotgoose.online/) · [Watch the demonstration](https://youtu.be/SYHgv-Zi3hE) · [Carrot Duck](https://github.com/carrotduck/carrot-duck)

![Carrot Goose motion workbench](docs/workbench.png)

[Project website](https://shiruifu.online/projects/embodied-robot/) presents the design question and development process. The recorded robot demonstration predates the current browser workbench.

## Motion rehearsal

Choose a motion, scrub its timeline and edit a frame's joint targets. The workbench shows the values used across the selected sequence. A language request can generate a new movement or change the amplitude and speed of the current one.

Moving a slider previews the corresponding joint immediately. Connector lines identify the controlled joint as the camera moves. Select **Update** to save the preview as a frame. The separate **Offset** field adjusts the model's calibration preview and is exported with the mapping; it is not a second joint axis.

Try “Raise an arm, nod twice, then return” or “Reduce the current amplitude to 70% and halve the speed.” The interface opens in English and can be switched to Chinese.

The working installation contains 137 sequences imported from the robot's cached library and rehearsal material. This repository includes an authored greeting and the demonstration choreography. Import your own TonyPi action folder to build a local library:

```sh
python tools/import_actions.py /path/to/ActionGroups
```

The importer reads all servo channels in each `.d6a` file. The current 3D model animates six arm channels and two head channels; the remaining values stay in the imported data. The photo-based model is intended for inspecting timing and poses. Physical joint directions and travel limits require calibration.

## Robot project

The recorded demonstration connects webpage dialogue cues to an authored sequence of attention, a playful reply and an invitation to hug. The local controller returns completion or interruption feedback, while short voice cues play through the attached audio device.

| Component | Documentation |
| --- | --- |
| Motion and perception | [Robot modules](docs/robot.md) |
| Conversation connection | [Carrot Duck integration](docs/integration.md) |
| Dialogue and gesture sequence | [Performance score](docs/performance.md) |

## Run

Install Node.js 22 or newer, then:

```sh
npm ci
npm start
```

Open `http://127.0.0.1:8770`. Editing and playback work locally. For language planning, copy `.env.example` to `.env`, fill in your provider credentials, and start with:

```sh
node --env-file=.env server.mjs
```

The local server listens on this computer only. The hosted workbench uses the existing Carrot Duck account. [Integration notes](docs/integration.md) explain that connection and the dedicated Carrot Goose domain.

## Project files

| Directory | Contents |
| --- | --- |
| `apps/studio` | Browser model, frame editor and motion validation |
| `robot` | Motion compiler, pose cache, perception and TonyPi control modules |
| `integrations/duck` | Account-scoped motion planning route |
| `tools` | Action import and analysis |
| `unreal` | UE 5.7 editor scripts for the earlier block-model preview |

The robot modules preserve the rehearsal implementation and its own joint conventions. They are reference components for an existing TonyPi installation; the browser exports preview data rather than issuing servo commands. See [robot setup](docs/robot.md) before adapting them to another robot.

## Development

```sh
npm test
python -m unittest discover -s robot -p "test_*.py"
```

The [demonstration](https://youtu.be/SYHgv-Zi3hE) follows a short exchange from attention to a playful response and an invitation to hug. Carrot Duck provides the companion research context; Carrot Goose focuses on physical expression and rehearsal.

## References

[Hiwonder TonyPi](https://github.com/Hiwonder/TonyPi) provides the platform code and action-file reference. [URDF Loaders](https://github.com/gkjohnson/urdf-loaders) is a useful reference for future calibrated robot models. The browser currently uses Three.js and a procedural model. Dependency attribution is in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
