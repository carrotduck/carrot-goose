# Motion planning integration

The workbench sends the motion request and current sequence to `POST /api/workbench/plan`. It returns validated frame targets, timing and value ranges. A successful result opens and plays in the 3D editor.

This endpoint is independent of Carrot Duck accounts. It accepts same-origin workbench requests without a login or recovery key. Provider credentials stay on the server. The adapter limits requests per client, concurrent model calls and total daily requests. The shared allowance is 100 requests per server day and resets on process restart; it is an operational limit rather than a billing guarantee.

The hosted workbench is at https://carrotgoose.online/. Local installations use `server.mjs` and the model settings in `.env.example`. Editing and playback also work without a model provider.

`createWorkbenchRouter` uses the same motion compiler as the account-scoped integration. Existing Carrot Duck conversation routes retain their session checks. The planning endpoint returns frame data for preview in the editor.

For another deployment, serve the editor and endpoint from the same origin, configure the permitted origin list and HTTPS, and keep model credentials on the server.
