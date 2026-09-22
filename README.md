# ComboChan

An experimental combo-search bot for **Vampire Savior Japan (`vsavj`) in Fightcade FBNeo**. A Lua runner restores a fixed save state and executes exact frame inputs; Python searches continuations and optionally uses local Laya inference to prioritize them. The emulator measures every result.

This first version searches standing/crouching normal attacks for P1 against P2. Results mean **best found in the configured search**, not globally optimal combos. Specials, air routes, meter-spending routes, and other games are not yet implemented.

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

Damage is the sum of measured decreases in P2's health field, with the second health pool reported separately. The evaluator rejects health increases, observed recovery gaps, unresolved final hitstun, KO/life transitions, and meter-stock spending. This is a conservative game-specific heuristic, not a complete engine-level proof.

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
