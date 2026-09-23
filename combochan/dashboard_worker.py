"""Dashboard jobs. The web server never performs long emulator/model work inline."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sys
import time

from .bridge import Bridge, Step, Trial
from .evaluate import repeatability
from .games import get_game
from .policy import Policy


def emit(**event):
    print(json.dumps(event), flush=True)


class Cancelled(Exception):
    pass


def timing_options(parent, rules):
    if not parent['steps']:
        return list(range(rules.get('max_start_delay',0)+1))
    explicit=rules['delays']
    if not rules.get('auto_timing',True): return list(dict.fromkeys(explicit))
    limit=rules.get('max_delay',60)
    anchors=parent.get('landing_delays',[])+parent.get('contact_delays',[])
    # Spread early experiments across timing windows before refining every frame.
    return list(dict.fromkeys([d for d in anchors+[0,1,2,4,8,12,16,24,32,48,60]+explicit+list(range(limit+1)) if d<=limit]))


def continuation_candidates(parent,actions,rules):
    actions=list(actions)
    if parent['steps']:
        previous=parent.get('last','')
        buttons=['LP','LK','MP','MK','HP','HK']
        old=previous.removeprefix('c.')
        airborne=parent.get('state',{}).get('p1',{}).get('y',40)>40
        def chain_priority(action):
            name=action.name.removeprefix('c.')
            if airborne and name in buttons:
                return (0,not action.name.startswith('c.'),buttons.index(name))
            if old in buttons and name in buttons and buttons.index(name)>buttons.index(old):
                return (0,action.name.startswith('c.')!=previous.startswith('c.'),buttons.index(name))
            return (1 if action.group=='custom' else 2,0,0)
        actions.sort(key=chain_priority)
    delays=timing_options(parent,rules)
    candidates=[]
    for round_index in range(len(delays)):
        for index,action in enumerate(actions):
            action_delays=delays
            if parent['steps'] and action.group=='custom' and rules.get('auto_timing',True):
                duration=sum(s.frames for s in action.steps)
                command_windows=[d-duration+1+shift for d in parent.get('contact_frames',[]) for shift in (0,-1,1,-2,2)]
                action_delays=list(dict.fromkeys([d for d in command_windows if 0<=d<=rules.get('max_delay',60)]+delays))
            delay=action_delays[round_index%len(action_delays)] if parent['steps'] else delays[(round_index+index)%len(delays)]
            # Consecutive presses of the same button need a release frame.
            if parent['steps'] and set(parent['steps'][-1].buttons)&set(action.steps[0].buttons)&{'LP','LK','MP','MK','HP','HK'} and delay==0:
                continue
            steps=parent['steps']+((Step(delay),) if delay else ())+action.steps
            if sum(s.frames for s in steps)>min(rules['max_frames'],1200-rules['tail']): continue
            first_input_delay=0
            for step in steps:
                if step.buttons: break
                first_input_delay+=step.frames
            if first_input_delay>rules.get('max_start_delay',0): continue
            prefix=parent['notation']+' > ' if parent['notation'] else ''
            notation=prefix+(f'[{delay}f] ' if delay else '')+action.name
            candidates.append({'steps':steps,'notation':notation,'label':f'{delay}f {action.name}',
                               'group':action.group,'last':action.name,'delay':delay,'parent_damage':parent['score']['damage'] if 'score' in parent else 0,
                               '_timing_round':round_index,'_action_order':index})
    if parent['steps'] and rules.get('auto_timing',True):
        # Spend the first windows on plausible chain continuations, before motion spam.
        old=parent.get('last','').removeprefix('c.')
        strengths=['LP','LK','MP','MK','HP','HK']
        airborne=parent.get('state',{}).get('p1',{}).get('y',40)>40
        def priority(candidate):
            name=candidate['last'].removeprefix('c.')
            chain=candidate['group']=='custom' or (name in strengths and (airborne or (old in strengths and strengths.index(name)>strengths.index(old))))
            return (candidate['_timing_round']//8,not chain,candidate['_timing_round'],candidate['_action_order'])
        candidates.sort(key=priority)
    return candidates


def select_frontier(survivors, width):
    survivors.sort(key=lambda c:(-c['score']['damage'],abs(c['state']['p2']['x']-c['state']['p1']['x'])))
    chosen=[];seen=set()
    # Reserve half the beam for action diversity; retain timing alternatives too.
    for candidate in survivors:
        if candidate['last'] not in seen:
            chosen.append(candidate);seen.add(candidate['last'])
        if len(chosen)>=max(1,width//2): break
    selected={id(c) for c in chosen}
    for candidate in survivors:
        if len(chosen)>=width: break
        if id(candidate) not in selected:chosen.append(candidate)
    return chosen


def execute(config, emit_event=emit):
    game=get_game(config['game'])
    session=Path(config['session'])
    bridge=Bridge(session/'bridge',timeout=120,rom=game.rom)
    rules=config['rules']
    snapshot_hash=hashlib.sha256((session/'bridge/root.fs').read_bytes()).hexdigest()
    started=time.monotonic()
    def check_cancel():
        if (session/'cancel.flag').exists(): raise Cancelled('Stopped after completing the active batch.')
    def run(trials, speed='turbo'):
        check_cancel()
        return bridge.run(trials,speed)
    ready=json.loads((session/'bridge/ready.json').read_text(encoding='utf-8'))
    current_script=Path(__file__).resolve().parents[1]/game.runner_path
    if ready.get('script_content') != current_script.read_bytes().decode('utf-8'):
        raise RuntimeError('The loaded Lua runner is outdated. Stop it and load the prepared session script again.')
    if config['action']=='replay':
        replay=config['replay']
        if replay['snapshot_sha256'] != snapshot_hash: raise ValueError('This result uses a different save state.')
        steps=tuple(Step(s['frames'],tuple(s['buttons'])) for s in replay['steps'])
        emit_event(stage='replaying',message='Playing the saved frame inputs at normal speed.')
        records,manifest=run([Trial('replay',steps,tail=replay['tail'])],speed='normal')
        emit_event(stage='complete',message='Replay finished.',result={'replay':True,'manifest':manifest})
        return
    emit_event(stage='checking',message='Checking that this save state replays consistently (100 runs).',completed=0)
    # A neutral trace works for arbitrary snapshots, including mid-combo or airborne states.
    # It tests restoration, not whether a canned starter can hit from this position.
    records,manifest=run([Trial('restore',(Step(1),),tail=max(30,rules.get('max_delay',60)),repeats=100)])
    checks=repeatability(records)
    if not all(g['identical'] and g['runs']==100 for g in checks.values()):
        raise RuntimeError('This snapshot did not produce 100 identical traces. Search stopped.')
    initial=records[0]['trace'][0]
    game.validate_initial(initial)
    starting_hitstun=bool(initial['p2']['stun1'] or initial['p2']['stun2'])
    gate={'manifest':manifest,'repeatability':checks,'initial_state':initial}
    (session/'verify.json').write_text(json.dumps(gate,indent=2),encoding='utf-8')
    if config['action']=='check':
        emit_event(stage='complete',message='100/100 restoration traces matched.',result={'check':True,**gate})
        return
    check_cancel()
    emit_event(stage='model',message='Loading local Laya.' if rules['policy']=='laya' else 'Preparing the search.')
    policy=Policy(rules['policy'],rules['seed'],Path(config['model']))
    actions=game.search_actions(rules)
    frontier=[{'steps':(), 'notation':'', 'score':{'damage':0},'state':initial,'landing_delays':game.landing_delays(records[0]['trace'],0,rules.get('max_delay',60))}]
    best=None
    finalists=[]
    completed=0
    simulator_frames=0
    manifests=[manifest]
    for depth in range(1,rules['depth']+1):
        check_cancel()
        pools=[]
        for parent in frontier:
            candidates=continuation_candidates(parent,actions,rules)
            if candidates:
                if rules['policy']=='laya':
                    pools.append(candidates)
                else:
                    pools.append(policy.order(candidates,{'game':game.title,'prefix':parent['notation'],
                        'state':parent['state'],'resource_rule':rules['resources']}))
        if not pools: break
        candidates=[pool[i] for i in range(max(map(len,pools))) for pool in pools if i<len(pool)]
        remaining=rules['budget']-completed
        quota=remaining if depth==rules['depth'] else max(len(actions),remaining//(rules['depth']-depth+1))
        quota=min(remaining,quota,len(candidates))
        survivors=[]
        offset=0
        while offset<quota and candidates:
            check_cancel()
            size=min(16,quota-offset)
            if rules['policy']=='laya' and offset%64==0:
                def model_progress(choices,seconds,calls):
                    emit_event(stage='model',completed=completed,budget=rules['budget'],depth=depth,
                        model_calls=calls,model_wait_seconds=round(seconds,1),
                        message=f'Laya ranking {choices} choices ({seconds:.0f}s). Emulator trials resume after this inference.',
                        elapsed=time.monotonic()-started)
                batch=policy.guided_batch(candidates,{'game':game.title,'initial_state':initial,
                    'resource_rule':rules['resources'],'true_combo':rules['true_combo'],'depth':depth},
                    size=size,progress=model_progress,check_cancel=check_cancel)
            else: batch=candidates[:size]
            chosen_ids={id(c) for c in batch}
            candidates=[c for c in candidates if id(c) not in chosen_ids]
            emit_event(stage='searching',message=f'Running {len(batch)} emulator trials.',completed=completed,
                       budget=rules['budget'],depth=depth,model_calls=len(policy.calls))
            trials=[Trial(f'd{depth}_{offset+i}',c['steps'],tail=rules['tail']) for i,c in enumerate(batch)]
            records,manifest=run(trials)
            manifests.append(manifest)
            retry_indexes=[]
            for i,(candidate,record) in enumerate(zip(batch,records)):
                candidate['tail']=rules['tail']
                preliminary=game.score(record,rules)
                if rules['tail']<min(600,1200-sum(s.frames for s in candidate['steps'])) and preliminary['damage']>0 and set(preliminary['rejection_reasons'])=={'unresolved_hitstun'}:
                    retry_indexes.append(i)
            if retry_indexes:
                emit_event(stage='searching',message=f'Allowing {len(retry_indexes)} unfinished routes up to 600 settling frames.')
                extended,manifest=run([Trial(f'settle_{depth}_{offset+i}',batch[i]['steps'],tail=min(600,1200-sum(s.frames for s in batch[i]['steps']))) for i in retry_indexes])
                manifests.append(manifest)
                for i,record in zip(retry_indexes,extended):
                    simulator_frames+=len(records[i]['trace'])-1
                    records[i]=record;batch[i]['tail']=min(600,1200-sum(s.frames for s in batch[i]['steps']))
            for candidate,record in zip(batch,records):
                score=game.score(record,rules)
                candidate['score']=score
                end_frame=sum(s.frames for s in candidate['steps'])
                candidate['state']=record['trace'][end_frame]
                candidate['landing_delays']=game.landing_delays(record['trace'],end_frame,rules.get('max_delay',60))
                # Inputs end before startup/hitstop resolves. Target the observed contact window.
                contacts=[h['frame']-end_frame for h in score['damage_events'] if h['frame']>=end_frame]
                candidate['contact_frames']=contacts[-1:]
                candidate['contact_delays']=list(dict.fromkeys(d+shift for d in contacts[-1:] for shift in (-1,0,-2,1,2,3,4,5,6,7,8) if 0<=d+shift<=rules.get('max_delay',60)))
                completed+=1
                simulator_frames+=score['frames']
                if score['candidate_valid']:
                    finalists.append(candidate)
                    finalists.sort(key=lambda c:(-c['score']['damage'],sum(s.frames for s in c['steps'])))
                    finalists=finalists[:8]
                    best=finalists[0]
                # No-hit movement/setup branches can lead to later hits. Keep a bounded sample.
                if set(score['rejection_reasons']) <= {'no_damage','unresolved_hitstun'}:
                    # Ineffective normal presses must not displace actual chain extensions.
                    if candidate['group']!='normals' or score['damage']>candidate['parent_damage'] or candidate['parent_damage']==0:
                        survivors.append(candidate)
            emit_event(stage='searching',completed=completed,budget=rules['budget'],depth=depth,
                damage=best['score']['damage'] if best else 0,notation=best['notation'] if best else '',
                message=f'Tested {completed} input sequences.',elapsed=time.monotonic()-started)
            offset+=len(batch)
        if completed>=rules['budget'] or not survivors: break
        frontier=select_frontier(survivors,rules['beam'])
    check_cancel()
    export=None
    validation_attempts=[]
    for candidate in finalists:
        emit_event(stage='validating',completed=completed,damage=candidate['score']['damage'],notation=candidate['notation'],
                   message='Checking ranked results against guard and jump escapes.')
        defenses=['neutral','stand','crouch','jump'] if rules['true_combo'] else ['neutral']
        records,manifest=run([Trial('best_'+d,candidate['steps'],tail=candidate.get('tail',rules['tail']),defense=d,repeats=3) for d in defenses])
        manifests.append(manifest)
        scores=[game.score(r,rules) for r in records]
        repeated=all(g['identical'] for g in repeatability(records).values())
        passed=repeated and all(s['candidate_valid'] and s['damage_events']==candidate['score']['damage_events'] for s in scores)
        checked={'steps':[asdict(s) for s in candidate['steps']],'tail':candidate.get('tail',rules['tail']),'damage':candidate['score']['damage'],
                'notation':candidate['notation'],'verified':bool(passed and rules['true_combo']),
                'reproduced':passed,'snapshot_sha256':snapshot_hash,'validation':scores,'starting_hitstun':starting_hitstun}
        validation_attempts.append({'notation':checked['notation'],'damage':checked['damage'],'passed':passed})
        if export is None or passed: export=checked
        if passed: break
    result={'game':game.id,'starting_hitstun':starting_hitstun,'rules':rules,'best':export,'evaluated':completed,'simulator_frames':simulator_frames,
            'wall_seconds':time.monotonic()-started,'snapshot_sha256':snapshot_hash,'session':str(session),
            'validation_attempts':validation_attempts,'model':policy.model_info,'model_calls':policy.calls,'manifests':manifests,
            'scope':'Best found within the selected input templates and budget; no global optimality claim.'}
    emit_event(stage='complete',completed=completed,damage=export['damage'] if export else 0,
               message=('Search finished.' if export['reproduced'] else 'No shortlisted route passed validation. The saved route is marked Failed validation.') if export else 'No valid damaging sequence found in this search.',result=result)


def main():
    config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:
        execute(config)
    except Cancelled as exc:
        emit(stage='cancelled',message=str(exc))
    except Exception as exc:
        emit(stage='failed',message=str(exc))
        raise SystemExit(1)


if __name__=='__main__': main()
