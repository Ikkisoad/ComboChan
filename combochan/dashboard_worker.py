"""Dashboard jobs. The web server never performs long emulator/model work inline."""
from dataclasses import asdict
from pathlib import Path
import hashlib
import json
import sys
import time

from .bridge import Bridge, BridgePool, Step, Trial
from .evaluate import repeatability
from .games import get_game
from .moves import parse_starter
from .policy import Policy
from .timing import observe, preferred_delays, stun_end


def emit(**event):
    print(json.dumps(event), flush=True)


class Cancelled(Exception):
    pass


def depth_quota(remaining, depths_left, available):
    """Reserve trials for continuations even when the move library is large."""
    return min(available, remaining, max(1, (remaining+depths_left-1)//depths_left))


def escape_mismatch(reference, defended):
    return not defended['candidate_valid'] or defended['damage_events'] != reference['damage_events']


def timing_options(parent, rules):
    if not parent['steps']:
        return list(range(rules.get('max_start_delay',0)+1))
    explicit=rules['delays']
    if not rules.get('auto_timing',True): return list(dict.fromkeys(explicit))
    limit=rules.get('max_delay',60)
    anchors=parent.get('landing_delays',[])+parent.get('contact_delays',[])
    # Spread early experiments across timing windows before refining every frame.
    return list(dict.fromkeys([d for d in anchors+[0,1,2,4,8,12,16,24,32,48,60]+explicit+list(range(limit+1)) if d<=limit]))


def continuation_candidates(parent,actions,rules,vsav_ordering=True):
    actions=list(actions)
    starters=rules.get('starters') or ([rules['starter']] if rules.get('starter') else [])
    sequences=rules.get('_starter_sequences')
    if sequences is None: sequences=[parse_starter(starter,actions) for starter in starters]
    names=parent.get('action_names',[])
    if sequences and not any(names[:len(sequence)]==sequence for sequence in sequences):
        next_names={sequence[len(names)] for sequence in sequences if sequence[:len(names)]==names and len(sequence)>len(names)}
        actions=[action for action in actions if action.name in next_names]
    if parent['steps'] and vsav_ordering:
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
            if parent['steps'] and not parent.get('tag_transition') and rules.get('auto_timing',True) and rules.get('_timing_observations'):
                learned=preferred_delays(parent,action,rules['_timing_observations'].get(action.name),rules.get('max_delay',60))
                action_delays=list(dict.fromkeys(learned+action_delays))
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
                               'action_names':parent.get('action_names',[])+[action.name],
                               'checkpoint_steps':len(parent['steps']),
                               '_timing_round':round_index,'_action_order':index})
    if parent['steps'] and vsav_ordering and rules.get('auto_timing',True):
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
    survivors=sorted(survivors,key=lambda c:(-c['score']['damage'],abs(c['state']['p2']['x']-c['state']['p1']['x'])))
    chosen=[];seen=set()
    # Reserve exploration slots for routes that still have room to continue.
    # These signals guide experiments; final ranking remains measured damage.
    promising=sorted((c for c in survivors if c.get('extension_window',0)>0),key=lambda c:(
        -c.get('extension_window',0),-c['score'].get('hit_count',0),
        abs(c['state']['p2']['x']-c['state']['p1']['x']),-c['score']['damage']))
    openings=set()
    for candidate in promising:
        opening=tuple(candidate.get('action_names',[candidate['last']])[:1])
        if opening in openings: continue
        chosen.append(candidate);openings.add(opening);seen.add(candidate['last'])
        if len(chosen)>=max(1,width//2): break
    # Reserve half the beam for action diversity; retain timing alternatives too.
    for candidate in survivors:
        if len(chosen)>=max(1,width//2): break
        if candidate['last'] not in seen:
            chosen.append(candidate);seen.add(candidate['last'])
    selected={id(c) for c in chosen}
    for candidate in survivors:
        if len(chosen)>=width: break
        if id(candidate) not in selected:chosen.append(candidate)
    return chosen


def extension_window(trace, end_frame, score):
    """Remaining stun/continuity signal, never a claim about P1 recovery."""
    if not score.get('damage_events'): return 0
    contact=score['damage_events'][-1]['frame']
    # Null hitstun (MVC2) provides no usable window.
    rows=trace[contact:]
    if not rows or any(row['p2'].get('stun1') is None for row in rows): return 0
    recovery=next((row['frame'] for row in rows if not (row['p2'].get('stun1') or row['p2'].get('stun2'))),None)
    return max(0,(recovery if recovery is not None else trace[-1]['frame'])-max(contact,end_frame))


def reserve_finisher_trial(candidates, pools, frontier, finishers, quota):
    """Try a strong starter again after a developing prefix within each depth budget."""
    if quota < 2 or not finishers:
        return candidates
    parents=sorted(range(len(frontier)),key=lambda i:(
        -frontier[i]['score']['damage'],-len(frontier[i].get('action_names',[]))))
    for i in parents:
        parent=frontier[i]
        names=parent.get('action_names',[])
        if not names or parent['score']['damage']<=0 or any(name in finishers for name in names):
            continue
        finisher=next((c for c in pools[i] if c['last'] in finishers),None)
        if finisher is not None:
            candidates.remove(finisher)
            candidates.insert(1,finisher)
            break
    return candidates


def execute(config, emit_event=emit):
    if 'game_profile' in config:
        from .game_profile import ConfiguredGame
        game=ConfiguredGame(config['game_profile'])
        if game.id!=config['game']: raise ValueError('Game profile ID mismatch.')
    else:
        game=get_game(config['game'])
    session=Path(config['session'])
    sessions=[Path(path) for path in config.get('sessions',[str(session)])]
    if config['action']=='replay': sessions=[session]
    snapshot_file=config.get('snapshot_file','root'+game.state_extensions[0])
    bridges=[Bridge(path/'bridge',timeout=getattr(game,'bridge_timeout',120),rom=game.rom,snapshot=snapshot_file) for path in sessions]
    bridge=BridgePool(bridges) if len(bridges)>1 else bridges[0]
    rules=config['rules']
    if hasattr(game,'validate_rules'): game.validate_rules(rules)
    snapshot_hash=hashlib.sha256((session/'bridge'/snapshot_file).read_bytes()).hexdigest()
    started=time.monotonic()
    def check_cancel():
        if (session/'cancel.flag').exists(): raise Cancelled('Stopped after completing the active batch.')
    def run(trials, speed='turbo'):
        check_cancel()
        return bridge.run(trials,speed)
    current_script=Path(__file__).resolve().parents[1]/game.runner_path
    profile_hash=getattr(game,'profile_sha256',None)
    for path in sessions:
        ready=json.loads((path/'bridge/ready.json').read_text(encoding='utf-8'))
        if ready.get('script_content') != current_script.read_bytes().decode('utf-8'):
            raise RuntimeError('The loaded Lua runner is outdated. Stop it and load the prepared session script again.')
        if profile_hash and ready.get('profile_sha256')!=profile_hash:
            raise RuntimeError('The loaded game profile changed. Prepare and connect a new session.')
        if hashlib.sha256((path/'bridge'/snapshot_file).read_bytes()).hexdigest()!=snapshot_hash:
            raise RuntimeError('Emulator instances have different save states. Prepare a new session.')
    if config['action']=='replay':
        replay=config['replay']
        if replay.get('profile_sha256')!=profile_hash and not (hasattr(game,'replay_compatible') and game.replay_compatible(replay)):
            raise ValueError('Replay requires the original game profile.')
        if replay['snapshot_sha256'] != snapshot_hash: raise ValueError('This result uses a different save state.')
        steps=tuple(Step(s['frames'],tuple(s['buttons'])) for s in replay['steps'])
        emit_event(stage='replaying',message='Playing the saved frame inputs at normal speed.')
        records,manifest=run([Trial('replay',steps,tail=replay['tail'])],speed='normal')
        emit_event(stage='complete',message='Replay finished.',result={'replay':True,'manifest':manifest})
        return
    emit_event(stage='checking',message=f'Checking that this save state replays consistently (100 runs per emulator, {len(bridges)} instance(s)).',completed=0)
    # A neutral trace works for arbitrary snapshots, including mid-combo or airborne states.
    # It tests restoration, not whether a canned starter can hit from this position.
    restoration=[Trial('restore',(Step(1),),tail=max(30,rules.get('max_delay',60)),repeats=100)]
    check_cancel()
    records,manifest=bridge.run_all(restoration) if len(bridges)>1 else run(restoration)
    checks=repeatability(records)
    if not all(g['identical'] and g['runs']==100*len(bridges) for g in checks.values()):
        raise RuntimeError('This snapshot did not produce 100 identical traces per emulator, matching across all instances. Search stopped.')
    initial=records[0]['trace'][0]
    game.validate_initial(initial)
    stun=(initial['p2']['stun1'],initial['p2']['stun2'])
    starting_hitstun=None if all(value is None for value in stun) else bool(any(stun))
    gate={'manifest':manifest,'repeatability':checks,'initial_state':initial}
    (session/(snapshot_file+'.verify.json' if snapshot_file!='root.fs' else 'verify.json')).write_text(json.dumps(gate,indent=2),encoding='utf-8')
    if config['action']=='check':
        emit_event(stage='complete',message=f'{100*len(bridges)}/{100*len(bridges)} restoration traces matched across {len(bridges)} emulator(s).',result={'check':True,**gate})
        return
    check_cancel()
    emit_event(stage='model',message='Loading local Laya.' if rules['policy']=='laya' else 'Preparing the search.')
    policy=Policy(rules['policy'],rules['seed'],Path(config['model']))
    actions=game.search_actions(rules)
    starters=rules.get('starters') or ([rules['starter']] if rules.get('starter') else [])
    sequences=[parse_starter(starter,actions) for starter in starters]
    search_rules={**rules,'_starter_sequences':sequences}
    frontier=[{'steps':(), 'notation':'', 'score':{'damage':0},'state':initial,'landing_delays':game.landing_delays(records[0]['trace'],0,rules.get('max_delay',60))}]
    best=None
    finishers=set()
    finalists=[]
    completed=0
    simulator_frames=0
    manifests=[manifest]
    timing_observations={}
    if rules.get('learn_timing',True) and rules.get('auto_timing',True) and rules['depth']>1:
        # Bounded warm-up, counted in the same budget as search trials. Single
        # move contact latency is local to this state, not universal startup.
        preferred={name for sequence in sequences for name in sequence}
        probe_actions=sorted(actions,key=lambda a:(a.name not in preferred,a.group=='movement'))
        probe_actions=[a for a in probe_actions if sum(s.frames for s in a.steps)<=min(rules['max_frames'],1200-rules['tail'])]
        probe_actions=probe_actions[:min(32,max(1,rules['budget']//10))]
        for start in range(0,len(probe_actions),16):
            group=probe_actions[start:start+16]
            emit_event(stage='searching',message='Measuring move contact and available hitstun signals before exploring delays.',completed=completed,budget=rules['budget'])
            trials=[]
            for i,action in enumerate(group):
                candidate={'steps':action.steps,'action_names':[action.name]}
                tail=game.trial_tail(candidate,rules) if hasattr(game,'trial_tail') else rules['tail']
                trials.append(Trial(f'timing_{start+i}',action.steps,tail=min(tail,1200-sum(s.frames for s in action.steps))))
            observations,manifest=run(trials)
            manifests.append(manifest)
            for action,record in zip(group,observations):
                score=game.score(record,rules)
                if set(score['rejection_reasons'])<={'no_damage','unresolved_hitstun','unresolved_damage'}:
                    timing_observations[action.name]=observe(action,record['trace'],score)
                completed+=1;simulator_frames+=score['frames']
        search_rules['_timing_observations']=timing_observations
    for depth in range(1,rules['depth']+1):
        check_cancel()
        pools=[]
        pool_parents=[]
        for parent in frontier:
            candidates=continuation_candidates(parent,actions,search_rules,getattr(game,"vsav_ordering",True))
            if hasattr(game,'order_continuations'):
                candidates=game.order_continuations(candidates,parent,rules)
            if candidates:
                pool_parents.append(parent)
                if rules['policy']=='laya':
                    pools.append(candidates)
                else:
                    pools.append(policy.order(candidates,{'game':game.title,'prefix':parent['notation'],
                        'state':parent['state'],'resource_rule':rules['resources']}))
        if not pools: break
        candidates=[pool[i] for i in range(max(map(len,pools))) for pool in pools if i<len(pool)]
        remaining=rules['budget']-completed
        quota=depth_quota(remaining,rules['depth']-depth+1,len(candidates))
        if rules['policy']=='heuristic':
            candidates=reserve_finisher_trial(candidates,pools,pool_parents,finishers,quota)
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
            for candidate in batch:
                candidate['tail']=(game.trial_tail(candidate,rules) if hasattr(game,'trial_tail') else rules['tail'])
            trials=[Trial(f'd{depth}_{offset+i}',c['steps'],tail=c['tail'],
                          checkpoint_steps=c['checkpoint_steps'] if rules.get('checkpoints',True) else 0) for i,c in enumerate(batch)]
            records,manifest=run(trials)
            manifests.append(manifest)
            retry_indexes=[]
            for i,(candidate,record) in enumerate(zip(batch,records)):
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
            escaped=set()
            if getattr(game,'escape_checks',False):
                # Disconnected damage strings otherwise crowd both the beam and
                # the shortlist before the more thorough final replay checks.
                references=[game.score(record,rules) for record in records]
                indexes=[i for i,s in enumerate(references)
                         if s['candidate_valid'] and s['hit_count']>1
                         and s['damage']>batch[i]['parent_damage']]
                if indexes:
                    emit_event(stage='searching',message=f'Checking {len(indexes)} extensions against standing guard.',depth=depth,completed=completed)
                    defended,manifest=run([Trial(f'escape_{depth}_{offset+i}',batch[i]['steps'],tail=batch[i]['tail'],defense='stand') for i in indexes])
                    manifests.append(manifest)
                    for i,record in zip(indexes,defended):
                        score=game.score(record,rules)
                        simulator_frames+=score['frames']
                        if escape_mismatch(references[i],score): escaped.add(i)
            for i,(candidate,record) in enumerate(zip(batch,records)):
                score=game.score(record,rules)
                if i in escaped:
                    score['candidate_valid']=False
                    score['rejection_reasons'].append('guard_escape')
                candidate['score']=score
                end_frame=sum(s.frames for s in candidate['steps'])
                candidate['state']=record['trace'][end_frame]
                candidate['extension_window']=extension_window(record['trace'],end_frame,score)
                candidate['stun_ends_at']=stun_end(record['trace'],score)
                if hasattr(game,'annotate_candidate'):
                    game.annotate_candidate(candidate,record['trace'],end_frame,rules)
                candidate['landing_delays']=game.landing_delays(record['trace'],end_frame,rules.get('max_delay',60))
                # Inputs end before startup/hitstop resolves. Target the observed contact window.
                contacts=[h['frame']-end_frame for h in score['damage_events'] if h['frame']>=end_frame]
                candidate['contact_frames']=contacts[-1:]
                candidate['contact_delays']=list(dict.fromkeys(d+shift for d in contacts[-1:] for shift in (-1,0,-2,1,2,3,4,5,6,7,8) if 0<=d+shift<=rules.get('max_delay',60)))
                completed+=1
                simulator_frames+=score['frames']
                prefix_complete=not sequences or any(candidate['action_names'][:len(sequence)]==sequence for sequence in sequences)
                if score['candidate_valid'] and prefix_complete:
                    if depth==1 and score['damage']>0 and (not finishers or score['damage']>=best['score']['damage']):
                        finishers={candidate['last']}
                    finalists.append(candidate)
                    finalists.sort(key=lambda c:(-c['score']['damage'],sum(s.frames for s in c['steps'])))
                    finalists=finalists[:8]
                    best=finalists[0]
                # No-hit movement/setup branches can lead to later hits. Keep a bounded sample.
                if set(score['rejection_reasons']) <= {'no_damage','unresolved_hitstun'}:
                    # Ineffective normal presses must not displace actual chain extensions.
                    if not prefix_complete or candidate['group']!='normals' or score['damage']>candidate['parent_damage'] or candidate['parent_damage']==0:
                        survivors.append(candidate)
            emit_event(stage='searching',completed=completed,budget=rules['budget'],depth=depth,
                damage=best['score']['damage'] if best else 0,notation=best['notation'] if best else '',
                message=f'Tested {completed} input sequences.',elapsed=time.monotonic()-started)
            offset+=len(batch)
        if completed>=rules['budget'] or not survivors: break
        frontier=(game.select_frontier(survivors,rules['beam']) if hasattr(game,'select_frontier')
                  else select_frontier(survivors,rules['beam']))
    check_cancel()
    export=None
    validation_attempts=[]
    for candidate in finalists:
        emit_event(stage='validating',completed=completed,damage=candidate['score']['damage'],notation=candidate['notation'],
                   message='Checking ranked results against guard and jump escapes.' if rules['true_combo'] or getattr(game,'escape_checks',False) else 'Checking that ranked damage strings reproduce.')
        defenses=['neutral','stand','crouch','jump'] if rules['true_combo'] or getattr(game,'escape_checks',False) else ['neutral']
        records,manifest=run([Trial('best_'+d,candidate['steps'],tail=candidate.get('tail',rules['tail']),defense=d,repeats=3) for d in defenses])
        manifests.append(manifest)
        scores=[game.score(r,rules) for r in records]
        repeated=all(g['identical'] for g in repeatability(records).values())
        passed=repeated and all(s['candidate_valid'] and s['damage_events']==candidate['score']['damage_events'] for s in scores)
        checked={'steps':[asdict(s) for s in candidate['steps']],'tail':candidate.get('tail',rules['tail']),'damage':candidate['score']['damage'],
                'notation':candidate['notation'],'verified':bool(passed and rules['true_combo']),
                'reproduced':passed,'profile_sha256':profile_hash,'snapshot_sha256':snapshot_hash,'validation':scores,'starting_hitstun':starting_hitstun}
        checked['escape_checked']=passed and len(defenses)>1
        validation_attempts.append({'notation':checked['notation'],'damage':checked['damage'],'passed':passed})
        if export is None or passed: export=checked
        if passed: break
    result={'game':game.id,'game_profile':getattr(game,'definition',None),'profile_sha256':profile_hash,'starting_hitstun':starting_hitstun,'rules':rules,'best':export,'evaluated':completed,'simulator_frames':simulator_frames,
            'wall_seconds':time.monotonic()-started,'snapshot_sha256':snapshot_hash,'session':str(session),
            'validation_attempts':validation_attempts,'timing_observations':timing_observations,'model':policy.model_info,'model_calls':policy.calls,'manifests':manifests,
            'scope':'Best found within the selected input templates and budget; no global optimality claim.'}
    emit_event(stage='complete',completed=completed,damage=export['damage'] if export else 0,
               message=('Search finished.' if export['reproduced'] else 'No shortlisted route passed validation. The saved route is marked Failed validation.') if export else 'No valid damaging sequence found in this search.',result=result)


def execute_queue(config, emit_event=emit):
    snapshots=config.get('snapshots',[])
    if config['action']=='replay':
        return execute(config,emit_event)
    starters=(config['rules'].get('starters') or [config['rules'].get('starter','')]) if config['action']=='search' else ['']
    if not snapshots and len(starters)==1:
        return execute(config,emit_event)
    if not snapshots:
        snapshots=[{'file':config.get('snapshot_file','root.fs'),'source':''}]
    session=Path(config['session'])
    searches=[(state_index,snapshot,starter) for state_index,snapshot in enumerate(snapshots,1) for starter in starters]
    for index,(state_index,snapshot,starter) in enumerate(searches,1):
        if (session/'cancel.flag').exists(): raise Cancelled('Queue stopped. Completed results were kept.')
        context={'queue_index':index,'queue_total':len(searches),'state_index':state_index,'state_total':len(snapshots),
                 'snapshot_source':snapshot['source'],'starter':starter}
        emit_event(stage='starting',**context,completed=0,damage=0,notation='',depth=0,
                   message=f"Starting {'search' if config['action']=='search' else 'check'} {index} of {len(searches)}"+(f' with {starter}.' if starter else '.'))
        def forward(**event):
            event.update(context)
            if 'result' in event:
                event['result'].update(snapshot_source=snapshot['source'],starter=starter)
            if event.get('stage')=='complete': event['stage']='searching' if config['action']=='search' else 'checking'
            emit_event(**event)
        rules={**config['rules'],'starter':starter,'starters':[starter] if starter else []} if config['action']=='search' else config['rules']
        execute({**config,'snapshot_file':snapshot['file'],'rules':rules},forward)
    if (session/'cancel.flag').exists(): raise Cancelled('Queue stopped. Completed results were kept.')
    emit_event(stage='complete',message=f"Finished all {len(searches)} {'searches' if config['action']=='search' else 'save-state checks'}.")


def main():
    config=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    try:
        execute_queue(config)
    except Cancelled as exc:
        emit(stage='cancelled',message=str(exc))
    except Exception as exc:
        emit(stage='failed',message=str(exc))
        raise SystemExit(1)


if __name__=='__main__': main()
