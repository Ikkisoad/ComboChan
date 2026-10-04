# X-Men vs. Street Fighter / Fightcade FBNeo

The built-in adapter supports the Euro 961004 ROM, **`xmvsf`**. Other regional or revision ROM IDs are deliberately rejected until tested.

## Setup

1. Open `xmvsf` locally in Fightcade FBNeo and save your scenario as a `.fs` state.
2. Select **X-Men vs. Street Fighter** in ComboChan. The default path, when present, is `G:/Games/Fightcade/emulator/fbneo/savestates/xmvsf slot 01.fs`.
3. Click **Prepare session** to copy the state into an isolated session.
4. In FBNeo, open **Game → Lua Scripting → New Lua Script Window**. Stop the training script before changing its path, then run the generated `connect.lua`. Disable Auto pause, unpause and close menus.
5. Run **Check connection**, then search. If another dashboard is busy, start the updated server with `python -m combochan.dashboard --port 8792` and open `http://127.0.0.1:8792/?game=x-men-vs-street-fighter`.

The runner controls both players and restores the copied state for each trial. It does not refill health/meter or write gameplay memory. Stop its Lua script to return to manual play.

## Inputs and scoring

The adapter supplies six standing and six crouching normals; 236, 214 and 623 motions with individual or paired punch/kick inputs; walk, jump, dash and super-jump templates. Paired motion inputs can activate hypers where appropriate. These are generic inputs, not exhaustive character move lists. Charge moves, air routes and character-specific commands can be entered as custom moves.

Damage follows the active character's health bank. Meter stocks and partial meter are shared between teammates. The engine counter counts hits dealt, so P2's received-hit counter is read from P1's object. Counter reset, health increases, unresolved counters, KO and active-character transitions reject true-combo candidates. Defensive replay checks compare damage-event frames and amounts against neutral, standing guard, crouching guard and jump attempts. Guard checks also filter search extensions. Disabling **Require a true combo** permits disconnected damage strings; tag transitions are still rejected and results are not marked verified combos.

The combo counter is a continuity signal, not an exact hitstun timer. Live testing found a counter reset directly from one hit to one hit without an intervening zero frame; the evaluator rejects this case. Counter continuity alone is insufficient: some normal timings changed damage against standing guard, which defensive replay comparison rejects.

## Memory sources

Mappings were checked against the installed FBNeo training-mode `games/xmvsf/xmvsf.lua` and `hitboxes/marvel-hitboxes.lua`. No third-party script is vendored.

| Field | P1 | P2 |
| --- | --- | --- |
| Point health / recoverable | `0xFF4211` / `0xFF421B` | `0xFF4611` / `0xFF461B` |
| Anchor health / recoverable | `0xFF4A11` / `0xFF4A1B` | `0xFF4E11` / `0xFF4E1B` |
| Active character (0 point, 1 anchor) | `0xFF4220` | `0xFF4620` |
| Shared stocks / partial meter | `0xFF4214` / `0xFF4212` | `0xFF4614` / `0xFF4612` |
| On-screen x / y | `0xFF400C` / `0xFF4010` | `0xFF440C` / `0xFF4410` |
| Received-hit counter | `0xFF4510` | `0xFF4110` |

Health and counters are bytes; positions are signed words; partial meter is an unsigned word. Health ranges from 0 to 144. Position tracks the on-screen object, independently of the selected health bank. Searches can start with either slot active, but reject any slot change during a trial to avoid attributing a switch between health pools to damage.

## Live calibration

On October 4, 2026, the Euro ROM was tested in the user's running Fightcade FBNeo with Rogue/Sabretooth against Ryu/Ken:

- 100 neutral restoration traces were identical.
- Each basic normal input worked; neutral and out-of-range LP produced no damage. Approaching for 40 frames then HP produced 15 damage.
- `F:40, LP, N:2, MP, N:2, HP` produced 17 damage at frames 44 and 63. All four defense settings reproduced the exact events three times each. The input template contains three attacks; only two hits connected.
- With 16-frame waits, the counter restarted at frame 64 without a zero frame. With 60-frame waits, recovery gaps and counter resets were detected. Guard and jump attempts escaped these follow-ups.
- A tag input changed the active-character selector and was rejected by the adapter. A 236PP hyper spent one stock; its short tail remained unresolved, so the evaluator required more settling time.

Losslessly delta-encoded live traces are saved in `tests/fixtures/xmvsf_calibration.json`. Regression tests reconstruct their original hashes and cover positive/negative controls, defensive comparison, tag rejection, meter caps, setup isolation and ROM identity. The fixture contains telemetry and inputs, not a ROM or save state. This calibration covers the measured normal chains; it does not establish exhaustive support for every character, aerial route, defensive mechanic or tag combo.
