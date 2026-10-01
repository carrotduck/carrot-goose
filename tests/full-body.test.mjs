import { test } from "node:test";
import assert from "node:assert/strict";
import { IDLE, makeMotion, compilePlan } from "../apps/studio/sim-core.mjs";
test("lower-body targets survive planning, scaling and imported optional channels", () => {
  const initial = { ...IDLE, 17: 510, 18: 490 };
  const a = makeMotion(
    "Knee bend",
    [
      { pose: { 3: 403, 11: 596 }, move_s: 1 },
      { pose: initial, move_s: 1 },
    ],
    initial,
  );
  const b = compilePlan(
    { base_action: "current", amplitude: 0.5, speed: 0.5 },
    { actions: [] },
    a,
  );
  assert.equal(b.frames[0].target["3"], 353);
  assert.equal(b.frames[0].target["11"], 646);
  assert.equal(b.frames[1].target["3"], 303);
  assert.equal(b.frames[1].target["17"], 510);
  assert.equal(b.duration, 4);
});
