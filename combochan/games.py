"""Game plugins: the dashboard only depends on this adapter contract."""
from dataclasses import dataclass
import ctypes
import os
import tempfile
from pathlib import Path
from .bridge import Step
from .evaluate import evaluate
from .moves import parse_sequence


@dataclass(frozen=True)
class Action:
    name: str
    steps: tuple[Step, ...]
    group: str


class VampireSavior:
    id = 'vampire-savior'
    title = 'Vampire Savior'
    subtitle = 'The Lord of Vampire'
    rom = 'vsavj'
    emulator_name = 'Fightcade FBNeo'
    runner_path = 'bridge/runner.lua'
    badge = 'VS'
    state_extensions = ('.fs',)
    executable_names = ('fcadefbneo.exe',)
    groups = (
        {'id': 'normals', 'label': 'Standing & crouching normals'},
        {'id': 'motions', 'label': 'Motion inputs & two-button variants'},
        {'id': 'movement', 'label': 'Walk, jump & dash inputs'},
    )

    def public(self):
        return {'id': self.id, 'title': self.title, 'subtitle': self.subtitle,
                'moves':[{'name':a.name,'group':a.group} for a in self.actions([g['id'] for g in self.groups])],
                'rom': self.rom, 'badge':self.badge, 'emulator': self.emulator_name, 'groups': self.groups,
                'status': 'Experimental adapter', 'player': 'Player 1',
                'limits': 'Japan ROM (vsavj). Searches selected input templates; not every possible input sequence. Character-specific specials, charges and air routes are not exhaustive.'}

    def actions(self, groups):
        result = []
        buttons = ('LP','LK','MP','MK','HP','HK')
        if 'normals' in groups:
            for button in buttons:
                result += [Action(button,(Step(1,(button,)),),'normals'),
                           Action('c.'+button,(Step(1,('D',button)),),'normals')]
        if 'motions' in groups:
            for name, motion in [('236',( ('D',),('D','F'),('F',))),
                                 ('214',( ('D',),('D','B'),('B',))),
                                 ('623',( ('F',),('D',),('D','F')) )]:
                for button in buttons:
                    steps=tuple(Step(2,direction) for direction in motion[:-1])
                    result.append(Action(name+button,steps+(Step(1,motion[-1]+(button,)),),'motions'))
                for suffix, pair in [('PP',('LP','MP')),('KK',('LK','MK'))]:
                    steps=tuple(Step(2,direction) for direction in motion[:-1])
                    result.append(Action(name+suffix,steps+(Step(1,motion[-1]+pair),),'motions'))
        if 'movement' in groups:
            result.extend([Action('walk forward',(Step(8,('F',)),),'movement'),
                           Action('jump forward',(Step(8,('U','F')),),'movement'),
                           Action('jump',(Step(8,('U',)),),'movement'),
                           Action('dash',(Step(1,('F',)),Step(1),Step(1,('F',))),'movement')])
        return result

    def search_actions(self, rules):
        custom=[Action(m['name'],parse_sequence(m['sequence']),'custom') for m in rules.get('custom_moves',[]) if m['enabled']]
        return custom+[a for a in self.actions(rules['groups']) if a.name not in rules.get('disabled_actions',[])]

    def landing_delays(self, trace, end_frame, limit):
        # vsavj telemetry uses y=40 for the floor in the supported adapter.
        for previous,row in zip(trace[end_frame:],trace[end_frame+1:]):
            if previous['p1']['y']>40 and row['p1']['y']<=40:
                landing=row['frame']-end_frame
                return [d for d in (landing,landing+1,landing-1,landing+2,landing-2) if 0<=d<=limit]
        return []

    def validate_initial(self, state):
        if not all(0<=state[player]['health']<=288 for player in ('p1','p2')):
            raise ValueError('Health telemetry is outside the supported game range.')

    def launch_arguments(self, executable, script):
        # This FBNeo build truncates quoted command-line arguments by one character.
        # A Windows short path avoids quotes without changing the user's filenames.
        argument = str(Path(script).resolve())
        if any(character.isspace() for character in argument) and os.name == 'nt':
            buffer = ctypes.create_unicode_buffer(32768)
            length = ctypes.windll.kernel32.GetShortPathNameW(argument, buffer, len(buffer))
            if 0 < length < len(buffer): argument = buffer.value
        if any(character.isspace() for character in argument):
            folder = Path(tempfile.mkdtemp(prefix='combochan-'))
            bootstrap = folder/'connect.lua'
            if any(character.isspace() for character in str(bootstrap)):
                folder.rmdir()
                raise ValueError('FBNeo cannot parse the script path. Use the manual connection steps below.')
            target = Path(script).resolve().as_posix()
            quoted = '"'+''.join(chr(b) if 32<=b<127 and b not in (34,92) else '\\%03d'%b for b in target.encode('utf-8'))+'"'
            # loadfile returns before the Lua chunk runs, so frameadvance can yield.
            bootstrap.write_text('return assert(loadfile('+quoted+'))()\n',encoding='ascii')
            argument = str(bootstrap)
        return [str(executable),self.rom,argument]

    def score(self, record, rules):
        cap = None if rules['resources'] == 'state' else rules['stock_cap']
        return evaluate(record, max_stocks=cap, require_combo=rules['true_combo'])


GAMES = {game.id: game for game in (VampireSavior(),)}


def get_game(game_id):
    try:
        return GAMES[game_id]
    except KeyError:
        raise ValueError('Unknown game adapter') from None
