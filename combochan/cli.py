from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import sys

from .bridge import Bridge, Step, Trial
from .evaluate import evaluate, repeatability

ROOT = Path(__file__).resolve().parents[1]


def save_report(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(json.dumps(data, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description="ComboChan Vampire Savior experiment runner")
    parser.add_argument("--bridge", type=Path, default=ROOT / "artifacts/bridge")
    parser.add_argument("--timeout", type=float, default=180)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="Copy an existing save-state into the project")
    init.add_argument("snapshot", type=Path)
    probe = sub.add_parser("probe", help="Verify a neutral run and each basic attack")
    probe.add_argument("--repeats", type=int, default=2)
    repro = sub.add_parser("verify", help="Repeat a short sequence and compare full telemetry")
    repro.add_argument("--repeats", type=int, default=100)
    replay = sub.add_parser("replay", help="Replay an exported result from its starting state")
    replay.add_argument("file", type=Path)
    replay.add_argument("--repeats", type=int, default=1)
    replay.add_argument("--speed", choices=["normal", "turbo"], default="normal")
    search = sub.add_parser("search", help="Bounded search over standing/crouching normals")
    search.add_argument("--budget", type=int, default=160)
    search.add_argument("--depth", type=int, default=4)
    search.add_argument("--beam", type=int, default=4)
    search.add_argument("--policy", choices=["heuristic", "random", "laya"], default="heuristic")
    search.add_argument("--seed", type=int, default=0)
    search.add_argument("--model", type=Path, default=ROOT / "models/laya")
    args = parser.parse_args()
    args.bridge.mkdir(parents=True, exist_ok=True)
    if args.command == "init":
        destination = args.bridge / "root.fs"
        if destination.exists():
            raise FileExistsError("root.fs already exists; use a separate --bridge directory for another scenario")
        shutil.copy2(args.snapshot, destination)
        print(destination)
        return
    bridge = Bridge(args.bridge, args.timeout)
    if args.command == "search":
        from .search import search_combos
        result = search_combos(bridge, budget=args.budget, depth=args.depth,
                               beam=args.beam, policy=args.policy, seed=args.seed, model=args.model)
        save_report(ROOT / "artifacts" / f"search-{args.policy}-{args.seed}.json", result)
        return
    speed = "turbo"
    if args.command == "probe":
        trials = [Trial("neutral", (Step(30),), repeats=args.repeats)]
        trials += [Trial(button, (Step(1, (button,)),), repeats=args.repeats)
                   for button in ("LP", "MP", "HP", "LK", "MK", "HK")]
    elif args.command == "verify":
        trials = [Trial("LP", (Step(1, ("LP",)),), repeats=args.repeats)]
    else:
        data = json.loads(args.file.read_text())
        import hashlib
        if data["snapshot_sha256"] != hashlib.sha256((args.bridge / "root.fs").read_bytes()).hexdigest():
            raise ValueError("Replay snapshot does not match current root.fs")
        trials = [Trial("replay", tuple(Step(s["frames"], tuple(s["buttons"])) for s in data["steps"]),
                        repeats=args.repeats, tail=data.get("tail", 90), defense=data.get("defense", "neutral"))]
        speed = args.speed
    records, manifest = bridge.run(trials, speed=speed)
    report = {"manifest": manifest, "repeatability": repeatability(records),
              "results": [evaluate(r) for r in records if r["repetition"] == 1],
              "initial_state": records[0]["trace"][0]}
    save_report(ROOT / "artifacts" / f"{args.command}.json", report)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"ComboChan: {exc}", file=sys.stderr)
        raise SystemExit(1)
