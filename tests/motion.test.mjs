import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { compilePlan, makeMotion, IDLE } from "../apps/studio/sim-core.mjs";
test("amplitude and speed modify actual trajectories", () => {
  const a = makeMotion(
    "reach",
    [
      { pose: { 16: 355 }, move_s: 1 },
      { pose: IDLE, move_s: 1 },
    ],
    IDLE,
  );
  const b = compilePlan(
    { base_action: "current", amplitude: 0.7, speed: 0.5 },
    { actions: [] },
    a,
  );
  assert.equal(b.frames[0].target[16], 331);
  assert.equal(b.duration, 4);
  assert.equal(b.hardware_executed, false);
  assert.throws(
    () => makeMotion("invalid", [{ pose: { pitch: 2500 }, move_s: 1 }]),
    /1000/,
  );
});
test("bundled example has continuous frame boundaries", () => {
  const library = JSON.parse(
    readFileSync(new URL("../apps/studio/library.json", import.meta.url)),
  );
  for (const a of library.actions) {
    let prev = a.initial;
    for (const f of a.frames) {
      assert.deepEqual(f.from, prev);
      assert.ok(f.duration > 0);
      prev = f.target;
    }
  }
});

test("speed scaling preserves hold-only frames and scales their exact duration", () => {
  const original = makeMotion("hold", [
    { pose: IDLE, move_s: 0, hold_s: 1 },
    { pose: { pitch: 1510 }, move_s: 0.02, hold_s: 0 },
  ]);
  const scaled = compilePlan(
    { base_action: "current", speed: 2 },
    { actions: [] },
    original,
  );
  assert.equal(scaled.frames[0].move, 0);
  assert.equal(scaled.frames[0].duration, 0.5);
  assert.equal(scaled.frames[1].move, 0.01);
  assert.equal(scaled.duration, original.duration / 2);
});
