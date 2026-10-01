import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import { segmentMotion, sliceMotion } from "../apps/studio/motion-segments.mjs";

test("removed events retain their original frame numbers across gaps", () => {
  const action = {
    name: "Events",
    initial: { pitch: 1500 },
    frames: Array.from({ length: 5 }, (_, i) => ({
      start: i, move: 1, duration: 1, target: { pitch: 1500 },
      gate: i === 2 ? "wait" : null,
      utterance: i === 4 ? "Hello" : null,
    })),
  };
  const fragment = sliceMotion(action, 1, 4);
  assert.deepEqual(fragment.provenance.removed_events.map((event) => event.frame), [3, 5]);
  assert.ok(fragment.frames.every((frame) => frame.gate === null && frame.utterance === null));
  assert.equal(action.frames[2].gate, "wait");
});
test("cuts at reversal; preserves entry, all channels and time without mutation", () => {
  const a = {
    name: "Test",
    initial: { pitch: 1500, 1: 500 },
    frames: [
      { start: 0, move: 1, duration: 1, target: { pitch: 1400, 1: 520 } },
      {
        start: 1,
        move: 1,
        duration: 1,
        target: { pitch: 1500, 1: 500 },
        gate: "cue",
      },
    ],
  };
  const before = JSON.stringify(a);
  const parts = segmentMotion(a);
  assert.equal(parts.length, 2);
  assert.equal(parts[1].fragment.initial.pitch, 1400);
  assert.equal(parts[1].fragment.frames[0].target["1"], 500);
  assert.equal(parts[1].fragment.frames[0].gate, null);
  assert.equal(parts[1].fragment.provenance.removed_events[0].gate, "cue");
  assert.equal(JSON.stringify(a), before);
  assert.throws(() => sliceMotion(a, 1, 0));
});
test("public library candidates cover each timed frame with correct source boundaries", () => {
  const library = JSON.parse(
    fs.readFileSync(new URL("../apps/studio/library.json", import.meta.url)),
  );
  for (const action of library.actions) {
    const parts = segmentMotion(action);
    assert.ok(parts.length);
    assert.ok(
      Math.abs(
        parts.reduce((sum, p) => sum + p.fragment.duration, 0) -
          action.duration,
      ) < 0.001,
    );
    for (const part of parts) {
      assert.deepEqual(
        part.fragment.initial,
        part.start ? action.frames[part.start - 1].target : action.initial,
      );
      assert.equal(part.fragment.provenance.start_frame, part.start + 1);
    }
  }
});
