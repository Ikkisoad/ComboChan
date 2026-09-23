"""Conservative telemetry evaluation; no global optimality claims."""
import hashlib
import json


def trace_digest(trace: list[dict]) -> str:
    return hashlib.sha256(json.dumps(trace, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def evaluate(record: dict, max_stocks: int | None = 0, require_combo: bool = True) -> dict:
    trace = record["trace"]
    if len(trace) < 2 or [r["frame"] for r in trace] != list(range(len(trace))):
        raise ValueError("Missing or noncontiguous trace")
    hits, gaps, healing, spent = [], [], 0, 0
    starting_hitstun = bool(trace[0]['p2']['stun1'] or trace[0]['p2']['stun2'])
    recovered_since_hit = False
    for previous, row in zip(trace, trace[1:]):
        p, q = previous["p2"], row["p2"]
        delta = p["health"] - q["health"]
        healing += max(0, -delta)
        spent += max(0, previous["p1"]["stocks"] - row["p1"]["stocks"])
        if delta > 0:
            if (hits or starting_hitstun) and recovered_since_hit:
                gaps.append(row["frame"])
            hits.append({"frame": row["frame"], "damage": delta})
            recovered_since_hit = False
        elif (hits or starting_hitstun) and not (q["stun1"] or q["stun2"]):
            recovered_since_hit = True
    # A wake-up hit can reset the counter directly from 2 to 1, without an idle frame.
    counter_available=all(type(row['p2'].get('combo_hits')) is int for row in trace)
    counter_breaks=[]
    if counter_available:
        last_count=trace[0]['p2']['combo_hits'] if starting_hitstun else 0
        active=starting_hitstun
        reset=False
        for previous,row in zip(trace,trace[1:]):
            count=row['p2']['combo_hits']
            if active and count<previous['p2']['combo_hits']: reset=True
            damage=previous['p2']['health']-row['p2']['health']
            if damage>0:
                if count<=0 or (active and (reset or count<=last_count)):
                    counter_breaks.append(row['frame'])
                active=True;last_count=count;reset=False
    final = trace[-1]
    settled = not any(r["p2"]["stun1"] or r["p2"]["stun2"] for r in trace[-10:])
    damage = sum(h["damage"] for h in hits)
    reasons = []
    if not hits: reasons.append("no_damage")
    if healing: reasons.append("health_increased")
    if gaps and require_combo: reasons.append("recovery_gap")
    if counter_breaks and require_combo: reasons.append("combo_counter_break")
    if not settled: reasons.append("unresolved_hitstun")
    if max_stocks is not None and spent > max_stocks: reasons.append("meter_spent")
    if final["p2"]["health"] <= 0: reasons.append("ko_or_life_transition")
    return {"id": record["id"], "damage": damage, "health_loss": trace[0]["p2"]["health"]-final["p2"]["health"],
            "recoverable_pool_loss": trace[0]["p2"]["recoverable"]-final["p2"]["recoverable"],
            "combo_counter_available":counter_available,"combo_counter_breaks":counter_breaks,
            "starting_hitstun": starting_hitstun, "damage_events": hits, "hit_count": len(hits), "gaps": gaps,
            "healing": healing, "stocks_spent": spent, "settled": settled,
            "candidate_valid": not reasons, "rejection_reasons": reasons,
            "defense": record["defense"], "trace_sha256": trace_digest(trace),
            "validation": "engine_counter_and_telemetry" if counter_available else "telemetry_only", "frames": len(trace)-1}


def repeatability(records: list[dict]) -> dict:
    groups = {}
    for record in records:
        groups.setdefault(record["id"], []).append(trace_digest(record["trace"]))
    return {name: {"runs": len(hashes), "unique_traces": len(set(hashes)),
                   "identical": len(set(hashes)) == 1} for name, hashes in groups.items()}
