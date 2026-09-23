# Dashboard

Run `Start Dashboard.cmd` or `python -m combochan.dashboard --open` from an installed checkout. The server binds only to localhost, uses no CDN, and requires no frontend build. Keep its terminal open; Ctrl+C stops the server. A second server can use `--port 8791`.

## Workflow

1. Select Vampire Savior, Fightcade `fcadefbneo.exe`, and a `vsavj` `.fs` snapshot.
2. Prepare a session. This copies the snapshot; the original remains untouched.
3. Launch a separate emulator, or use the displayed session script in an existing Lua window. Stop the training script before changing paths. Disable Auto pause and unpause.
4. Run the connection check or start a search. The runner controls both players and reloads the copied snapshot for every trial.
5. Review verified routes, replay against the same snapshot, or export their exact frame inputs. Stop waits for the active batch to finish.

Default resources come from the snapshot. There is no refill or meter rewrite. Optional stock caps constrain measured spending. Snapshot settings do not define the whole search: input groups, timing, depth, beam width, trial budget, and frame horizon still bound exploration. Laya is optional and requires the model-download setup in the README; heuristic search works without it.

Current motion templates include 236, 214 and 623 with individual or paired buttons. Movement includes walk, jump and dash. This does not exhaust character-specific specials, charge moves, air routes, defensive mechanics, or all possible sequences. KO/life transitions remain conservatively rejected. Disabling the true-combo rule permits damage strings but does not mark them verified combos. No result claims global optimality.

## Files and troubleshooting

Profiles live in `artifacts/dashboard/config.json`, independent sessions under `sessions/`, and results under `runs/`. Earlier CLI results are also listed. Replay requires the original snapshot hash. A ready file alone is insufficient: connection status requires a fresh heartbeat. On timeout, inspect the Lua console and unpause the emulator. Prepare a fresh session if a request was abandoned; do not run two clients against one session.

FBNeo has a quoted command-line parsing issue. The launcher first tries a Windows short path and otherwise writes a tiny `combochan-*` bootstrap in the system temporary folder. That file contains only the session script path. If the temporary path also contains spaces, load the displayed script manually. Temporary bootstraps can be deleted after closing the emulator.

Native Browse uses Python tkinter; paste full paths if tkinter is unavailable. The server never closes an existing user emulator. Stop a running job before closing the dashboard.

## Adding another game

`combochan/games.py` is the registry. Each adapter supplies a stable id, title/badge, ROM identifier, emulator metadata, state extensions, runner path, public input groups, launch arguments, action templates, initial telemetry validation, and scoring. Register its instance in `GAMES`; the frontend creates its tab and persists a separate profile automatically.

The current worker and file bridge share the existing frame-step and two-player telemetry protocol. A new emulator needs a compatible bridge or a corresponding worker/backend extension, not just a new title. Implement the game's memory offsets, snapshot loading, health/resource semantics and defensive validation in its runner/scorer. Validate against known positive/negative controls and live deterministic replays before claiming support. The current native file picker and setup copy are FBNeo-oriented and should be generalized with the next backend.

## Validation

`python -m unittest discover -s tests -v` covers rules, snapshot isolation, heartbeat status, request protection, cancellation and the worker pipeline with a test bridge. `tools/test_dashboard_ui.cjs` uses Playwright against a running server to test desktop/mobile controls and real session preparation; install Playwright or set `PLAYWRIGHT_MODULE` to its module path. The browser test prepares a new session from configured paths and should run while no job is active. Unit tests do not substitute for live validation of new move templates.

## Move configuration and timing

Expand **Configure available moves** to disable individual built-in templates or add named custom sequences. **Add Lilith demon** inserts `LP, N, LP, F, LK, HP`; adjust holds/releases to match the move. This is an input template, not a guarantee that the move activates in every state. Commas separate steps, `+` holds buttons together, `:frames` sets duration, and `N` releases all buttons. Example: `D:2, D+F:2, F+HP`. Custom moves can be used with every built-in group turned off. Their checkbox controls whether they are searched. Save settings persists the library with the game profile.

Automatic timing defaults to a 60-frame maximum wait, applies between actions, and prioritizes windows around an observed return to the floor (the vsavj adapter's y=40). Remaining windows are spread across the move library and refined frame by frame as the budget permits. Prefixes keep timing alternatives in the beam. This allows aerial hits followed by delayed ground inputs; it does not guarantee finding every air-to-ground combo. Disable automatic timing to restrict experiments to the explicit delays. Results show chosen waits as `[34f]` and exports retain exact input durations.

## First-input budget and existing combos

**Latest first input after loading** defaults to 0: the bot supplies its first input before advancing the first emulated frame. Set 5 to explore 0–5 neutral frames before that input. This limit is independent of inter-move timing and also counts leading neutral steps inside custom moves. Existing profiles inherit 0 until explicitly changed.

If P2 is already in hitstun at frame zero, true-combo validation treats that as an existing combo: a recovery gap before the first additional damage invalidates the route. Guard/jump validation starts immediately in that case. Results count added damage after the snapshot, not historical damage. Turning off Require a true combo still permits disconnected strings. Reload the Lua session script after updating to enable immediate defensive validation.

## Engine combo-counter validation

The vsavj runner records the received-hit counter at player base + 0x144 (P2: 0xFF8944), separately named `combo_hits`. Live replay of the 55-damage wake-up route showed values 1 → 2 at frame 15, then 2 → 1 at the new hit at frame 96. The previous nonzero-stun test missed this direct reset. Counter continuity now rejects that route during search. A counter clearing after the final hit is normal; a reset followed by more damage is not a true combo. Equal/non-advancing counts on new damage are conservatively rejected, so unusual multi-tick damage mechanics may need further adapter-specific handling.

The compact captured negative control is `tests/fixtures/vsav_wakeup_counter.json`; its uninterrupted suffix also checks accepted progression. Existing exported traces remain unchanged. A result with failed defensive/repeatability checks is displayed as **Failed validation**, not Candidate. The worker checks up to eight ranked finalists, stopping at the first passing route. Counter checks supplement defensive replays; they do not replace them. Reload the session Lua script after updating the runner.

## Laya scheduling

Dashboard Laya searches make one inference over at most 12 choices from a 64-candidate window, then immediately execute a batch of up to 16 trials. Three further baseline batches run before the next inference (or the next search depth). Model-selected choices share the batch with baseline exploration. Unselected candidates remain available. This bounds model work between emulator batches, instead of ranking every branch before testing anything. The dashboard reports elapsed inference time every two seconds. Stop is checked before and after an inference; a running model call must return before cancellation finishes. CPU inference can still take noticeable time. Existing running workers keep their old scheduling until the next run.

## Normal-chain exploration

Continuation timing now prioritizes observed hit-contact frames as well as landing. Grounded normal prefixes prioritize stronger normals, while airborne prefixes can restart with grounded lights after landing. These are ordering hints, not hard cancel-legality rules. Holding Down across different crouching attacks is allowed; only repeated attack buttons require release. Ineffective normal extensions no longer crowd damaging extensions out of the beam. The optional Lilith demon template must be enabled to search that command.

`python -m tools.tune_lilith_route` is a bounded diagnostic for the supplied Lilith route, using a copied prepared snapshot in an isolated emulator that closes afterward. It tries 1–3 frame holds and 0–60 frame gaps, preserves up to four hit-timing variants per stage, and saves evidence under `artifacts/route-tests`. The initial jHP may already be contained in the snapshot, so a no-damage first step is allowed in this diagnostic. It does not claim to enumerate all timing combinations.

Contact timing prioritizes the frames immediately before contact for normal buffers. Custom commands also get windows timed so their final input can arrive near contact. Promising routes rejected only for unresolved hitstun receive one longer settling replay (up to 600 frames, within the total 1,200-frame protocol limit). That settling duration is saved and reused for defensive validation/replay; input-horizon limits stay separate.

The supplied Lilith route was experimentally validated on its prepared snapshot: HP 1f, neutral 7f, D+LK 1f, neutral 2f, D+MK 1f, neutral 13f, D+HP 1f, neutral 10f, then LP / neutral / LP / F / LK / HP for one frame each. The snapshot already includes the aerial hit. This continuation adds 53 damage, spends one stock, and reproduced against all four defense settings three times. This is evidence from a user-specified route timing sweep, not a claim that unrestricted search is exhaustive. The result is saved in dashboard history with exact inputs and validation evidence.

## Saved results and favorites

Use **Favorite** on a result to keep it in the **Favorites** tab under Saved results. Favorites persist across restarts and retain replay/export. **Clear results** clears non-favorites from the selected game's list and preserves favorites and other games. **Undo clear** restores the last cleared group during the current page session. Clearing updates `artifacts/dashboard/result-library.json`; exported results and raw experiment evidence remain on disk, so clearing the list does not reclaim disk space.
