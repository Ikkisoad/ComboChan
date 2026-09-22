"""Small single-scenario comparison; does not establish general model superiority."""
from pathlib import Path
import json

from .bridge import Bridge
from .search import search_combos


def main():
    root=Path(__file__).resolve().parents[1]
    bridge=Bridge(root/'artifacts/bridge',timeout=300)
    summaries=[]
    for mode in ['heuristic','random','laya']:
        print('Starting '+mode,flush=True)
        result=search_combos(bridge,budget=500,depth=4,beam=4,policy=mode,seed=0,model=root/'models/laya')
        (root/'artifacts'/f'search-{mode}-0.json').write_text(json.dumps(result,indent=2))
        summary={'policy':mode,'evaluated':result['evaluated'],'damage':result['best']['damage'] if result['best'] else 0,
                 'verified':result['best']['verified'] if result['best'] else False,
                 'label':result['best']['label'] if result['best'] else None,
                 'wall_seconds':result['wall_seconds'],'search_frames':result['search_frames'],
                 'inference_seconds':sum(c['seconds'] for c in result['model_calls'])}
        summaries.append(summary)
        (root/'artifacts/benchmark.json').write_text(json.dumps(summaries,indent=2))
        print(json.dumps(summary),flush=True)


if __name__=='__main__': main()
