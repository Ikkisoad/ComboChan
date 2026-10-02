"""Flycast Dojo MVC2 (Naomi) damage-search adapter.

Uncalibrated hitstun is deliberately absent. This adapter cannot certify combos.
"""
from pathlib import Path
import configparser
import hashlib
import json
import math
import shutil

from .bridge import Step
from .evaluate import trace_digest


class MarvelVsCapcom2:
    id = 'marvel-vs-capcom-2'
    title = 'Marvel vs. Capcom 2'
    subtitle = 'New Age of Heroes · Naomi'
    rom = 'mvsc2'
    emulator_name = 'Flycast Dojo'
    runner_path = 'bridge/flycast_runner.lua'
    state_extensions = ('.state',)
    executable_names = ('flycast.exe',)
    default_executable = 'G:/Games/Fightcade/emulator/flycast/flycast.exe'
    default_snapshot = 'G:/Games/Fightcade/emulator/flycast/data/mvsc2.state'
    combo_validated = False
    escape_checks = True
    vsav_ordering = False
    bridge_timeout = 600
    launch_message = 'Isolated Flycast launched. It loads the copied save automatically; keep its menus closed during experiments.'
    # Version binds results to the Naomi mapping and conservative scorer.
    profile_sha256 = hashlib.sha256(b'mvc2-naomi-assists-v5-2d7088-5a4-420-34').hexdigest()
    previous_input_profiles = frozenset(hashlib.sha256(stamp).hexdigest() for stamp in (
        b'mvc2-naomi-damage-v1-2d7088-5a4-420-34',
        b'mvc2-naomi-escape-v2-2d7088-5a4-420-34'))
    groups = (
        {'id': 'normals', 'label': 'Standing & crouching normals'},
        {'id': 'motions', 'label': 'Special move inputs'},
        {'id': 'movement', 'label': 'Walk, jump & dash'},
        {'id': 'assists', 'label': 'Partner assists'},
        {'id': 'supers', 'label': 'Hyper combos'},
    )
    search_buttons = ('LP','LK','HP','HK','A1','A2')

    def public(self):
        return {'id': self.id, 'title': self.title, 'subtitle': self.subtitle,
                'rom': self.rom, 'badge': 'M2', 'emulator': self.emulator_name,
                'groups': self.groups, 'player': 'Player 1', 'combo_validated': False,
                'buttons': self.search_buttons,
                'state_extensions': self.state_extensions,
                'status': 'Experimental escape checks',
                'moves': [{'name': a.name, 'group': a.group} for a in self.actions([g['id'] for g in self.groups])],
                'limits': 'Naomi mvsc2. A1/A2 call the selected partner assists; 236PP, 214PP and 236KK cover SonSon’s hypers. SonSon launcher and aerial continuations are prioritized when she is P1. Finalists face guard and jump attempts after the first hit. Hitstun is uncalibrated. Runs at normal speed.',
                'connection_steps': ['Prepare a session, then use Launch emulator to open its isolated Flycast copy.',
                                     'The copied save state loads automatically. Keep that window running with menus closed.',
                                     'Close the isolated Flycast window to return to your original session.'],
                'connection_note': 'Your original Flycast configuration and save slots stay intact. The session runner controls both players in the isolated window.'}

    def actions(self, groups):
        from .games import Action
        actions = []
        buttons = ('LP', 'LK', 'HP', 'HK')
        if 'normals' in groups:
            actions.append(Action('df.HP', (Step(1, ('D','F','HP')),), 'normals'))
            for button in buttons:
                actions += [Action(button, (Step(1, (button,)),), 'normals'),
                            Action('c.'+button, (Step(1, ('D', button)),), 'normals')]
        if 'motions' in groups:
            for name, motion in [('236', (('D',), ('D','F'), ('F',))),
                                 ('214', (('D',), ('D','B'), ('B',))),
                                 ('623', (('F',), ('D',), ('D','F')))]:
                for suffix, buttons_held in [(b, (b,)) for b in buttons]:
                    actions.append(Action(name+suffix, tuple(Step(2, d) for d in motion[:-1])+
                                          (Step(1, motion[-1]+buttons_held),), 'motions'))
        if 'assists' in groups:
            actions += [Action('Assist 1', (Step(1, ('A1',)),), 'assists'),
                        Action('Assist 2', (Step(1, ('A2',)),), 'assists')]
        if 'supers' in groups:
            for name,motion,buttons_held in [
                ('236PP', (('D',),('D','F'),('F',)), ('LP','HP')),
                ('214PP', (('D',),('D','B'),('B',)), ('LP','HP')),
                ('236KK', (('D',),('D','F'),('F',)), ('LK','HK')),
            ]:
                actions.append(Action(name, tuple(Step(2,d) for d in motion[:-1])+
                                      (Step(1,motion[-1]+buttons_held),), 'supers'))
        if 'movement' in groups:
            actions += [Action('jump cancel', (Step(8, ('U','F')),), 'movement'),
                        Action('walk forward', (Step(8, ('F',)),), 'movement'),
                        Action('jump forward', (Step(8, ('U','F')),), 'movement'),
                        Action('jump', (Step(8, ('U',)),), 'movement'),
                        Action('dash', (Step(1, ('LP','HP')),), 'movement')]
        return actions

    def search_actions(self, rules):
        from .games import Action, filter_disabled_buttons
        from .moves import parse_sequence
        custom = [Action(m['name'], parse_sequence(m['sequence']), 'custom')
                  for m in rules.get('custom_moves', []) if m['enabled']]
        actions=custom + [a for a in self.actions(rules['groups']) if a.name not in rules.get('disabled_actions', [])]
        return filter_disabled_buttons(actions,rules)

    def validate_rules(self, rules):
        if rules['true_combo']:
            raise ValueError('MVC2 hitstun is not calibrated. Turn off Require a true combo; results are damage strings.')
        for action in self.search_actions(rules):
            if any(set(step.buttons) & {'MP', 'MK'} for step in action.steps):
                raise ValueError('MVC2 uses LP/HP/LK/HK plus A1/A2 assists. MP/MK are not supported.')

    def replay_compatible(self, replay):
        profile=replay.get('profile_sha256')
        if profile==self.profile_sha256: return True
        if profile not in self.previous_input_profiles: return False
        return all(set(step['buttons']) <= {'U','D','L','R','F','B','LP','HP','LK','HK'}
                   for step in replay.get('steps',[]))

    def trial_tail(self, candidate, rules):
        names=candidate.get('action_names',[])
        if any(name in ('236PP','214PP','236KK') for name in names): return max(240,rules['tail'])
        if any(set(step.buttons) & {'A1','A2'} for step in candidate['steps']): return max(180,rules['tail'])
        return rules['tail']

    def landing_delays(self, trace, end_frame, limit):
        for previous,row in zip(trace[end_frame:],trace[end_frame+1:]):
            if previous['p1']['y']>1 and row['p1']['y']<=1:
                landing=row['frame']-end_frame
                return [d for d in (landing,landing+1,landing-1) if 0<=d<=limit]
        return []

    def annotate_candidate(self,candidate,trace,end_frame,rules):
        candidate['trajectory']=trace[end_frame:end_frame+rules.get('max_delay',60)+12]
        candidate['launch_observed']=any(row['p2']['y']>80 for row in trace[end_frame:])
        candidate['airborne_observed']=any(row['p1']['y']>1 for row in trace[end_frame:])

    def order_continuations(self,candidates,parent,rules):
        # Only SonSon gets character-specific priorities. Never treat a move name
        # as evidence that it launched or connected: use the observed trajectory.
        if parent['state']['p1'].get('character')!=20:
            return candidates
        names=parent.get('action_names',[])
        if not names:
            starters=['df.HP','236PP','Assist 1','Assist 2','214PP','236KK','c.HK','LP','HP','c.LK']
            return sorted(candidates,key=lambda c:(starters.index(c['last']) if c['last'] in starters else len(starters),c['_timing_round'],c['_action_order']))
        airborne=parent.get('airborne_observed',False)
        if parent.get('launch_observed') and not airborne:
            preferred=['jump cancel','jump forward','jump']
            contacts=parent.get('contact_delays',[])
            target=(contacts[0]+3) if contacts else 8
            return sorted(candidates,key=lambda c:(preferred.index(c['last']) if c['last'] in preferred else len(preferred),abs(c['delay']-target),c['_action_order']))
        if airborne:
            # Medium air normals are repeated light inputs in MVC2, not MP/MK
            # (which denote the unsupported assist aliases in this adapter).
            jump_index=max((i for i,n in enumerate(names) if n in ('jump cancel','jump forward','jump')),default=-1)
            chain=names[jump_index+1:]
            sequence=['LP','LK','LP','LK','HP','HK']
            preferred=sequence[min(len(chain),len(sequence)-1)]
            trajectory=parent.get('trajectory',[])
            def priority(c):
                target=c['delay']+6
                row=trajectory[min(target,len(trajectory)-1)] if trajectory else None
                if row:
                    a,b=row['p1'],row['p2']
                    aligned=abs(a['y']-b['y'])+0.25*abs(a['x']-b['x'])
                    if a['y']<=1 or b['y']<=1: aligned+=1000
                else: aligned=0
                contacts=parent.get('contact_delays',[])
                # After an air hit, cancel around contact; after jumping, use
                # the earliest predicted alignment of both airborne characters.
                timing=abs(c['delay']-(contacts[0]+1)) if contacts else aligned+c['delay']*.5
                return (c['last']!=preferred,c['last'] not in ('LP','LK','HP','HK'),timing,c['_action_order'])
            return sorted(candidates,key=priority)
        return candidates

    def select_frontier(self,survivors,width):
        from .dashboard_worker import select_frontier
        selected=[]
        # Keep a launcher and an airborne setup even if a grounded special did
        # more immediate damage. Remaining slots still rank by measured damage.
        for predicate in (lambda c:c.get('airborne_observed') and c.get('last') not in ('236PP','214PP','236KK'),
                          lambda c:c.get('launch_observed') and not c.get('airborne_observed')):
            options=[c for c in survivors if predicate(c) and all(c is not x for x in selected)]
            if options and len(selected)<width:
                selected.append(max(options,key=lambda c:c['score']['damage']))
        selected.extend(c for c in select_frontier(survivors,width) if all(c is not x for x in selected))
        return selected[:width]

    def validate_initial(self, state):
        if state.get('in_match') != 1:
            raise ValueError('Save an active MVC2 match with both point characters on screen.')
        for player in ('p1', 'p2'):
            p = state[player]
            if not (0 < p['health'] <= 144 and 0 <= p['stocks'] <= 5 and
                    p['active_count'] == 1 and 0 <= p['character'] <= 58 and
                    all(math.isfinite(p[k]) and abs(p[k]) < 10000 for k in ('x','y'))):
                raise ValueError('Unsupported MVC2 state or memory mapping. Use a live Naomi match without assists or KOs.')

    def score(self, record, rules):
        self.validate_rules(rules)
        trace = record['trace']
        if len(trace) < 2 or [r['frame'] for r in trace] != list(range(len(trace))):
            raise ValueError('Missing or noncontiguous trace')
        self.validate_initial(trace[0])
        hits, healing, spent = [], 0, 0
        reasons = []
        for previous, row in zip(trace, trace[1:]):
            delta = previous['p2']['health'] - row['p2']['health']
            if delta > 0: hits.append({'frame': row['frame'], 'damage': delta})
            healing += max(0, -delta)
            spent += max(0, previous['p1']['stocks'] - row['p1']['stocks'])
        for row in trace:
            # The Naomi byte is 1 with only the point character and 2 while a
            # partner is present. Require it to match observed P1 active slots.
            if row.get('in_match') != row['p1']['active_count']: reasons.append('not_in_match')
            for side in ('p1','p2'):
                p, original = row[side], trace[0][side]
                if p['slot'] != original['slot'] or p['character'] != original['character'] or not (1 <= p['active_count'] <= (3 if side=='p1' else 1)):
                    reasons.append('tag_or_assist')
                if any(h <= 0 for h in p['team_health']): reasons.append('ko_or_life_transition')
                if not 0 <= p['health'] <= 144: reasons.append('invalid_health')
        if not hits: reasons.append('no_damage')
        if healing: reasons.append('health_increased')
        if rules['resources'] == 'cap' and spent > rules['stock_cap']: reasons.append('meter_spent')
        # No hitstun claim: a quiet tail only bounds observed damage.
        if any(h['frame'] > len(trace)-11 for h in hits): reasons.append('unresolved_damage')
        return {'id': record['id'], 'damage': sum(h['damage'] for h in hits),
                'health_loss': trace[0]['p2']['health']-trace[-1]['p2']['health'],
                'recoverable_pool_loss': None, 'combo_counter_available': False,
                'starting_hitstun': None, 'damage_events': hits, 'hit_count': len(hits),
                'gaps': [], 'healing': healing, 'stocks_spent': spent, 'settled': None,
                'candidate_valid': not reasons, 'rejection_reasons': sorted(set(reasons)),
                'defense': record['defense'], 'trace_sha256': trace_digest(trace),
                'validation': 'damage_only_unvalidated_hitstun', 'frames': len(trace)-1}

    def session_script(self):
        return 'COMBOCHAN_PROFILE_SHA256 = "'+self.profile_sha256+'"\n'

    def prepare_runtime(self, executable, session, snapshots):
        """Portable private emulator directory; never write the source installation."""
        source = Path(executable).resolve().parent
        rom = source/'ROMs/mvsc2.zip'
        if not rom.is_file():
            raise ValueError('Place your Naomi mvsc2.zip in the selected Flycast installation’s ROMs folder.')
        if not (source/'data/naomi.zip').is_file():
            raise ValueError('The selected Flycast installation needs its Naomi BIOS in data/naomi.zip.')
        runtime = session/'flycast'
        (runtime/'data').mkdir(parents=True)
        for file in [Path(executable), *source.glob('*.dll')]:
            shutil.copy2(file, runtime/file.name)
        shutil.copy2(source/'data/naomi.zip', runtime/'data/naomi.zip')
        for suffix in ('eeprom', 'nvmem'):
            file = source/f'data/mvsc2.zip.{suffix}'
            if file.is_file(): shutil.copy2(file, runtime/'data'/file.name)
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        cfg.optionxform = str
        if (source/'emu.cfg').exists(): cfg.read(source/'emu.cfg', encoding='utf-8-sig')
        overrides = {
            'config': {'LuaFileName':'flycast.lua', 'rend.ThreadedRendering':'no',
                       'Dreamcast.AutoLoadState':'no', 'Dreamcast.AutoSaveState':'no',
                       'Dreamcast.SavestateSlot':'9', 'aica.Volume':'0'},
            'dojo': {'Enable':'no', 'Training':'no', 'EnableTrainingLua':'no',
                     'IgnoreNetSave':'yes', 'Offline':'yes', 'TestGame':'no',
                     'EnableMatchCode':'no', 'RecordMatches':'no', 'GameEntry':'', 'Quark':''},
            'network': {'Enable':'no', 'GGPO':'no'},
            'window': {'fullscreen':'no', 'maximized':'no', 'width':'960','height':'720'},
        }
        for section, values in overrides.items():
            if section not in cfg: cfg[section] = {}
            cfg[section].update(values)
        with (runtime/'emu.cfg').open('w', encoding='utf-8') as f: cfg.write(f)
        # Lua bootstrap lives in Flycast’s config directory; its lookup is relative.
        from .game_profile import lua_value
        (runtime/'flycast.lua').write_text('COMBOCHAN_RUNTIME_DIR = '+lua_value(runtime.as_posix()+'/')+
                                           '\nreturn assert(loadfile('+lua_value((session/'connect.lua').as_posix())+'))()\n', encoding='ascii')
        (runtime/'launch.json').write_text(json.dumps({'rom': str(rom)}), encoding='utf-8')

    def launch_arguments(self, executable, script):
        runtime = Path(script).parent/'flycast'
        rom = json.loads((runtime/'launch.json').read_text(encoding='utf-8'))['rom']
        return [str(runtime/'flycast.exe'), rom]
