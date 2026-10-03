# Research references for embodied performance

CARROT GOOSE explores how a physical gesture accompanies a conversational reply. The supporting workbench makes motion sequences editable, so that the preparation and timing of a gesture can be examined. These references inform the design questions; the [research framing](research-framing.md) describes the proposed comparison.

## A response extends beyond speech

**Zeng et al., [LPM 1.0: Video-based Character Performance Model](https://arxiv.org/abs/2604.07823v2) (2026, v2).** LPM treats conversational performance as sustained audiovisual behaviour, including listening as well as speaking. For Goose, this suggests examining the lead-in to a gesture and what happens between spoken turns, rather than assessing an isolated pose.

This is a conceptual transfer from generated video to physical interaction. Goose uses robot motion sequences and a browser authoring tool; LPM is not its motion generator. One question is whether changing the onset of the same gesture changes how responsive it feels to the preceding dialogue.

## Separate emotional interpretation from movement

**Smith and Carette, [Design Foundations for Emotional Game Characters](https://doi.org/10.7557/23.6175).** Their architecture separates appraisal and emotion state from the selection of visible behaviour. That distinction is useful when designing a physical response: interpreting a conversational cue does not, by itself, specify an appropriate gesture.

Goose connects companion cues to local motion execution. Its workbench supports authoring the movement, while the [performance score](performance.md) describes its place in the exchange. The paper provides an architectural reference, not evidence that any particular gesture communicates the intended emotion.

## Adapting to a person's preferences

**Maroto-Gómez et al., [An adaptive decision-making system supported on user preference predictions for human–robot interactive communication](https://doi.org/10.1007/s11257-022-09321-2) (2023).** The study concerns learning users' activity preferences to select robot activities. It offers a direction for future work: could prior acceptance or refusal inform the choice to offer a gesture later?

The published system's preference-ranking method is not implemented here. Learning what a user prefers also differs from claiming that the robot grows its own preferences or personality.

## Personality belongs to the companion layer

**Lo, Huang and Lo, [LLM-based robot personality simulation and cognitive system](https://doi.org/10.1038/s41598-025-01528-8) (2025)** is related work on robot personality representation and evaluation. Its personality framework is not the basis of Goose's servo controller, nor does it validate Duck's keyword mapping.

Personality configuration and interaction continuity are discussed in [Carrot Duck's research references](https://github.com/carrotduck/carrot-duck/blob/main/docs/RESEARCH_REFERENCES.md). Goose adds the question of how a reply is physically expressed. Whether that expression contributes to perceived personal recognition remains a question for participant evaluation.
