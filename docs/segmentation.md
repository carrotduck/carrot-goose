# Reviewing motion fragments

Open **Analyze motion library** in the right panel, then **Analyze all motions**. Analysis runs locally in the browser over the loaded library. The hosted library currently contains 137 sequences; the public repository bundles the authored examples.

The deterministic pass proposes frame boundaries at direction changes, pauses of at least 0.25 seconds, near-return of a joint to its source initial value, event cues, and a 30-frame length limit. Changes within 3 raw units are treated as small for segmentation. These defaults are editing heuristics, not calibrated physical limits. Boundaries are shared across the channels so coordinated motion remains together. It does not infer intent or deduplicate equivalent gestures.

Select a candidate and edit the one-based start/end frame numbers. **Preview fragment** plays just that range. **Confirm and save** stores the reviewed fragment in this browser and adds it to the motion library. **Export saved fragments** downloads a JSON collection. Download the export for a durable copy; browser storage may be cleared.

Each fragment preserves source name/reference, source frame range, source start time, entry/exit poses and active channels. All channel values are retained, including leg values that the current model does not animate. Original gates and speech cues are listed in provenance and removed from preview playback. The original motion remains unchanged.

Analysis of the 137-sequence development library produced 2,688 candidates with no timing-total discrepancies or rejected sequences. This checks structural preservation, not semantic quality or physical execution. Fragment names and cut points still require review. The language planner does not yet automatically retrieve or compose this reviewed collection.

The public tests check reversal boundaries, entry poses, channel retention, event handling and source immutability. Physical transition validation remains a separate step.
