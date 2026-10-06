# Marvel vs. Capcom / Fightcade FBNeo

Select **Marvel vs. Capcom** for the Euro 980123 ROM (`mvsc`). Prepare a `.fs` snapshot with the point characters active. The adapter provides six standing/crouching normals, 236/214/623 motions, paired punch/kick hypers, movement and super jumps. Mixed punch/kick inputs are rejected because tags and assists are not calibrated. Team/anchor scenarios are outside the supported scope.

Health, positions, stocks, character identity and received-hit counters are read without gameplay-memory writes. Sources are the installed training-mode `games/mvc/mvc.lua` and `hitboxes/marvel-hitboxes.lua`.

| Signal | P1 | P2 | Type |
| --- | --- | --- | --- |
| Point health | `0xFF3271` | `0xFF3671` | byte, 0–144 |
| Stocks | `0xFF3274` | `0xFF3674` | byte |
| X / Y | `0xFF300C` / `0xFF3010` | `0xFF340C` / `0xFF3410` | signed word |
| Character ID | `0xFF3052` | `0xFF3452` | word |
| Received-hit counter | `0xFF3520` | `0xFF3120` | byte |

The counter is a continuity signal, not a hitstun timer. Identity and object-slot changes are conservatively rejected, but this is not a calibrated tag adapter. Partial meter and recoverable health are not mapped; zero defaults for those fields do not claim measurement.

## Live calibration, October 6, 2026

Captured Venom/Morrigan versus Spider-Man/Captain America from the user's running emulator into `artifacts/mvsc-calibration/root.fs`. Original emulator save slots were preserved.

- Five emulators produced 500 identical neutral restoration traces, 100 each.
- `F:55, LP, N:8, D+MK` dealt 16 damage at frames 60, 73 and 84. All four defense modes reproduced identical events three times each.
- `F:60, LP, N:60, MK` had a recovery gap; standing guard, crouching guard and jump escaped the follow-up.
- `F:60, LP, N:8, HK` reset the counter without a zero frame and was rejected. Defensive replays escaped the follow-up.
- A 236PP hyper spent one stock. A 300-frame tail allowed it to settle.
- Some connected-looking routes vary by one damage point under standing guard. The exact-event validator intentionally rejects these; hit timing alone does not override failed damage comparison.

Losslessly compressed telemetry in `tests/fixtures/mvsc_calibration.json` covers these controls. Tests reconstruct and verify the original trace hashes. No ROM or save-state data is included in the fixture. This calibration covers the measured Venom scenario, not every character, team mechanic or defensive option.

The initial search uses five isolated sessions, 1,000 candidates, six actions, beam width 16, a 300-frame tail, save-state resources and true-combo scoring. Custom approach and calibrated-chain inputs help explore the captured spacing. Search results mean best found within that budget; finalists still need exact defensive replay verification.
