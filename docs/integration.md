# Conversation and motion

The planner accepts a request and the current sequence at `POST /api/chat/:userId/simulation/plan`. It returns a validated motion with per-frame targets, timing and the observed value ranges. The workbench can play and edit that result.

The hosted adapter verifies the account session, limits request frequency and deduplicates request IDs. `createSimulationRouter({generate, library})` accepts an injected model function, so another host can supply its own provider and authentication middleware. The local server supplies a loopback-only session for development.

Plans use `simulation_only` and `hardware_executed: false`. Export schemas retain their original version identifiers for compatibility. The public product name is Carrot Goose.

The hosted workbench is at `https://carrotgoose.online/`. Use the sign-in dialog with an existing Carrot Duck recovery key to establish a session on this domain.

For another deployment, serve `apps/studio` and the planner behind the same origin, replace the account adapter in `editor.js`, and configure HTTPS and account sessions. Existing Carrot Duck login storage belongs to that origin and does not transfer to a new domain. Keep provider credentials on the server.

The ordinary Duck conversation page and the motion prompt are separate entry points. The simulator sends only its current request and motion context to the planner.
