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


def filter_disabled_buttons(actions, rules):
    disabled=set(rules.get('disabled_buttons', ()))
    return [action for action in actions if not any(disabled.intersection(step.buttons) for step in action.steps)]


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
    search_buttons = ('LP','LK','MP','MK','HP','HK')

    def public(self):
        return {'id': self.id, 'title': self.title, 'subtitle': self.subtitle,
                'moves':[{'name':a.name,'group':a.group,'buttons':sorted({b for step in a.steps for b in step.buttons})} for a in self.actions([g['id'] for g in self.groups])],
                'rom': self.rom, 'badge':self.badge, 'emulator': self.emulator_name, 'groups': self.groups,
                'status': 'Experimental adapter', 'player': 'Player 1', 'buttons': self.search_buttons,
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
        actions=custom+[a for a in self.actions(rules['groups']) if a.name not in rules.get('disabled_actions',[])]
        return filter_disabled_buttons(actions,rules)

    def validate_rules(self, rules):
        if any(set(step.buttons) & {'A1','A2'} for action in self.search_actions(rules) for step in action.steps):
            raise ValueError(f'A1/A2 are MVC2 assist buttons and are unavailable in {self.title}.')

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


from .flycast import MarvelVsCapcom2

class ThirdStrike(VampireSavior):
    id = 'street-fighter-iii-third-strike'
    title = 'Street Fighter III: 3rd Strike'
    subtitle = 'Fight for the Future'
    rom = 'sfiii3nr1'
    badge = '3S'
    vsav_ordering = False
    combo_validated = False
    default_snapshot = 'G:/Games/Fightcade/emulator/fbneo/savestates/sfiii3nr1 slot 01.fs'

    def __init__(self):
        import hashlib
        import json
        inputs = {code: {p: p.upper()+' '+name for p in ('p1','p2')}
                  for code, name in [('U','Up'),('D','Down'),('L','Left'),('R','Right'),
                                     ('LP','Weak Punch'),('MP','Medium Punch'),('HP','Strong Punch'),
                                     ('LK','Weak Kick'),('MK','Medium Kick'),('HK','Strong Kick')]}
        players = {}
        # CPS3 player bases and health from FBNeo training-mode/hitbox maps.
        # Hitstun is distinct from the stun gauge and displayed combo counter.
        for p, base, stocks, meter, hitstun in (
                ('p1',0x02068C6C,0x020695BE,0x020695B5,0x020288A8),
                ('p2',0x02069104,0x020695EB,0x020695E1,0x020288A9)):
            players[p] = {name: {'address': address, 'type': kind} for name,address,kind in (
                ('health',base+0x9F,'u8'),('x',base+0x64,'s16'),('y',base+0x68,'s16'),
                ('stocks',stocks,'u8'),('meter',meter,'u8'),('stun1',hitstun,'u8'))}
        self.telemetry = {'rom': self.rom, 'inputs': inputs, 'players': players}
        self.profile_sha256 = hashlib.sha256(json.dumps(self.telemetry,sort_keys=True).encode()).hexdigest()

    def public(self):
        value = super().public()
        value.update(combo_validated=self.combo_validated,
                     limits='Japan 990512 NO CD (sfiii3nr1). Experimental damage searches; true-combo verification requires live calibration. Generic normals, motions and movement; add character-specific moves as custom inputs.')
        return value

    def validate_initial(self, state):
        if not all(0 <= state[p]['health'] <= 160 for p in ('p1','p2')):
            raise ValueError('Third Strike health telemetry is outside 0-160.')

    def validate_rules(self, rules):
        super().validate_rules(rules)
        if rules['true_combo'] and not self.combo_validated:
            raise ValueError('Third Strike true-combo verification requires live hitstun and defensive calibration; disable Require a true combo.')
        if rules['resources'] == 'cap':
            raise ValueError('Third Strike EX moves spend partial meter; stock caps are not supported. Use save-state resources.')

    def landing_delays(self, trace, end_frame, limit):
        return []

    def score(self, record, rules):
        self.validate_rules(rules)
        for row in record['trace']:
            self.validate_initial(row)
        return super().score(record, rules)

    def session_script(self):
        from .game_profile import lua_value
        return 'COMBOCHAN_GAME = '+lua_value({**self.telemetry,'sha256':self.profile_sha256})+'\n'


class XMenVsStreetFighter(VampireSavior):
    id = 'x-men-vs-street-fighter'
    title = 'X-Men vs. Street Fighter'
    subtitle = 'Mutants meet world warriors'
    rom = 'xmvsf'
    badge = 'XS'
    vsav_ordering = False
    combo_validated = True
    escape_checks = True
    default_snapshot = 'G:/Games/Fightcade/emulator/fbneo/savestates/xmvsf slot 01.fs'

    def __init__(self):
        import hashlib
        import json
        inputs = {code: {p: p.upper()+' '+name for p in ('p1','p2')}
                  for code, name in [('U','Up'),('D','Down'),('L','Left'),('R','Right'),
                                     ('LP','Weak Punch'),('MP','Medium Punch'),('HP','Strong Punch'),
                                     ('LK','Weak Kick'),('MK','Medium Kick'),('HK','Strong Kick')]}
        players = {}
        # FBNeo training-mode xmvsf.lua and marvel-hitboxes.lua mappings.
        # Health banks follow the active slot; on-screen object positions are
        # always in the point object. Combo counters count hits dealt, so P2's
        # received-hit counter lives in P1's object (and vice versa).
        for p, base, counter in (('p1',0xFF4000,0xFF4510),('p2',0xFF4400,0xFF4110)):
            fields = {name: {'address': base+offset, 'type': kind} for name,offset,kind in (
                ('health',0x211,'u8'),('recoverable',0x21B,'u8'),
                ('stocks',0x214,'u8'),('meter',0x212,'u16'),
                ('x',0x0C,'s16'),('y',0x10,'s16'),('facing',0x4B,'u8'),
                ('state',0x06,'u16'),('active_character',0x220,'u8'))}
            for name in ('health','recoverable'):
                fields[name].update(selector_address=base+0x220,
                                    alternate_address=fields[name]['address']+0x800)
            fields['stun1'] = {'address':counter,'type':'u8'}
            fields['combo_hits'] = {'address':counter,'type':'u8'}
            players[p] = fields
        self.telemetry = {'rom':self.rom,'inputs':inputs,'players':players}
        self.profile_sha256 = hashlib.sha256(json.dumps(self.telemetry,sort_keys=True).encode()).hexdigest()

    def public(self):
        value = super().public()
        value.update(combo_validated=self.combo_validated,
                     limits='Euro 961004 (xmvsf). Active-character health, engine combo counters and defensive replay checks; calibrated on Rogue normal chains. Normals, motions, hypers and super jumps; add character-specific moves as custom inputs. Tag transitions are rejected.')
        return value

    def actions(self, groups):
        actions = super().actions(groups)
        if 'movement' in groups:
            actions.extend([Action('super jump',(Step(1,('D',)),Step(8,('U',))),'movement'),
                            Action('super jump forward',(Step(1,('D',)),Step(8,('U','F'))),'movement')])
        return actions

    def validate_initial(self, state):
        if not all(0 <= state[p]['health'] <= 144 for p in ('p1','p2')):
            raise ValueError('X-Men vs. Street Fighter health telemetry is outside 0-144.')
        if any(state[p].get('active_character') not in (0,1) for p in ('p1','p2')):
            raise ValueError('X-Men vs. Street Fighter active character must be point or anchor.')

    def validate_rules(self, rules):
        super().validate_rules(rules)
        if rules['true_combo'] and not self.combo_validated:
            raise ValueError('X-Men vs. Street Fighter true-combo verification requires live counter and defensive calibration; disable Require a true combo.')

    def landing_delays(self, trace, end_frame, limit):
        return []

    def score(self, record, rules):
        self.validate_rules(rules)
        for row in record['trace']:
            self.validate_initial(row)
        result = super().score(record, rules)
        initial = record['trace'][0]
        if any(row[p]['active_character'] != initial[p]['active_character']
               for row in record['trace'] for p in ('p1','p2')):
            result['candidate_valid'] = False
            result['rejection_reasons'].append('tag_or_character_transition')
        return result

    def session_script(self):
        from .game_profile import lua_value
        return 'COMBOCHAN_GAME = '+lua_value({**self.telemetry,'sha256':self.profile_sha256})+'\n'


GAMES = {game.id: game for game in (VampireSavior(), MarvelVsCapcom2(), ThirdStrike(), XMenVsStreetFighter())}


def get_game(game_id):
    try:
        return GAMES[game_id]
    except KeyError:
        raise ValueError('Unknown game adapter') from None
