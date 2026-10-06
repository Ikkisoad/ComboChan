"""Scenario-local timing observations; never authoritative character frame data."""


def observe(action, trace, score):
    attacks={'LP','MP','HP','LK','MK','HK','A1','A2'}
    elapsed=0;press=None
    for step in action.steps:
        if attacks.intersection(step.buttons): press=elapsed+1;break
        elapsed+=step.frames
    events=score.get('damage_events',[])
    contact=events[0]['frame'] if events else None
    recovery=None
    if events:
        last=events[-1]['frame']
        rows=trace[last:]
        # A combo counter can be a continuity signal; it is not hitstun duration.
        if rows and all(type(r['p2'].get('stun1')) is int and 'combo_hits' not in r['p2'] for r in rows):
            recovery=next((r['frame'] for r in rows if not (r['p2'].get('stun1') or r['p2'].get('stun2'))),None)
    return {'contact_frame':contact,'contact_latency':contact-press+1 if contact is not None and press is not None and contact>=press else None,
            'hitstun_frames':recovery-events[-1]['frame'] if recovery is not None else None,
            'startup_frames':None,'recovery_frames':None,'frame_advantage':None,
            'damage':score['damage'],'scope':'Observed from this root state; contact latency includes spacing, hitstop and input buffering.'}


def preferred_delays(parent, action, observation, limit):
    """Prioritize cancel contact and estimated link deadlines, without pruning."""
    end=sum(s.frames for s in parent['steps'])
    duration=sum(s.frames for s in action.steps)
    contacts=parent.get('contact_frames',[])
    # Finish command entry at contact to probe cancels, regardless of recovery.
    cancel=[contact-duration+1+shift for contact in contacts for shift in (0,1,-1,2)]
    latency=(observation or {}).get('contact_latency')
    deadline=parent.get('stun_ends_at')
    links=[]
    if latency is not None and deadline is not None:
        latest=deadline-end-duration-latency
        links=[latest+shift for shift in (0,-1,-2,1)]
    return list(dict.fromkeys(d for d in cancel+links if 0<=d<=limit))


def stun_end(trace, score):
    hits=score.get('damage_events',[])
    if not hits: return None
    rows=trace[hits[-1]['frame']:]
    if not rows or any(type(r['p2'].get('stun1')) is not int or 'combo_hits' in r['p2'] for r in rows): return None
    return next((r['frame'] for r in rows if not (r['p2'].get('stun1') or r['p2'].get('stun2'))),None)
