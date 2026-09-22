"""Bounded beam search; replay prefixes from the unchanged root snapshot."""
from dataclasses import asdict
from pathlib import Path
import json
import sqlite3
import time

from .bridge import Step, Trial
from .evaluate import evaluate, repeatability
from .policy import Policy

NORMALS = [(b, (b,)) for b in ("LP","LK","MP","MK","HP","HK")]
NORMALS += [("c"+b, ("D", b)) for b in ("LP","LK","MP","MK","HP","HK")]
DELAYS = (2, 4, 6, 8, 12, 16)


def search_combos(bridge, budget=160, depth=4, beam=4, policy="heuristic", seed=0, model=None):
    if not 12 <= budget <= 10000 or not 1 <= depth <= 8 or not 1 <= beam <= 32:
        raise ValueError("Budget 12–10000, depth 1–8, beam 1–32 required")
    # A recorded reproducibility gate belongs to this scenario and current adapter.
    report_path = bridge.directory.parent / "verify.json"
    if not report_path.exists():
        raise RuntimeError("Run verify --repeats 100 before searching")
    verification = json.loads(report_path.read_text())
    import hashlib
    snapshot_hash = hashlib.sha256((bridge.directory / "root.fs").read_bytes()).hexdigest()
    if verification["manifest"]["snapshot_sha256"] != snapshot_hash:
        raise RuntimeError("Repeatability report belongs to another snapshot")
    ready = json.loads((bridge.directory / "ready.json").read_text())
    adapter_hash = hashlib.sha256(Path(ready["script"]).read_bytes()).hexdigest()
    if verification["manifest"]["adapter_sha256"] != adapter_hash:
        raise RuntimeError("Adapter changed; rerun the repeatability gate")
    if not all(g["identical"] and g["runs"] >= 100 for g in verification["repeatability"].values()):
        raise RuntimeError("100-run repeatability gate failed")
    calibration_path = bridge.directory.parent / "calibration.json"
    if not calibration_path.exists():
        raise RuntimeError("Run python -m combochan.validate before searching")
    calibration = json.loads(calibration_path.read_text())
    if (not calibration["passed"] or calibration["manifest"]["snapshot_sha256"] != snapshot_hash
            or calibration["manifest"]["adapter_sha256"] != adapter_hash):
        raise RuntimeError("Evaluator calibration is missing, stale, or failed")
    start = time.monotonic()
    ordering = Policy(policy, seed, model)
    frontier = [{"steps": (), "label": "root", "damage": 0}]
    evaluated, manifests, best = [], [], None
    db = sqlite3.connect(bridge.directory.parent / "experiments.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS trials (job TEXT, id TEXT, request TEXT, result TEXT, PRIMARY KEY(job,id))")
    try:
        for level in range(1, depth+1):
            batches = []
            for parent in frontier:
                candidates = []
                for delay in ((0,) if level == 1 else DELAYS):
                    for name, buttons in NORMALS:
                        steps = parent["steps"] + ((Step(delay),) if delay else ()) + (Step(1,buttons),)
                        candidates.append({"steps":steps,"label":parent["label"]+f" > {delay}f {name}",
                                           "parent_damage":parent["damage"]})
                batches.append(ordering.order(candidates,{"game":"Vampire Savior", "prefix":parent["label"],
                                                        "observed_damage":parent["damage"], "meter_spend_allowed":0,
                                                        "state":parent.get("decision_state", verification["initial_state"])}))
            # Round-robin parents so a fixed budget does not evaluate only one prefix.
            candidates = [b[i] for i in range(max(map(len,batches))) for b in batches if i<len(b)]
            # Reserve trials for later depths rather than exhausting the budget on pairs.
            remaining = budget-len(evaluated)
            allowance = remaining if level == depth else max(12,remaining//(depth-level+1))
            candidates = candidates[:min(remaining,allowance)]
            if not candidates: break
            trials = [Trial(f"d{level}_{i}", c["steps"]) for i,c in enumerate(candidates)]
            records, manifest = bridge.run(trials)
            manifests.append(manifest)
            survivors = []
            for c,t,r in zip(candidates,trials,records):
                score = evaluate(r)
                item = {**c, **score, "decision_state":r["trace"][sum(s.frames for s in c["steps"])]}
                evaluated.append(item)
                db.execute("INSERT INTO trials VALUES (?,?,?,?)", (manifest["job"],t.id,
                           json.dumps(asdict(t)),json.dumps(score)))
                if score["candidate_valid"] and score["damage"] > c["parent_damage"]:
                    survivors.append(item)
                    if best is None or score["damage"] > best["damage"]: best = item
            db.commit()
            print(f"Depth {level}: {len(evaluated)}/{budget} trials; best damage {best['damage'] if best else 0}", flush=True)
            survivors.sort(key=lambda c:(-c["damage"],sum(s.frames for s in c["steps"])))
            # Keep all basic starting attacks for the first expansion.
            frontier = survivors[:(12 if level==1 else beam)]
            if not frontier: break
        validation = None
        export = None
        if best:
            checks = [Trial("best_"+defense,best["steps"],repeats=3,defense=defense)
                      for defense in ("neutral","stand","crouch","jump")]
            records, manifest = bridge.run(checks)
            manifests.append(manifest)
            scores = [evaluate(r) for r in records]
            signature = best["damage_events"]
            passes = all(s["candidate_valid"] and s["damage_events"]==signature for s in scores)
            validation = {"passes":passes,"method":"guard/jump after first damage plus hitstun telemetry",
                          "repeatability":repeatability(records),"results":scores}
            export = {"snapshot_sha256":snapshot_hash, "rom":"vsavj", "steps":[asdict(s) for s in best["steps"]],
                      "label":best["label"],"damage":best["damage"],"tail":90,"defense":"neutral",
                      "verified":passes,"validation":validation,"scope":"best found; normal attacks only"}
            (bridge.directory.parent / f"best-{policy}-{seed}.json").write_text(json.dumps(export,indent=2))
        result = {"policy":policy,"seed":seed,"budget":budget,"evaluated":len(evaluated),
                  "search_frames":sum(c["frames"] for c in evaluated),"wall_seconds":time.monotonic()-start,
                  "depth":depth,"beam":beam,"model":ordering.model_info,"model_calls":ordering.calls,
                  "best":export,"manifests":manifests,"validation":validation,
                  "scope":"Bounded normal-attack vocabulary. No global optimality claim."}
        return result
    finally:
        db.close()
