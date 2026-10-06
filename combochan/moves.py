"""Data-only custom move notation; no executable scripts."""
import re
from .bridge import Step


def parse_starter(text, actions):
    """Resolve a compact move prefix against the enabled move library."""
    if not isinstance(text,str) or not text.strip() or len(text)>5400:
        raise ValueError('Enter a starter such as 2LK2LK or 2HP (at most 5400 characters).')
    names={}
    for action in actions:
        names.setdefault(action.name.casefold(),action.name)
    # Exact library/custom names take precedence over shorthand aliases.
    for button in ('LP','LK','MP','MK','HP','HK'):
        for shorthand,name in (('2'+button,'c.'+button),('5'+button,button),('3'+button,'df.'+button)):
            if name.casefold() in names: names.setdefault(shorthand.casefold(),names[name.casefold()])
    tokens=sorted(names,key=len,reverse=True)
    result=[]
    for part in re.split(r'\s*[,>]\s*',text.strip().casefold()):
        remaining=part.strip()
        if not remaining: raise ValueError('Empty move in starter. Use 2LK2LK or 2LK > 2LK.')
        while remaining:
            token=next((token for token in tokens if remaining.startswith(token)),None)
            if token is None:
                raise ValueError(f'Unknown or disabled move in starter "{text}": "{remaining}". Use enabled move names or shorthand such as 2LK2LK.')
            result.append(names[token])
            if len(result)>64: raise ValueError('A starter may contain at most 64 moves.')
            remaining=remaining[len(token):].lstrip()
    return result


def parse_sequence(text):
    if not isinstance(text,str) or not text.strip() or len(text)>2000:
        raise ValueError('Enter a move sequence, for example LP, N, LP, F, LK, HP.')
    # Numpad directions are relative to facing, like the existing F/B protocol.
    # Each motion direction gets two frames; the final direction/button is a tap.
    motion=re.fullmatch(r'([1-9]+)((?:LP|MP|HP|LK|MK|HK)(?:\+(?:LP|MP|HP|LK|MK|HK))*)',text.strip().upper())
    if motion:
        directions={'1':('D','B'),'2':('D',),'3':('D','F'),'4':('B',),'5':(),
                    '6':('F',),'7':('U','B'),'8':('U',),'9':('U','F')}
        path,buttons=motion.groups()
        if len(path)>64: raise ValueError('A custom move may contain at most 64 steps and 240 frames.')
        return tuple(Step(2,directions[n]) for n in path[:-1])+(Step(1,directions[path[-1]]+tuple(buttons.split('+'))),)
    if re.fullmatch(r'[1-9]+[PK]',text.strip().upper()):
        raise ValueError('Choose a button strength, such as 41236LK or 41236HK, or use Add special move to add every available strength.')
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
