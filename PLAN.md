# ComboChan — initial project plan

Status: first target selected: Vampire Savior (970519 Japan, `vsavj`) in Fightcade FBNeo v0.2.97.44-55 on Windows. Optimization preferences remain provisional.

## First target: inspected local setup

Inspected on 2026-09-22. The running emulator is `G:\Games\Fightcade\emulator\fbneo\fcadefbneo.exe`. Training overlays show health, meter, hitboxes, and combo damage. Loading active save slot 1 through the emulator menu succeeded and restored Lilith (P1) and Morrigan (P2) standing adjacent. This is a visual restoration check, not a determinism test.

The user loads the state using `+`. The emulator menu independently exposes “Load state from active slot (no 1)” with shortcut F9. The `+` binding has not been tested. The corresponding existing file is `G:\Games\Fightcade\emulator\fbneo\savestates\vsavj slot 01.fs`; preserve the original when implementing experiments.

The installed `fbneo-training-mode` scripts provide concrete integration examples:

- `fbneo-training-mode.lua` uses `emu.frameadvance`, before/after frame callbacks, `joypad.set`, and save/load callbacks.
- `games/vsav/vsav.lua` defines health, recoverable-health, meter/stocks, facing, and hitstun memory reads. Treat these addresses as candidate telemetry for this ROM until verified at runtime.
- `games/vsav/config.lua` enables health refills and instant meter refills. The game module's meter-refill function writes 99 stocks. Control refill behavior during scored trials and track resource consumption explicitly; end-of-trial meter alone would be misleading.
- The on-disk emulator configuration enables pause on focus loss and has `bDrvSaveAll 0`. Verify actual running behavior, full-state restoration semantics, and Lua-side state reset rather than assuming snapshot completeness.

Backend decision: use an in-emulator Lua adapter for frame-level execution and telemetry, with a Python process for search and Laya inference. Prototype a local file-based request/result bridge first; validate Lua file access and pause/handshake behavior before relying on it. UI input is sufficient for setup but does not establish frame-accurate execution.

The first implementation milestone is a small Lua probe and trial runner:

1. Identify the loaded ROM and available APIs; record neutral-frame telemetry without changing gameplay RAM.
2. Verify programmatic restoration of a working copy of slot 1, including reset of adapter/training-script counters. Check whether Lua callbacks coexist or require integration into the existing training script.
3. Execute a short P1 input sequence with P2 neutral, recording both health pools, stocks/meter, facing, hitstun, and frame numbers. Validate input names against the running emulator.
4. Separate damage events from healing/refills and verify combo validity with game-specific signals and an escape/guard test.
5. Repeat the same trial 100 times and compare frame traces. Only after this gate passes, add move/timing search and then Laya guidance.

Provisional first objective: maximize valid P1 combo damage from this scenario, beginning with meterless actions. This is a planning default, not a confirmed user preference. Preserve both permanent and recoverable damage metrics until the desired scoring rule is settled.

## Goal and first scope

Given a reproducible fighting-game state, search for high-performing valid combos, verify them in the game, and export their exact inputs and results. Use Laya to guide the search, with measured game outcomes as ground truth.

Start with one game/version, one attacker and defender, a fixed training-dummy configuration, and a small set of saved scenarios. Support offline training only in the initial scope. Build a command-line experiment runner before a graphical interface or support for multiple games.

Provisional objective: maximize damage subject to explicit resource limits. Keep meter use, corner carry, end position, duration, and timing tolerance as separate metrics so other objectives can be added without losing information.

Report “best found within this budget” by default. Claim optimality only for an exhaustively searched finite action space and time horizon, with complete state information and sound pruning. Such a result does not establish global optimality in the unrestricted game.

## Architecture

1. Game adapter: load/save state, step exact frames with button states, read observations, and capture replays. Expose capabilities explicitly; training resets and full snapshots are different operations.
2. State reader: extract health, resources, positions, facing, animation/action state, hitstun, hitstop, airborne status, and combo status where the backend exposes them. Mark unavailable fields as unknown. Retain the full underlying snapshot for reproducibility even when Laya receives a compact summary.
3. Action library: character-specific moves represented as frame-level press/hold/release sequences, including motion inputs, relative directions, neutral frames, simultaneous buttons, and adjustable timing. Account for input buffering and charge history through saved state or replayed prefixes.
4. Search engine: restore a node, try an action/timing variant, measure its result, and expand promising continuations. Store successful and failed attempts.
5. Laya policy: receive compact structured state plus a bounded candidate set and rank which continuations to test next. Model confidence is a heuristic until validated on this game's data.
6. Evaluator and results store: enforce resource and combo-validity constraints; record metrics, exact inputs, snapshots, and replay evidence.

Suggested initial stack: Python for orchestration and the Laya integration, JSON for scenario/action definitions, and SQLite for experiment metadata. Keep snapshots and replay files outside the database. Select the game-control backend only after testing the target platform.

## Milestones and acceptance gates

### 1. Prove control and reproducibility

Identify a supported route to snapshots, input injection, frame stepping, and state observation. An emulator or instrumented game may make these available; a native PC game's training reset may require rebuilding the scenario by replaying a setup sequence. Do not assume that a game's training save restores hidden state.

Restore one scenario and replay a known short combo 100 times. Compare per-frame observations and final results; compare canonical state hashes if available. Account for timers, random seeds, input buffers, and dummy behavior. If runs diverge, investigate or explicitly adopt repeated statistical evaluation before building deterministic search on top.

Deliverable: a documented adapter feasibility result and one reproducible combo recording. If exact control is unavailable, reassess the backend or accept a slower, less certain observation/input approach.

### 2. Establish trustworthy combo evaluation

Detect whiffs, blocks, recovery gaps, resource violations, and valid combo termination using game-specific signals. Use a dummy configured to guard or escape at its earliest legal opportunity where supported; a passive dummy and a damage counter alone are insufficient evidence.

Measure the terminal reward only after the relevant move/sequence resolves, subject to a defined timeout. Include an explicit stop action and a maximum frame horizon to handle loops and infinite combos.

Deliverable: a small suite of known valid combos and deliberately invalid sequences that the evaluator distinguishes correctly.

### 3. Build search without model guidance

Begin with bounded beam search over move macros and frame delays. Include timing variants, buffered inputs, and alternative move prefixes within the declared search space. Cache prefix snapshots when supported; otherwise reload the root and replay the prefix.

Use hard pruning only for verified invalid states or constraint violations. Beam selection is heuristic and may discard the best route. Merge states only when their future-relevant state is known equivalent; identical visible positions are insufficient.

Deliverable: rediscover a known combo within the configured action vocabulary and export a better or equal verified result when one is found. Record simulator steps, wall time, and search coverage.

### 4. Integrate Laya and measure its contribution

Pin the model/package revision and benchmark latency on the actual machine. Keep inference outside frame scheduling: pause the simulation for planning when possible and execute chosen inputs through the deterministic controller.

Use Laya's choice output to order a small candidate set. Preserve exploration of lower-ranked candidates, and avoid treating low confidence as proof of impossibility. Include compact factual move metadata when available; do not assume pretrained fighting-game expertise.

Compare identical scenarios and action spaces with random ordering, simple game heuristics, and Laya ordering. Evaluate both equal simulator-step budgets and equal wall-clock budgets, including inference overhead. Track best valid damage, time to a target score, and replay success across multiple search seeds.

Deliverable: evidence showing whether Laya helps. Keep its guidance optional if it does not yet outperform simpler methods.

### 5. Improve and package

Generate training examples from measured continuations and completed search outcomes. If warranted, fine-tune Laya to prioritize useful continuations, and calibrate on held-out scenarios. Split by starting scenario rather than adjacent frames to reduce leakage.

Add broader timing refinement, additional objectives, and a results viewer after the core loop works. For execution reliability, test timing perturbations separately from exact replay reproducibility. Expand characters and games through new adapter/action definitions.

## Reproducible outputs

Each result should include game/build and backend versions; scenario identity and snapshot hash; characters and dummy settings; objective/resource constraints; model revision; search configuration, budget, and seed; move notation; exact frame inputs; observed metrics; and independent replay verification.

Export a replayable input script and a human-readable combo summary. Video is supplementary evidence rather than the executable source of truth.

## Decisions to settle next

- Confirm P1 Lilith as the controlled character for the first scenario; validate programmatic save-state/frame-step mechanisms in the running backend.
- Primary objective and resource limits.
- Available CPU/GPU and acceptable search duration per state.
- Whether initial access includes structured game state or only the rendered screen.

## Research basis

Laya exposes typed decisions over text/JSON, including choice, ordinal score, and yes/no probabilities. Its own documentation notes zero-shot and calibration limitations and provides domain fine-tuning guidance. These support trying it as a learned search heuristic; they do not establish fighting-game capability.

- Laya source and documentation: https://github.com/NandhaKishorM/laya
- Model card: https://huggingface.co/convaiinnovations/laya

Research checked 2026-09-22. Backend-specific feasibility remains unverified until the target game is selected.
