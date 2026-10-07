# ComboChan roadmap

Features are implemented and checked one at a time in this priority order.
Existing saved settings and replay evidence must remain compatible.

1. **Available special moves** — Implemented. Make the move library easy to find,
   accept commands such as SonSon's `41236K`, and save selected moves alongside
   starters. Enabled specials must be eligible for extensions as well as openings.
2. **Longer routes** — Implemented (64 actions). Increase the eight-action ceiling and clarify that
   one custom sequence or simultaneous button chord is one action. Keep finite
   trial/frame limits; a bounded search cannot prove an infinite.
3. **Explore extensions before discarding prefixes** — Implemented. Retain promising
   lower-damage branches and diverse openings instead of filling the beam with
   immediate high-damage attacks. Keep measured damage as the final result score.
4. **Branch from intermediate save states** — Implemented for FBNeo batches;
   Flycast support pending live validation. Reuse a tested prefix when
   exploring extensions, with full trace provenance and root-state replay for
   final verification. Use capability checks and a root-replay fallback for
   adapters without validated checkpoint support.
5. **Learn timing before broad delay sweeps** — Initial implementation complete;
   exact startup/recovery mapping pending calibrated telemetry. Spend a bounded part of
   the trial budget measuring enabled moves and prioritize observed contact,
   hitstun/link windows and cancel opportunities. Distinguish measured contact
   latency from true startup/recovery; unavailable signals must stay unknown.
6. **Close emulators** — Implemented. Add a dashboard action to close the emulator
   processes launched by this dashboard, with predictable active-job handling.
7. **MVC2 tags** — Implemented, experimental pending live calibration. Add optional tag actions and account for point-character
   changes when evaluating routes. Explain the adapter's button aliases and retain
   the current limitation that MVC2 hitstun/true-combo verification is uncalibrated.

Validation: targeted unit/regression checks per feature, dashboard UI checks where
available, then the full offline suite. Emulator-specific changes require live
calibration before claims of verified in-game behavior. Straightforward changes
can use lighter models; bridge/scoring changes need careful review.

## Implementation notes

- Special entry expands `41236K` into each available kick strength (`41236LK`
  and `41236HK` for MVC2). Both library selection and starters persist together.
- Maximum actions accepts 1–64. The default remains 5; input horizon and trial
  budget still bound long routes. A custom multi-button string is one action.
- Half the generic beam can retain distinct openings with observed continuation
  room. MVC2 also retains its launcher/airborne setup branches.
- FBNeo checkpoints are bounded to 32 per batch, scoped to one root snapshot,
  and removed after the batch. Full input schedules and traces remain in results.
  Normal-speed replay and defensive/final validation always start from the root.
- Timing warm-up spends at most 10% of the search budget, capped at 32 probes.
  Observations are exported as `timing_observations`. Contact latency is measured
  in the current scenario, not asserted to be intrinsic startup. Combo counters
  are not treated as hitstun duration. Missing recovery/frame advantage stays
  null; learned windows prioritize trials without excluding other timings.
- Close emulators requests graceful shutdown of processes launched by the current
  dashboard for the selected game, including older prepared sessions. Active jobs
  must finish or stop after their batch. Failed close requests remain retryable.
- MVC2 Tags is off by default. `Tag 1` uses `LP+LK`; `Tag 2` uses `HP+HK`
  (the second attack pair referred to as `MP+MK` on some layouts). Enabled tags
  permit P1 swaps within the original team roster; P2 swaps, KOs and invalid
  telemetry are still rejected. After a swap, root-character timing observations
  and SonSon-specific priorities no longer guide that branch.
- Remaining calibration work: Flycast checkpoint callback timing, reliable P1
  actionable/recovery signals, MVC2 hitstun, context-specific timing after tags,
  and live comparison against full-root replays. Offline fixtures are not live
  game calibration evidence.

## Validation (2026-10-07)

- 166 offline tests passed, including the optional Lua checkpoint/point-tracking
  tests with `COMBOCHAN_TEST_LUA51` set to a local Lua 5.1 library.
- `tools/test_dashboard_roadmap.cjs` passed against an isolated temporary server:
  special moves/starters, 64-action settings, optional tag defaults and persistence,
  timing controls, close requests using a fake owned process, busy-state controls,
  and mobile layout. It also runs the starter browser regression.
- No live emulator was closed during testing. Live tag behavior and the remaining
  calibration items above are not certified by these synthetic tests.

## Validation (2026-10-07)

- 166 offline tests passed, including the optional Lua checkpoint/point-tracking
  tests with `COMBOCHAN_TEST_LUA51` set to a local Lua 5.1 library.
- `tools/test_dashboard_roadmap.cjs` passed against an isolated temporary server:
  special moves/starters, 64-action settings, optional tag defaults and persistence,
  timing controls, close requests using a fake owned process, busy-state controls,
  and mobile layout. It also runs the starter browser regression.
- No live emulator was closed during testing. Live tag behavior and the remaining
  calibration items above are not certified by these synthetic tests.
