# Manually configuring another FBNeo game

A data-only JSON profile supplies the game-specific values; no Python or Lua editing is needed. This backend supports Fightcade FBNeo, its Lua memory/joypad APIs, and `.fs` snapshots. It assumes two players, decreasing health, positions on a shared horizontal axis, and hold-away/down-away/up-away defensive attempts. Games with different damage, blocking, state-loading, or combo semantics need a custom adapter/scorer. This is not a universal adapter for arbitrary PC games.

## Guided setup in the dashboard

Start the dashboard normally (`python -m combochan.dashboard --open`) and click **Add game** in the sidebar:

1. **Game details:** enter the display name, unique ID, exact ROM name and maximum raw health.
2. **Controls:** enter P1/P2 emulator input names. Enable the attack aliases your game uses; directions are required.
3. **Memory values:** fill in health, horizontal position and hitstun addresses for both players. Select byte/word/signed-word reads and optional mask/equality transforms. Expand optional signals for stocks, combo counters and other values.
4. **Moves:** name the sequences the search may try. Inputs must use your mapped aliases.
5. **Review:** save the game. Leave the calibration checkbox unchecked until you have tested known connected/disconnected sequences and defensive controls.

Missing or invalid values prevent advancing. Closing the wizard keeps an unfinished draft in this browser, including after a refresh. Saving adds a tab immediately and stores the profile in `artifacts/dashboard/game-profiles.json`; normal dashboard launches reload these profiles without command-line options.

Select your emulator and save-state queue in **Connect your game**, then prepare a session, connect the runner and check restoration. Use **Edit game setup** beside the selected game's emulator label to reopen the wizard. Editing any mapping clears the wizard's calibration assertion and changed profiles require preparing a new session. Existing IDs stay fixed so results remain associated with their game. Editing is unavailable while a job runs.

The wizard explains the required signals; it does not discover memory addresses or prove their meaning. See the field reference and calibration checklist below.

## Alternative: create and load a JSON profile

From the repository with Python 3.10+:

```powershell
python -m combochan.game_profile template my-game.json
# Edit my-game.json with your game's values.
python -m combochan.game_profile validate my-game.json
python -m combochan.dashboard --game-profile my-game.json --open
```

The template command refuses to overwrite an existing file. Its `null` values deliberately prevent running an unfinished profile. Validation checks structure and mapped inputs; it cannot establish that an address represents the intended game value. Repeat `--game-profile` to load multiple files with different IDs. Pass these options on every dashboard start; restart after editing a profile.

Select the new game tab, choose `fcadefbneo.exe` and a snapshot for its exact ROM, then **Prepare session** and **Launch emulator** (or load the displayed session Lua script manually). Run **Check restoration**. It requires 100 identical neutral traces. Custom games initially search damage strings; **Require a true combo** is off until you complete the calibration below.

## Values to supply

| Field | Meaning |
| --- | --- |
| `version` | Keep `1`. |
| `id` | Stable unique lowercase game/profile ID. `vampire-savior` is reserved. Use different IDs for different ROM revisions or mapping variants. |
| `title` | Name shown in the dashboard. |
| `rom` | Exact value returned by `emu.romname()` for your ROM. |
| `health_max` | Largest valid raw health value (1–65535), not the displayed percentage. |
| `inputs` | Exact names from `joypad.get()`, separately for P1 and P2. Map U/D/L/R and each attack alias you use. |
| `players` | P1 and P2 telemetry memory maps; addresses are absolute, not offsets from an implicit player base. |
| `moves` | Named frame-input sequences available for search. |
| `combo_validated` | Keep false until hitstun, scoring, and guard/jump escape checks are calibrated for this game. |

Use your emulator's memory viewer/debugger or a trusted game-specific memory map to find addresses. Observe each value during idle, movement, hits, recovery, and meter spending. A plausible value or a successful repeatability check alone does not validate its meaning. The template does not discover addresses automatically.

### Telemetry

Both players require `health`, `x`, and `stun1`. Every mapped field is an object such as:

```json
{"address": "0x123456", "type": "u16"}
```

That address is illustrative, not a real game mapping. Use a JSON decimal integer or an `0x` hexadecimal string. Supported reads are `u8` (byte), `u16` (word), and `s16` (signed word), using FBNeo's memory readers and native emulated memory layout.

`health` must decrease with damage and reach zero at KO. `x` must increase toward screen right; F/B and defensive directions are resolved from live P1/P2 positions. `stun1` must be zero outside hitstun and nonzero during hitstun. If a bit or state value encodes hitstun, transform it using an optional integer `mask`, then optional integer `equals`:

```json
{"address": "0x123458", "type": "u8", "mask": 4, "equals": 4}
```

`equals` converts the result to 1 when equal and 0 otherwise. Without it, the masked/raw value is recorded. Do not map an arbitrary animation-state ID directly as hitstun: idle IDs may also be nonzero.

Optional fields are `stun2`, `stocks`, `meter`, `recoverable`, `facing`, `y`, `state`, and `combo_hits`. Absent optional fields default to zero except `combo_hits`, which stays absent. Missing telemetry does not claim measurement: a stock cap is unavailable until P1 `stocks` is mapped. `recoverable` means a second health pool, not damage. `combo_hits`, if supplied, must count hits received and increase for every new damage event during a combo; resets/non-increments on later damage are conservatively rejected. Multi-tick damage or different counter semantics may require a custom scorer.

Generic profiles do not use a fixed floor height or Vampire Savior normal-chain ordering. Position is still used to break ties between search candidates.

### Controls and moves

U/D/L/R are required; F/B are derived and must not appear in the input map. Attack aliases are LP/MP/HP/LK/MK/HK. They are logical names: for a four-button game, map four aliases to its four physical buttons and omit the others. Each mapped input needs unique P1/P2 names. Example:

```json
"LP": {"p1": "P1 Button 1", "p2": "P2 Button 1"}
```

Use the actual strings exposed by your ROM. The runner rejects missing joypad names before connecting. It explicitly releases all boolean inputs before applying each frame's controls.

A move consists of `name` and `sequence`, for example:

```json
{"name": "Quarter-circle attack", "sequence": "D:2, D+F:2, F+LP"}
```

Commas separate steps, `+` holds buttons together, `:N` holds for N frames, and `N` alone is neutral. A release between repeated taps is explicit: `LP, N, LP`. Define 1–128 moves, each with at most 64 steps and 240 total frames. Only mapped aliases are allowed. Dashboard custom moves use the same checks.

## Calibrate before trusting results

1. Confirm the selected ROM, each input, and raw health/position values against visible gameplay. Confirm mirrored F/B after the players exchange sides.
2. Confirm `stun1`/`stun2` stay nonzero only while the defender cannot recover. Test a known connected sequence and a deliberately delayed follow-up; inspect saved traces and rejected recovery gaps. Test any mapped combo counter and stock spending too.
3. Confirm standing guard, crouching guard and jump attempts actually expose gaps in this game. These defenses do not cover every escape mechanic.
4. Once those signals and controls are calibrated, set `combo_validated` to true, validate the file, restart the dashboard, and prepare/connect a new session. Enable **Require a true combo**. Search finalists must reproduce against neutral and all three defenses, three times each.

The flag records your calibration assertion; it is not automatic proof. The scorer rejects healing, unresolved hitstun, KO/life transitions, and (when selected) recovery gaps and excess stock spending. Different game mechanics require changes to that scoring contract. A result means best found within the selected moves and search budget.

## Saved profiles and replay

Each session saves its normalized `game-profile.json` and embeds the mapping in `connect.lua`. Results also preserve the profile; bridge manifests and exports carry its SHA-256. Changing any profile setting requires preparing a new session. Replay requires both the original snapshot and the original profile hash, preventing an old route from silently using new button or memory mappings. Keep the original JSON with results you want to replay.

The original `combochan` search/probe/validate CLI remains Vampire Savior-specific. Use the dashboard entry point above for configured games. Other emulator backends can implement the protocols in `combochan/core.py` or provide a compatible batch bridge and worker adapter.
