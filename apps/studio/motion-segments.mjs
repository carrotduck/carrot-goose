// Deterministic frame segmentation. Semantic labels are confirmed by the author.
export function sliceMotion(action, start, end, name = "Motion fragment") {
  if (
    !Number.isInteger(start) ||
    !Number.isInteger(end) ||
    start < 0 ||
    end < start ||
    end >= action.frames.length
  )
    throw Error("Invalid frame range");
  const initial = {
      ...(start ? action.frames[start - 1].target : action.initial),
    },
    frames = [];
  let time = 0,
    previous = initial;
  for (const original of action.frames.slice(start, end + 1)) {
    if (
      !Number.isFinite(original.duration) ||
      original.duration < 0 ||
      !Number.isFinite(original.move) ||
      original.move < 0 ||
      original.move > original.duration
    )
      throw Error("Invalid frame timing");
    const target = { ...previous, ...original.target };
    if (Object.values(target).some((v) => !Number.isFinite(v)))
      throw Error("Invalid joint value");
    frames.push({
      ...structuredClone(original),
      from: { ...previous },
      target,
      start: time,
      gate: null,
      utterance: null,
    });
    time += original.duration;
    previous = target;
  }
  if (time <= 0) throw Error("Fragment has no playback duration");
  const keys = [
    ...new Set([
      ...Object.keys(initial),
      ...frames.flatMap((f) => Object.keys(f.target)),
    ]),
  ];
  const channels = keys.filter((k) =>
    frames.some((f) => f.target[k] !== initial[k]),
  );
  return {
    name,
    initial,
    frames,
    duration: time,
    source: "reviewed_fragment",
    mode: "simulation_only",
    hardware_executed: false,
    provenance: {
      source_name: action.name,
      source_reference: action.source || null,
      start_frame: start + 1,
      end_frame: end + 1,
      start_time: action.frames[start].start,
      channels,
      entry_pose: initial,
      exit_pose: previous,
      removed_events: action.frames
        .slice(start, end + 1)
        .map((f, i) => ({
          frame: start + i + 1,
          gate: f.gate,
          utterance: f.utterance,
        }))
        .filter((event) => event.gate || event.utterance),
    },
  };
}
export function segmentMotion(
  action,
  { pause = 0.25, threshold = 3, maxFrames = 30 } = {},
) {
  if (!action?.frames?.length) throw Error("No frames");
  const result = [];
  let start = 0,
    previous = { ...action.initial },
    lastDelta = {};
  const flush = (end, reason) => {
    if (end < start) return;
    try {
      const fragment = sliceMotion(
        action,
        start,
        end,
        action.name + " · " + (result.length + 1),
      );
      result.push({ start, end, reason, fragment });
    } catch (e) {
      if (e.message !== "Fragment has no playback duration") throw e;
    }
    start = end + 1;
  };
  action.frames.forEach((f, i) => {
    const target = { ...previous, ...f.target };
    const delta = Object.fromEntries(
      Object.keys(target).map((k) => [
        k,
        target[k] - (previous[k] ?? target[k]),
      ]),
    );
    const reversal = Object.keys(delta).some(
      (k) =>
        Math.abs(delta[k]) > threshold &&
        Math.abs(lastDelta[k] || 0) > threshold &&
        delta[k] * lastDelta[k] < 0,
    );
    if (i > start && (reversal || f.gate || f.utterance))
      flush(i - 1, reversal ? "Direction change" : "Event boundary");
    const moving = Object.values(delta).some((v) => Math.abs(v) > threshold);
    const returned = Object.keys(delta).some(
      (k) =>
        Math.abs(target[k] - (action.initial[k] ?? target[k])) <= threshold &&
        Math.abs(previous[k] - (action.initial[k] ?? previous[k])) > threshold,
    );
    if (
      f.duration - f.move >= pause ||
      !moving ||
      returned ||
      i - start + 1 >= maxFrames
    )
      flush(
        i,
        !moving
          ? "Hold"
          : returned
            ? "Return"
            : f.duration - f.move >= pause
              ? "Pause"
              : "Length limit",
      );
    lastDelta = delta;
    previous = target;
  });
  flush(action.frames.length - 1, "End");
  return result;
}
