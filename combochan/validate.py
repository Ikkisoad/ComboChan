"""Live positive/negative controls for the current close-range root state."""
from pathlib import Path
import json

from .bridge import Bridge, Step, Trial
from .evaluate import evaluate, repeatability


def main():
    root=Path(__file__).resolve().parents[1]
    bridge=Bridge(root/'artifacts/bridge')
    chain=(Step(1,('MP',)),Step(4),Step(1,('HK',)))
    gap=(Step(1,('MP',)),Step(60),Step(1,('HK',)))
    trials=[Trial('neutral',(Step(30),)),Trial('whiff',(Step(60,('L',)),Step(1,('LP',))))]
    trials += [Trial(name+'_'+defense,steps,repeats=2,defense=defense)
               for name,steps in [('chain',chain),('gap',gap)]
               for defense in ['neutral','stand','crouch','jump']]
    records,manifest=bridge.run(trials)
    scores=[evaluate(r) for r in records]
    lookup={s['id']:s for s in scores}
    checks={
        'neutral_no_damage':lookup['neutral']['damage']==0,
        'whiff_no_damage':lookup['whiff']['damage']==0,
        'chain_connected':all(lookup['chain_'+d]['candidate_valid'] for d in ['neutral','stand','crouch','jump']),
        'chain_survives_defense':len({lookup['chain_'+d]['damage'] for d in ['neutral','stand','crouch','jump']})==1,
        'gap_detected':not lookup['gap_neutral']['candidate_valid'] and bool(lookup['gap_neutral']['gaps']),
        'defense_changes_gap':any(lookup['gap_'+d]['damage']<lookup['gap_neutral']['damage'] for d in ['stand','crouch','jump']),
        'identical_repeats':all(v['identical'] for v in repeatability(records).values()),
    }
    report={'passed':all(checks.values()),'checks':checks,'results':scores,'manifest':manifest}
    (root/'artifacts/calibration.json').write_text(json.dumps(report,indent=2))
    print(json.dumps({'passed':report['passed'],'checks':checks,'results':[(s['id'],s['damage'],s['gaps']) for s in scores]},indent=2))
    if not report['passed']: raise SystemExit(1)


if __name__=='__main__': main()
