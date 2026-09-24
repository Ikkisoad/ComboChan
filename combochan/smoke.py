"""Offline vertical slice; optionally rank toy trials with the real local Laya."""
import argparse
import json
from pathlib import Path

from .bridge import Step, Trial
from .core import ComboExecutor, FrameExecutor, ResultScorer, TelemetryScorer
from .policy import Policy
from .stub import StubAdapter


def run_smoke(policy=None) -> dict:
    game = StubAdapter()
    snapshot = game.save_state()
    executor: ComboExecutor = FrameExecutor(game)
    scorer: ResultScorer = TelemetryScorer()
    candidates = [
        {"label": "connected", "trial": Trial("connected", (Step(1, ("MP",)), Step(4), Step(1, ("HK",))))},
        {"label": "gap", "trial": Trial("gap", (Step(1, ("MP",)), Step(20), Step(1, ("HK",))))},
        {"label": "whiff", "trial": Trial("whiff", (Step(1),))},
    ]
    policy = policy if policy is not None else Policy("heuristic")
    ordered = policy.order(candidates, json.dumps({
        "backend": "toy_stub", "observation": game.observe(),
        "rules": "MP deals 10, HK deals 15; hitstun lasts 12 frames. Rank connected meterless damage."
    }))
    results = [scorer.score(executor.execute(snapshot, item["trial"])[0]) for item in ordered]
    valid = [result for result in results if result["candidate_valid"]]
    best = max(valid, key=lambda result: result["damage"], default=None)
    return {"backend": "toy_stub", "real_game_verified": False,
            "policy": policy.mode, "best": best, "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=("heuristic", "laya"), default="heuristic")
    parser.add_argument("--model", type=Path, default=Path(__file__).resolve().parents[1] / "models/laya")
    args = parser.parse_args()
    print(json.dumps(run_smoke(Policy(args.policy, model=args.model)), indent=2))


if __name__ == "__main__":
    main()
