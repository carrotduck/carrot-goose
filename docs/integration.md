# Conversation and motion

The planner accepts a request and the current sequence at `POST /api/chat/:userId/simulation/plan`. It returns a validated motion with per-frame targets, timing and the observed value ranges. The workbench can play and edit that result.

The hosted adapter verifies the account session, limits request frequency and deduplicates request IDs. `createSimulationRouter({generate, library})` accepts an injected model function, so another host can supply its own provider and authentication middleware. The local server supplies a loopback-only session for development.

Plans use `simulation_only` and `hardware_executed: false`. Export schemas retain their original version identifiers for compatibility. The public product name is Carrot Goose.

The hosted workbench is at `https://carrotgoose.online/`. Use the sign-in dialog with an existing Carrot Duck recovery key to establish a session on this domain.

For another deployment, serve `apps/studio` and the planner behind the same origin, replace the account adapter in `editor.js`, and configure HTTPS and account sessions. Existing Carrot Duck login storage belongs to that origin and does not transfer to a new domain. Keep provider credentials on the server.

The ordinary Duck conversation page and the motion prompt are separate entry points. The simulator sends only its current request and motion context to the planner.

## Context supplied to the model

The hosted planner reuses Carrot Duck's model service. Each request includes the current sequence's starting pose, frame targets and timing. The system prompt supplies supported joint IDs, neutral values, display directions and available motion names. The selected interface language controls the language of the generated name and explanation.

The shoulder pitch channels are 8 and 16, the lateral arm channels are 7 and 15, and the elbow channels are 6 and 14 in the browser model. The frame plan is validated before it becomes an editable sequence. The planner does not receive the companion's full conversation history or memory through this endpoint.

A release check using the real model service generated a right-shoulder lift from 275 to 355 and returned to 275. This verified the simulation route and output mapping; it was not a hardware run.
