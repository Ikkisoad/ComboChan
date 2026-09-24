"""User-authored, data-only FBNeo game profiles."""
import argparse
import hashlib
import json
import re
from pathlib import Path

from .bridge import BUTTONS
from .games import Action, VampireSavior
from .moves import parse_sequence

FIELDS = {'health', 'recoverable', 'stocks', 'meter', 'facing', 'combo_hits',
          'stun1', 'stun2', 'x', 'y', 'state'}
REQUIRED = {'health', 'x', 'stun1'}
DIRECTIONS = {'U', 'D', 'L', 'R'}


def lua_value(value):
    """Serialize validated data without interpolating executable Lua."""
    if isinstance(value, str):
        return '"' + ''.join(chr(b) if 32 <= b < 127 and b not in (34, 92)
                             else '\\%03d' % b for b in value.encode('utf-8')) + '"'
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is int:
        return str(value)
    if isinstance(value, dict):
        return '{' + ','.join('[' + lua_value(k) + ']=' + lua_value(v) for k, v in value.items()) + '}'
    raise ValueError('Unsupported Lua profile value')


def validate_profile(data):
    if not isinstance(data, dict):
        raise ValueError('Game profile must be an object.')
    data = json.loads(json.dumps(data))
    allowed = {'version', 'id', 'title', 'rom', 'health_max', 'inputs', 'players', 'moves', 'combo_validated'}
    if set(data) != allowed:
        raise ValueError('Profile fields must be: ' + ', '.join(sorted(allowed)))
    if type(data['version']) is not int or data['version'] != 1:
        raise ValueError('Unsupported profile version.')
    for key in ('id', 'rom'):
        if not isinstance(data[key], str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', data[key]):
            raise ValueError(f'{key} must use 1-64 lowercase letters, digits, underscores or hyphens.')
    if data['id'] == 'vampire-savior':
        raise ValueError('Use a unique id; vampire-savior is reserved.')
    if not isinstance(data['title'], str) or not 1 <= len(data['title'].strip()) <= 80:
        raise ValueError('Enter a game title (1-80 characters).')
    if type(data['health_max']) is not int or not 1 <= data['health_max'] <= 65535:
        raise ValueError('Set health_max to the maximum health value (1-65535).')
    if type(data['combo_validated']) is not bool:
        raise ValueError('combo_validated must be a boolean.')
    inputs = data['inputs']
    if not isinstance(inputs, dict) or not DIRECTIONS <= set(inputs) or not set(inputs) <= BUTTONS - {'F', 'B'}:
        raise ValueError('inputs must map U/D/L/R and supported attack aliases; F/B are derived from x.')
    for code, names in inputs.items():
        if not isinstance(names, dict) or set(names) != {'p1', 'p2'}:
            raise ValueError(f'inputs.{code} needs p1 and p2 joypad names.')
        for name in names.values():
            if not isinstance(name, str) or not 1 <= len(name) <= 100 or any(ord(c) < 32 for c in name):
                raise ValueError(f'Enter exact FBNeo joypad names for inputs.{code}.')
    names = [name for mapping in inputs.values() for name in mapping.values()]
    if len(names) != len(set(names)):
        raise ValueError('Each player/input mapping must have a unique joypad name.')
    players = data['players']
    if not isinstance(players, dict) or set(players) != {'p1', 'p2'}:
        raise ValueError('players must contain p1 and p2 telemetry maps.')
    for player, fields in players.items():
        if not isinstance(fields, dict) or not REQUIRED <= set(fields) or not set(fields) <= FIELDS:
            raise ValueError(f'{player} requires health, x and stun1; unsupported telemetry field found or required field missing.')
        for name, spec in fields.items():
            if not isinstance(spec, dict) or not {'address', 'type'} <= set(spec) or not set(spec) <= {'address', 'type', 'mask', 'equals'}:
                raise ValueError(f'{player}.{name} requires address/type and optional mask/equals.')
            address = spec['address']
            if isinstance(address, str):
                try: address = int(address, 0)
                except ValueError: raise ValueError(f'Set {player}.{name}.address to a decimal or 0x hexadecimal address.') from None
            if type(address) is not int or not 0 <= address <= 0xFFFFFFFE:
                raise ValueError(f'Set {player}.{name}.address to a valid memory address.')
            spec['address'] = address
            if spec['type'] not in ('u8', 'u16', 's16'):
                raise ValueError(f'{player}.{name}.type must be u8, u16 or s16.')
            for option in ('mask', 'equals'):
                if option in spec and (type(spec[option]) is not int or not 0 <= spec[option] <= 65535):
                    raise ValueError(f'{player}.{name}.{option} must be an integer from 0 to 65535.')
    moves = data['moves']
    if not isinstance(moves, list) or not 1 <= len(moves) <= 128:
        raise ValueError('Define 1-128 moves.')
    seen = set()
    for move in moves:
        if not isinstance(move, dict) or set(move) != {'name', 'sequence'}:
            raise ValueError('Each move requires name and sequence.')
        name = move['name']
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or name.casefold() in seen:
            raise ValueError('Move names must be nonempty and unique (1-80 characters).')
        seen.add(name.casefold())
        steps = parse_sequence(move['sequence'])
        if any(set(step.buttons) - (set(inputs) | {'F', 'B'}) for step in steps):
            raise ValueError(f'Move {name} uses an unmapped button.')
    return data


class ConfiguredGame(VampireSavior):
    groups = ({'id': 'configured', 'label': 'Configured moves'},)
    badge = 'CG'
    subtitle = 'Manually configured FBNeo game'
    vsav_ordering = False

    def __init__(self, profile):
        self.definition = validate_profile(profile)
        for key in ('id', 'title', 'rom'):
            setattr(self, key, self.definition[key])
        self.profile_sha256 = hashlib.sha256(json.dumps(self.definition, sort_keys=True).encode()).hexdigest()

    def public(self):
        value = super().public()
        value.update(combo_validated=self.definition['combo_validated'],status='User-configured adapter', limits='User-supplied memory and input mappings. Validate against known game outcomes before trusting results.')
        return value

    def actions(self, groups):
        return [Action(m['name'], parse_sequence(m['sequence']), 'configured')
                for m in self.definition['moves']] if 'configured' in groups else []

    def search_actions(self, rules):
        actions = super().search_actions(rules)
        allowed = set(self.definition['inputs']) | {'F', 'B'}
        if any(set(s.buttons) - allowed for a in actions for s in a.steps):
            raise ValueError('A custom move uses a button absent from the game profile.')
        return actions

    def validate_rules(self, rules):
        if rules['true_combo'] and not self.definition['combo_validated']:
            raise ValueError('Validate hitstun and guard/jump controls, then set combo_validated=true; otherwise disable Require a true combo.')
        if rules['resources'] == 'cap' and 'stocks' not in self.definition['players']['p1']:
            raise ValueError('A stock cap requires a mapped P1 stocks field.')

    def validate_initial(self, state):
        if not all(0 <= state[p]['health'] <= self.definition['health_max'] for p in ('p1', 'p2')):
            raise ValueError('Health telemetry is outside the configured range.')

    def score(self, record, rules):
        self.validate_rules(rules)
        for row in record['trace']:
            self.validate_initial(row)
        return super().score(record, rules)

    def landing_delays(self, trace, end_frame, limit):
        return []

    def session_script(self):
        settings = {key: self.definition[key] for key in ('rom', 'inputs', 'players')}
        settings['sha256'] = self.profile_sha256
        return 'COMBOCHAN_GAME = ' + lua_value(settings) + '\n'


def template():
    return {'version': 1, 'id': 'my-game', 'title': 'My Game', 'rom': 'replace-rom-name',
            'health_max': None, 'combo_validated': False,
            'inputs': {code: {'p1': f'P1 {name}', 'p2': f'P2 {name}'}
                       for code, name in [('U', 'Up'), ('D', 'Down'), ('L', 'Left'), ('R', 'Right'), ('LP', 'Button 1')]},
            'players': {p: {name: {'address': None, 'type': kind} for name, kind in
                           [('health', 'u16'), ('x', 's16'), ('stun1', 'u8')]} for p in ('p1', 'p2')},
            'moves': [{'name': 'Attack', 'sequence': 'LP'}, {'name': 'Crouching attack', 'sequence': 'D+LP'}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('template', 'validate'))
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'template':
            with args.path.open('x', encoding='utf-8') as output:
                json.dump(template(), output, indent=2)
                output.write('\n')
            print(f'Created {args.path}. Fill in the null values and game-specific mappings.')
        else:
            game = ConfiguredGame(json.loads(args.path.read_text(encoding='utf-8')))
            print(f'Valid profile: {game.title} ({game.rom}); live calibration is still required.')
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + '\n')


if __name__ == '__main__':
    main()
