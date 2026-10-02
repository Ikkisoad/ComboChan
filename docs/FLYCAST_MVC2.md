# Marvel vs. Capcom 2 on Flycast Dojo

The built-in **Marvel vs. Capcom 2** dashboard tab supports the **Naomi `mvsc2.zip`** game in Flycast Dojo 6.32 or later. Dreamcast images and modified ROMs are not supported by this memory map.

This is an experimental **damage-string search**, not a true-combo verifier. The runner measures health, positions, active character slots and meter stocks. Finalists are replayed three times each against neutral, standing guard, crouching guard and jump attempts, activated after the first observed damage. All damage events must match. Passing results say **Escape checks passed**; older neutral-only results say **Damage only · gaps possible**. Hitstun remains uncalibrated, so **Require a true combo** is disabled and results never receive the **Verified combo** label. These defensive probes cannot prove continuous hitstun, especially for snapshots taken mid-combo. Restoration checks establish repeatability of recorded telemetry, not full hidden-state equivalence.

## Connect

1. In your normal Flycast installation, save an active match with both point characters on screen. Use a `.state` file, such as `data/mvsc2.state`. Position the characters for the starter you want to explore.
2. Open ComboChan and select **Marvel vs. Capcom 2**. Select `flycast.exe` and the save-state file. The selected installation must contain your `ROMs/mvsc2.zip` and `data/naomi.zip`.
3. Click **Prepare session**, then **Launch emulator**. ComboChan copies the emulator, required libraries, configuration, BIOS, EEPROM/NVRAM and save state into the session directory. The ROM is read from your installation. The original emulator configuration and save slots are not changed.
4. Keep the isolated Flycast window running with menus closed. It loads the copied snapshot automatically. Check restoration or start a small search; every search requires 100 matching neutral traces first.
5. Close the isolated Flycast window when finished. Your original emulator session remains available for manual play.

The backend connects through the isolated process rather than attaching to an already-running Flycast process. Each queued state is copied into that process's private slot 9 before its trials. The source snapshots are never overwritten. Replays require the original snapshot and adapter-profile hashes.

## Inputs and scoring

Use **LP, HP, LK, HK**, **A1, A2** for the two selected partners, directional inputs **U/D/L/R**, and relative **F/B**. A one-frame press is the default; `F:40, LP` walks forward for 40 frames and presses light punch. Explicit `N` frames release held buttons. MP/MK are rejected because MVC2 has four attack buttons and two dedicated assist buttons. A1/A2 are Naomi buttons 3/6 (Flycast C/Z input bits 1/256); the selected assist type belongs to the saved match.

The **Partner assists** category calls either reserve character with A1 or A2. The **Hyper combos** category includes `236PP` (LP+HP), `214PP` (LP+HP) and `236KK` (LK+HK). For SonSon these correspond to Tenchi Tsuukan, En'ou, and POW. They depend on the meter available in the save state and the game accepting the motion. Team hyper combinations, delayed hyper swaps, snapbacks and tags are outside this scoring scope because they can change the point character. The motion category contains single-button specials.

Open **Buttons search can use** in Search rules to exclude any attack or assist button. Unchecking A1 and A2 removes both partner calls and any custom sequence that presses either button; normal attacks and hypers remain available. Save settings to keep the selection for the next search.

When the snapshot identifies SonSon as P1, the heuristic explores `df.HP` and `c.HK` starters, then jump cancels and aerial `LP, LK, LP, LK, HP, HK` inputs. Repeated light inputs represent her medium air normals. Measured contact frames and relative airborne positions guide timing; an unfinished air route retains a beam slot even when a hyper deals more immediate damage. The shared search divides its remaining budget across remaining depths and reserves a continuation trial for the strongest measured starter as a finisher after a developing route. This also applies to Vampire Savior searches. The reservation tests an input, not whether it connects: guard and jump checks still reject dropped damage strings. These are search priorities, not guaranteed or optimal routes.

Scoring counts decreases in the current P2 point character's health. It allows a P1 reserve character to appear during an assist while requiring the original point character and team slot to remain the same. It rejects observed healing, tags, opponent assists, KOs, round transitions, invalid health, and damage still occurring in the last ten frames. Multi-hit extensions receive an additional standing-guard probe during search; changed damage events reject that branch before it can crowd the beam. Finalists still require all four defensive conditions. The sequence budget excludes restoration and validation replays, whose traces and manifests are retained. A quiet tail is not proof that hitstun ended. A meter cap counts observed decreases in whole stocks. Team combos and recoverable-life scoring remain outside the supported scope.

Trials run at normal speed even when the common search protocol requests turbo. Manifests record both requested and actual speed. Large searches can take several minutes; begin with a small budget and useful starting positions. Neutral controls alone cannot guarantee that a CPU opponent is inactive: use a two-player scenario suitable for deterministic practice.

## Implementation and diagnostics

`combochan/flycast.py` supplies the game adapter, isolated runtime preparation, and damage-only scorer. `bridge/flycast_runner.lua` uses VBlank callbacks for inputs and samples, and the overlay callback for restoring save states on the UI thread. It never writes gameplay memory or refills resources.

Session `bridge/heartbeat.json` reports the runner phase, trial and repetition. `error.json` records a stopped runner; request/result files and manifests preserve evidence. A heartbeat only indicates liveness. If a batch stops advancing, close the isolated emulator, prepare a fresh session, and inspect the error before retrying. Do not overwrite pending requests to force a new job.

The Naomi mapping starts at player base `0x0C2D7088`, with opposing-player stride `0x5A4` and team-slot stride `0xB48`: active flag `+0`, character ID `+1`, X/Y float coordinates `+0x34/+0x38`, facing `+0x110`, health `+0x420`. Team stocks are at `0x0C2F8392/3`; the activity byte at `0x0C2F836C` reads 1 for the point character alone and 2 while one P1 assist is on screen in the tested Naomi state. These offsets and meanings are specific to the supported build and must be recalibrated for other revisions.

References used to inspect the interfaces and candidate mappings:

- [Flycast Dojo Lua implementation](https://github.com/blueminder/flycast-dojo/blob/master/core/lua/lua.cpp)
- [Flycast Dojo save-state implementation](https://github.com/blueminder/flycast-dojo/blob/master/core/nullDC.cpp)
- [Naomi input mapping](https://github.com/blueminder/flycast-dojo/blob/master/core/hw/maple/maple_jvs.cpp)
- [Capcom MVC2 battle commands](https://game.capcom.com/manual/MVCFC/pt-br/switch/page/7/1)
- [SonSon move guide](https://gamefaqs.gamespot.com/arcade/562932-marvel-vs-capcom-2/faqs/21587)
- [MVC2 Naomi candidate health and meter addresses](https://github.com/Smoker1/RetroArch-174-and-above-Cheats/blob/master/Reicast-NAOMI/Marvel%20vs.%20Capcom%202.cht)

The installed Dojo MVC2 training script uses Dreamcast addresses and is not loaded by this backend. No third-party Lua implementation is copied into the runner.
