"""Data-only custom move notation; no executable scripts."""
from .bridge import Step


def parse_sequence(text):
    if not isinstance(text,str) or not text.strip() or len(text)>2000:
        raise ValueError('Enter a move sequence, for example LP, N, LP, F, LK, HP.')
    steps=[]
    for part in text.upper().split(','):
        fields=part.strip().split(':')
        if len(fields)>2: raise ValueError('Use INPUT:frames, separated by commas.')
        frames=1
        if len(fields)==2:
            if not fields[1].strip().isdigit(): raise ValueError('Frame durations must be whole numbers.')
            frames=int(fields[1])
        buttons=fields[0].strip()
        if not buttons: raise ValueError('Empty input in move sequence.')
        held=() if buttons=='N' else tuple(b.strip() for b in buttons.split('+'))
        steps.append(Step(frames,held))
    if len(steps)>64 or sum(s.frames for s in steps)>240:
        raise ValueError('A custom move may contain at most 64 steps and 240 frames.')
    return tuple(steps)


def validate_custom_moves(value):
    if not isinstance(value,list) or len(value)>32: raise ValueError('Use at most 32 custom moves.')
    result=[]; names=set()
    for move in value:
        if not isinstance(move,dict): raise ValueError('Invalid custom move.')
        name=move.get('name'); sequence=move.get('sequence'); enabled=move.get('enabled',True)
        if not isinstance(name,str) or not 1<=len(name.strip())<=80: raise ValueError('Move names must contain 1–80 characters.')
        name=name.strip()
        if name.casefold() in names: raise ValueError('Custom move names must be unique.')
        if type(enabled) is not bool: raise ValueError('Move enabled must be a boolean.')
        parse_sequence(sequence);names.add(name.casefold())
        result.append({'name':name,'sequence':sequence.strip(),'enabled':enabled})
    return result
