# ComboChan

See the [prioritized roadmap](ROADMAP.md) for implemented search improvements and remaining emulator calibration work.

An experimental combo-search bot for **Vampire Savior Japan (`vsavj`) in Fightcade FBNeo**. A Lua runner restores a fixed save state and executes exact frame inputs; Python searches continuations and optionally uses local Laya inference to prioritize them. The emulator measures every result.

The dashboard also includes an experimental **Marvel vs. Capcom 2 (Naomi) / Flycast Dojo** adapter. It searches measured damage strings in an isolated emulator session, with SonSon launcher/aerial priorities, partner assists, hyper inputs and defensive replay checks. True-combo verification is unavailable until MVC2 hitstun is calibrated. See the [Flycast/MVC2 setup guide](docs/FLYCAST_MVC2.md).

The dashboard searches normals, motion inputs, and movement templates for P1 against P2. It uses the resources available in the save state by default, with an optional stock-spending cap. Results mean **best found in the configured search**, not globally optimal combos. Character-specific move coverage remains incomplete. Other compatible FBNeo games can use manually configured JSON profiles. The original CLI search retains its narrower meterless normal-attack scope.

The dashboard includes **Street Fighter III: 3rd Strike** for Fightcade FBNeo's Japan 990512 NO CD ROM (`sfiii3nr1`). Select its game tab and prepare a session from a `.fs` save state. Generic standing/crouching normals, motions (including two-button EX inputs), and movement templates are available; character-specific routes can use custom moves. Health, position, stocks, partial meter, and hitstun are read without gameplay-memory writes. True-combo verification remains disabled pending live calibration. Stock caps are unavailable because EX moves spend partial bars. Memory mappings are based on the installed CPS3 hitbox script and [FBNeo training mode](https://github.com/peon2/fbneo-training-mode/blob/master/games/sfiii3/sfiii3.lua).

The dashboard also supports **X-Men vs. Street Fighter**, Euro 961004 (`xmvsf`), in Fightcade FBNeo. Select its tab, prepare a `.fs` snapshot, and load the generated Lua script in your existing emulator. It reads point/anchor health, recoverable health, positions, shared meter and the engine's received-hit counter. Normals, motions, paired-button hyper inputs, jumps, dashes and super jumps are available. True-combo searches use counter continuity and defensive replays; stock caps are supported. Character-specific commands can use custom moves. Tag/active-character transitions are rejected. See the [XMVSF setup and calibration guide](docs/XMVSF.md).

**Marvel vs. Capcom: Clash of Super Heroes** is supported for the Euro 980123 FBNeo ROM (`mvsc`). The point-character adapter includes normals, motions, hypers and super jumps, with live-calibrated combo counters and defensive replays. Tags and assists are not supported. See the [MVC setup and calibration guide](docs/MVSC.md).

## Offline architecture smoke test

Run the smallest restore → execute → score slice without FBNeo or third-party dependencies:

```powershell
python -m combochan.smoke
python -m unittest discover -s tests -p test_smoke.py
```

The deterministic toy adapter produces a connected 25-damage sequence, a rejected recovery gap, and a rejected whiff. These are synthetic results, not verified game combos. After installing Laya and downloading the model as described below, run `python -m combochan.smoke --policy laya` to use real local inference to order the same trials. Scoring always uses the resulting telemetry, never model probabilities.

`combochan/core.py` defines `SaveStates`, `GameControl`, `ComboExecutor`, and `ResultScorer` protocols. `FrameExecutor` restores each repetition, executes bounded frame inputs plus a neutral tail, checks trace continuity, and releases controls even on failure. `TelemetryScorer` reuses the existing evaluator. `combochan/stub.py` implements full in-memory snapshots including held inputs and toy counters. New synchronous adapters can implement this boundary; the existing FBNeo batch bridge remains a separate backend. Real adapters must supply the evaluator's telemetry schema and validate game-specific control and combo signals before scored automation.

## Configure another game

Open the dashboard and click **Add game** in the sidebar. The five-step wizard guides you through game details, controls, memory values, move sequences, and review. It validates missing values, saves unfinished drafts in your browser, and adds the completed game immediately. Saved games reload automatically on startup; use **Edit game setup** to change their mappings later.

See the [manual game setup guide](docs/GENERIC_GAMES.md) for field meanings and calibration. The backend supports compatible two-player FBNeo games; users must supply their game's memory addresses and input names. JSON profiles and `--game-profile` remain available for advanced setup.

## Dashboard (recommended)

Double-click **Start Dashboard.cmd**, or run:

```powershell
.\.venv\Scripts\python.exe -m combochan.dashboard --open
```

Open http://127.0.0.1:8790. In the Vampire Savior tab, select your FBNeo executable and `.fs` save state, click **Prepare session**, then **Launch emulator**. For an already-open emulator, expand the connection instructions and load the generated session Lua script. Stop the old training script before changing its path, disable Auto pause, and leave the game unpaused.

Set **Emulator instances** to 1–16 before preparing to run multiple emulators. Each gets isolated session files, and search batches are shared across the connected instances without increasing the trial budget. The count is saved per game.

The dashboard copies the snapshot into an isolated session. It provides search rules, heuristic/random/Laya policies, progress, cooperative stop, history, exact-input exports, and replay. Every selected runner needs a fresh heartbeat before a job can start. Every search first checks 100 repeated neutral traces per emulator, including agreement across instances. True-combo results also receive defensive replay checks.

See [dashboard setup and game adapter guide](docs/DASHBOARD.md).

## Setup

Python 3.10+ is required. The basic runner/search has no third-party Python dependencies.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m combochan init "G:\Games\Fightcade\emulator\fbneo\savestates\vsavj slot 01.fs"
```

`init` copies the save to `artifacts/bridge/root.fs` and refuses to overwrite an existing copy. The original emulator slot is never written. ROMs, snapshots, model weights, and experiment data are excluded from Git.

For Laya:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-laya.lock.txt
.\.venv\Scripts\python.exe -m combochan.download_model
```

The downloader resolves and records a Hugging Face revision. After download, inference uses local weights with network access disabled. The tested installation runs Laya on CPU. The lock file records the actual tested Python dependencies; GPU acceleration requires a separately compatible PyTorch installation.

## Connect the emulator

1. Open `vsavj` locally in FBNeo and load your scenario.
2. Open **Game → Lua Scripting → New Lua Script Window**.
3. **Stop the existing training script before changing its path.** This FBNeo build can crash if its training script tries to save configuration after a script switch changes the working directory.
4. Set the script path to this repository's **absolute** `bridge/runner.lua` path, then click **Run**. The console should say `ComboChan ready`.
5. Turn off **Misc → Options → Auto pause** to allow background experiments, or keep FBNeo focused throughout the run. Close menus and unpause the emulator.

The runner takes control of both players while loaded. It replaces the training script; it has no health refill, meter refill, or gameplay-memory writes. It returns to the copied root state after each batch. Idle emulation continues, but every trial independently reloads the root before executing inputs. To return to manual play, stop the runner in the Lua console. Restore Auto pause to your preferred setting.

## Run experiments

```powershell
# Check neutral input and each basic attack.
.\.venv\Scripts\python.exe -m combochan probe

# Required before search: 100 identical light-punch telemetry traces.
.\.venv\Scripts\python.exe -m combochan verify --repeats 100

# Positive and negative controls for the supplied close-range scenario.
.\.venv\Scripts\python.exe -m combochan.validate

# Search without or with Laya guidance.
.\.venv\Scripts\python.exe -m combochan search --budget 500 --depth 4 --policy heuristic
.\.venv\Scripts\python.exe -m combochan search --budget 500 --depth 4 --policy laya

# Compare heuristic, random, and Laya ordering on the same scenario.
.\.venv\Scripts\python.exe -m combochan.benchmark

# Replay an exported sequence at normal speed.
.\.venv\Scripts\python.exe -m combochan replay artifacts/best-laya-0.json
```

The calibration fixture is specific to the supplied adjacent Lilith/Morrigan scenario: `MP`, four neutral frames, `HK` is the positive control; a 60-frame delay is the negative control. For a new scenario, build and validate its own positive/negative controls before searching. The adapter and snapshot hashes invalidate stale gate reports.

Search uses a bounded beam, a fixed trial budget, and delays of 2, 4, 6, 8, 12, or 16 neutral frames between one-frame attack presses. Crouching normals hold Down with the attack for that frame. Inputs are press/hold/release schedules, not wall-clock key taps. Each trial ends with 90 neutral frames. Finite tails and the limited move vocabulary intentionally bound the experiment.

Laya ranks small candidate groups, retaining exploration. It does not predict authoritative game outcomes, establish combo validity, or learn automatically from each attempt. The pretrained model has not been fine-tuned for this game. Benchmark results include its actual inference cost and must not be generalized from one scenario/seed.

## Results and validation

- `artifacts/probe.json`, `verify.json`, `calibration.json`: control and evaluator evidence.
- `artifacts/search-<policy>-<seed>.json`: search settings, model metadata, manifests, and validation.
- `artifacts/best-<policy>-<seed>.json`: exact replayable inputs, state hash, and verification status.
- `artifacts/benchmark.json`: compact policy comparison.
- `artifacts/experiments.sqlite3`: requests and evaluated outcomes.
- `artifacts/bridge/*.jsonl`: complete frame traces; corresponding manifests preserve exact requests.

Damage is the sum of measured decreases in P2's health field, with the second health pool reported separately. The evaluator rejects health increases, observed recovery gaps, unresolved final hitstun, KO/life transitions, and, in the original CLI, meter-stock spending. The dashboard applies the selected resource and combo rules. This is a conservative game-specific heuristic, not a complete engine-level proof.

Before a result is marked verified, it must reproduce the same damage-event frames against neutral, standing guard, crouching guard, and jump attempts. Defensive inputs begin immediately after the first damage event. These checks cover the first normal-attack scope; they do not exhaust every possible defensive mechanic. A damage event is not necessarily identical to the game's displayed hit counter.

100 matching traces demonstrate repeatability of the recorded telemetry for that sequence, not equivalence of every byte of hidden emulator state. The supplied snapshot contains 99 meter stocks; normal-only search restricts spending rather than rewriting that state.

## Troubleshooting

- **No ready file:** check the Lua console, selected ROM, absolute script path, and existence of `artifacts/bridge`.
- **Timeout:** focus/unpause FBNeo, close menus, and inspect its console. Requests and partial traces remain on disk for diagnosis. Do not submit another client while an old job is running.
- **Stopped/crashed script:** stop any Python client, inspect the pending request and error before restarting. The ready file alone does not prove the emulator is still running.
- **Training-script shutdown error:** stop it while its original script path is still selected, then change paths. The user's original snapshot remains available through FBNeo's normal load menu.

## Development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The Lua API behavior was checked against the [Fightcade FBNeo source](https://github.com/fightcadeorg/fightcade-fbneo/blob/master/src/burner/luaengine.cpp). Candidate memory offsets were independently read from the installed training scripts and validated against live outcomes. No third-party training script is vendored here. Laya's code/model licensing remains with its [upstream project](https://github.com/NandhaKishorM/laya).
