import json
import ctypes
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from combochan.bridge import Bridge, Step
from combochan.dashboard import Dashboard, DEFAULT_RULES, validate_rules
from combochan.games import get_game
from combochan.dashboard_worker import execute, depth_quota, continuation_candidates, escape_mismatch, reserve_finisher_trial


GAME = get_game('marvel-vs-capcom-2')
RULES = {**DEFAULT_RULES, 'true_combo': False}


def damage_record():
    """Synthetic scorer fixture, not live emulator evidence."""
    trace = []
    for frame in range(20):
        p = {'health': 144, 'team_health': [144, 144, 144], 'slot': 1,
             'active_count': 1, 'character': 20, 'stocks': 1,
             'x': -100.0, 'y': 0.0, 'stun1': None, 'stun2': None,
             'recoverable': None}
        q = {**p, 'character': 23, 'x': 0.0, 'health': 141 if frame >= 3 else 144,
             'team_health': [141 if frame >= 3 else 144, 144, 144]}
        trace.append({'frame': frame, 'p1': p, 'p2': q, 'in_match': 1})
    return {'id': 'damage', 'defense': 'neutral', 'trace': trace}


class FlycastScoringTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get('COMBOCHAN_TEST_LUA51'), 'Set COMBOCHAN_TEST_LUA51 to exercise Lua point tracking')
    def test_lua_tracks_new_point_when_original_character_returns_as_assist(self):
        runner=(Path(__file__).resolve().parents[1]/'bridge/flycast_runner.lua').read_text(encoding='utf-8')
        player_code=runner[runner.index('local point_slots={}'):runner.index('local function sample(frame)')]
        script='''
local values={}
local JSON_NULL={}
local memory={read8=function(a) return values[a] or 0 end,
 read16=function(a) return values[a] or 144 end,read32f=function() return 0 end}
local first=0x0c2d7088
local second=first+0xb48
values[first]=1;values[first+1]=20;values[second+1]=5
'''+player_code+'''
assert(player(1).slot==1)
values[first]=0;values[second]=1
assert(player(1).slot==2)
values[first]=1
local observed=player(1)
assert(observed.slot==2 and observed.character==5 and observed.active_count==2)
'''
        dll=ctypes.CDLL(os.environ['COMBOCHAN_TEST_LUA51'])
        dll.luaL_newstate.restype=ctypes.c_void_p
        dll.luaL_openlibs.argtypes=[ctypes.c_void_p]
        dll.luaL_loadstring.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
        dll.lua_pcall.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_int,ctypes.c_int]
        dll.lua_tolstring.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]
        dll.lua_tolstring.restype=ctypes.c_char_p
        dll.lua_close.argtypes=[ctypes.c_void_p]
        state=dll.luaL_newstate()
        try:
            dll.luaL_openlibs(state)
            status=dll.luaL_loadstring(state,script.encode())
            if not status: status=dll.lua_pcall(state,0,0,0)
            self.assertEqual(status,0,dll.lua_tolstring(state,-1,None) if status else '')
        finally: dll.lua_close(state)

    def test_tags_are_optional_and_use_simultaneous_attack_pairs(self):
        actions={a.name:a for a in GAME.actions(['tags'])}
        self.assertEqual(actions['Tag 1'].steps,(Step(1,('LP','LK')),))
        self.assertEqual(actions['Tag 2'].steps,(Step(1,('HP','HK')),))
        self.assertNotIn('tags',validate_rules({'true_combo':False},GAME)['groups'])
        rules=validate_rules({**RULES,'groups':['tags'],'starters':['Tag 2']},GAME)
        self.assertEqual(rules['starters'],['Tag 2'])
        with self.assertRaisesRegex(ValueError,'Enable at least'):
            validate_rules({**rules,'disabled_buttons':['LP','HP']},GAME)
        self.assertEqual(GAME.trial_tail({'action_names':['Tag 1'],'steps':actions['Tag 1'].steps},RULES),240)

    def test_enabled_p1_tag_accepts_same_roster_and_preserves_damage(self):
        record=damage_record()
        for row in record['trace']:
            row['p1']['team_characters']=[20,5,7]
            row['p1']['team_health']=[144,130,100]
            if row['frame']>=4: row['p1'].update(slot=2,character=5,health=130)
        self.assertIn('tag_or_assist',GAME.score(record,RULES)['rejection_reasons'])
        tags={**RULES,'groups':['normals','tags']}
        score=GAME.score(record,tags)
        self.assertTrue(score['candidate_valid'])
        self.assertEqual(score['damage'],3)
        record['trace'][-1]['p1']['character']=9
        self.assertIn('tag_or_assist',GAME.score(record,tags)['rejection_reasons'])

    def test_tags_never_allow_opponent_swap_or_disable_ko_checks(self):
        rules={**RULES,'groups':['tags']}
        record=damage_record();record['trace'][-1]['p2'].update(slot=2,character=5)
        self.assertIn('tag_or_assist',GAME.score(record,rules)['rejection_reasons'])
        record=damage_record();record['trace'][-1]['p1']['team_health']=[144,0,144]
        self.assertIn('ko_or_life_transition',GAME.score(record,rules)['rejection_reasons'])

    def test_sonson_priorities_do_not_follow_a_tag(self):
        candidates=[{'last':'LP'},{'last':'df.HP'}]
        parent={'state':{'p1':{'character':20}},'action_names':['Tag 1']}
        self.assertEqual(GAME.order_continuations(candidates,parent,RULES),candidates)
        self.assertTrue(GAME.replay_compatible({'profile_sha256':GAME.assist_input_profile,'steps':[]}))

    def test_guard_check_rejects_missing_or_shifted_hits(self):
        reference={'candidate_valid':True,'damage_events':[{'frame':10,'damage':12},{'frame':59,'damage':12}]}
        self.assertFalse(escape_mismatch(reference,reference))
        self.assertTrue(escape_mismatch(reference,dict(reference,damage_events=reference['damage_events'][:1])))
        self.assertTrue(escape_mismatch(reference,dict(reference,damage_events=[{'frame':10,'damage':12},{'frame':60,'damage':12}])))

    def test_small_budget_reaches_continuations_with_large_library(self):
        remaining=30
        quotas=[]
        for depth in range(1,9):
            quota=depth_quota(remaining,9-depth,1000)
            quotas.append(quota)
            remaining-=quota
        self.assertEqual(sum(quotas),30)
        self.assertTrue(all(q>0 for q in quotas))
        self.assertEqual(quotas[0],4)

    def test_sonson_prioritizes_launcher_jump_and_repeated_air_lights(self):
        rules={**RULES,'groups':['normals','movement'],'max_delay':60}
        parent={'steps':(),'notation':'','score':{'damage':0},'state':damage_record()['trace'][0]}
        def ordered(p):
            return GAME.order_continuations(continuation_candidates(p,GAME.search_actions(rules),rules,False),p,rules)
        self.assertEqual(ordered(parent)[0]['last'],'df.HP')
        parent.update(steps=(Step(1,('D','F','HP')),),notation='df.HP',action_names=['df.HP'],launch_observed=True,contact_delays=[5])
        self.assertEqual((ordered(parent)[0]['last'],ordered(parent)[0]['delay']),('jump cancel',8))
        parent.update(airborne_observed=True,action_names=['df.HP','jump cancel','LP','LK'])
        self.assertEqual(ordered(parent)[0]['last'],'LP')

    def test_frontier_keeps_air_setup_over_more_immediate_damage(self):
        state=damage_record()['trace'][0]
        ground={'last':'623HP','score':{'damage':30},'state':state}
        air={'last':'jump cancel','score':{'damage':12},'state':state,'airborne_observed':True}
        self.assertIs(GAME.select_frontier([ground,air],1)[0],air)
        air_super={'last':'236PP','score':{'damage':53},'state':state,'airborne_observed':True}
        self.assertIs(GAME.select_frontier([air_super,air],1)[0],air)

    def test_finisher_gets_a_trial_after_developing_route(self):
        parent={'score':{'damage':18},'action_names':['df.HP','jump cancel','LP']}
        finished={'score':{'damage':41},'action_names':['236PP']}
        normal={'last':'LK'}
        finisher={'last':'236PP'}
        other={'last':'df.HP'}
        pools=[[normal,finisher],[other]]
        interleaved=[normal,other,finisher]
        self.assertEqual(reserve_finisher_trial(interleaved,pools,[parent,finished],{'236PP'},3),
                         [normal,finisher,other])
        self.assertEqual(reserve_finisher_trial(interleaved,pools,[parent,finished],set(),3),
                         interleaved)

    def test_measured_damage_does_not_claim_hitstun_or_combo(self):
        score = GAME.score(damage_record(), RULES)
        self.assertEqual(score['damage'], 3)
        self.assertTrue(score['candidate_valid'])
        self.assertEqual(score['validation'], 'damage_only_unvalidated_hitstun')
        self.assertIsNone(score['settled'])
        self.assertIsNone(score['starting_hitstun'])

    def test_rejects_tag_assist_ko_healing_and_round_transition(self):
        for field, value, reason in [('slot', 2, 'tag_or_assist'),
                                     ('active_count', 2, 'tag_or_assist'),
                                     ('character', 5, 'tag_or_assist'),
                                     ('team_health', [141, 0, 144], 'ko_or_life_transition'),
                                     ('health', 144, 'health_increased')]:
            with self.subTest(field=field):
                record = damage_record()
                record['trace'][-1]['p2'][field] = value
                self.assertIn(reason, GAME.score(record, RULES)['rejection_reasons'])
        record = damage_record()
        record['trace'][-1]['in_match'] = 0
        self.assertIn('not_in_match', GAME.score(record, RULES)['rejection_reasons'])

    def test_meter_cap_and_damage_at_end_are_rejected(self):
        record = damage_record()
        record['trace'][-1]['p1']['stocks'] = 0
        score = GAME.score(record, {**RULES, 'resources': 'cap', 'stock_cap': 0})
        self.assertIn('meter_spent', score['rejection_reasons'])
        record = damage_record()
        record['trace'][-1]['p2']['health'] = 140
        self.assertIn('unresolved_damage', GAME.score(record, RULES)['rejection_reasons'])

    def test_true_combo_and_assist_aliases_fail_closed(self):
        with self.assertRaisesRegex(ValueError, 'hitstun'):
            validate_rules({**RULES, 'true_combo': True}, GAME)
        with self.assertRaisesRegex(ValueError, 'MP/MK'):
            validate_rules({**RULES, 'custom_moves': [{'name': 'assist', 'sequence': 'MP', 'enabled': True}]}, GAME)
        actions = GAME.actions(['normals'])
        self.assertEqual({b for a in actions for s in a.steps for b in s.buttons} - {'D','F'}, {'LP','HP','LK','HK'})

    def test_assist_and_sonson_hyper_templates(self):
        actions={a.name:a for a in GAME.actions(['assists','supers'])}
        self.assertEqual(actions['Assist 1'].steps,(Step(1,('A1',)),))
        self.assertEqual(actions['Assist 2'].steps,(Step(1,('A2',)),))
        self.assertEqual(actions['236PP'].steps[-1],Step(1,('F','LP','HP')))
        self.assertEqual(actions['214PP'].steps[-1],Step(1,('B','LP','HP')))
        self.assertEqual(actions['236KK'].steps[-1],Step(1,('F','LK','HK')))
        validate_rules({**RULES,'groups':['assists','supers']},GAME)
        with self.assertRaisesRegex(ValueError,'Vampire Savior'):
            validate_rules({**DEFAULT_RULES,'custom_moves':[{'name':'bad','sequence':'A1','enabled':True}]},get_game('vampire-savior'))

    def test_disabling_assist_buttons_removes_built_in_and_custom_calls(self):
        rules=validate_rules({**RULES,'groups':['normals','assists','supers'],
                              'disabled_buttons':['A1','A2'],
                              'custom_moves':[{'name':'Assist then punch','sequence':'A1, HP','enabled':True}]},GAME)
        actions=GAME.search_actions(rules)
        self.assertNotIn('Assist 1',[a.name for a in actions])
        self.assertNotIn('Assist 2',[a.name for a in actions])
        self.assertNotIn('Assist then punch',[a.name for a in actions])
        self.assertIn('236PP',[a.name for a in actions])
        self.assertFalse(any({'A1','A2'} & set(step.buttons) for action in actions for step in action.steps))
        with self.assertRaisesRegex(ValueError,'disabled button'):
            validate_rules({**RULES,'disabled_buttons':['A3']},GAME)

    def test_previous_mvc2_input_profiles_remain_replayable(self):
        old={'profile_sha256':next(iter(GAME.previous_input_profiles)),
             'steps':[{'frames':1,'buttons':['D','F','HP']}]}
        self.assertTrue(GAME.replay_compatible(old))
        self.assertFalse(GAME.replay_compatible({**old,'steps':[{'frames':1,'buttons':['A1']}]}))
        self.assertFalse(GAME.replay_compatible({**old,'profile_sha256':'unrelated'}))

    def test_partner_presence_can_be_scored_without_allowing_a_tag(self):
        record=damage_record()
        record['trace'][3]['p1']['active_count']=2
        record['trace'][3]['in_match']=2
        self.assertTrue(GAME.score(record,RULES)['candidate_valid'])
        record['trace'][3]['p1']['slot']=2
        self.assertIn('tag_or_assist',GAME.score(record,RULES)['rejection_reasons'])

    def test_hypers_get_enough_settling_frames(self):
        self.assertEqual(GAME.trial_tail({'action_names':['236PP'],'steps':(Step(1,('LP',)),)},RULES),240)
        self.assertEqual(GAME.trial_tail({'action_names':['Assist 1'],'steps':(Step(1,('A1',)),)},RULES),180)
        self.assertEqual(GAME.trial_tail({'action_names':['LP'],'steps':(Step(1,('LP',)),)},RULES),RULES['tail'])

    def test_invalid_mapping_and_bad_trace_fail(self):
        record = damage_record()
        record['trace'][0]['p1']['x'] = float('nan')
        with self.assertRaises(ValueError): GAME.score(record, RULES)
        record = damage_record()
        record['trace'][3]['frame'] = 99
        with self.assertRaises(ValueError): GAME.score(record, RULES)


class FlycastSessionTests(unittest.TestCase):
    def test_button_selection_persists_without_changing_other_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory))
            saved=app.save({'game':GAME.id,'emulator':'flycast.exe','snapshot':'mvsc2.state',
                            'rules':{**RULES,'budget':5000,'disabled_buttons':['A1','A2']}})
            profile=Dashboard(Path(directory)).profile(GAME.id)
            self.assertEqual(saved['rules']['disabled_buttons'],['A1','A2'])
            self.assertEqual(profile['rules']['disabled_buttons'],['A1','A2'])
            self.assertEqual(profile['rules']['budget'],5000)

    def test_existing_all_groups_profile_exposes_assists_and_supers(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory))
            app.config[GAME.id]={'rules':{**RULES,'groups':['normals','motions','movement']}}
            self.assertEqual(app.profile(GAME.id)['rules']['groups'],
                             ['normals','motions','movement','assists','supers'])

    def test_history_distinguishes_legacy_damage_and_escape_checked_results(self):
        with tempfile.TemporaryDirectory() as directory:
            app=Dashboard(Path(directory))
            (app.data/'runs').mkdir(parents=True)
            for name,best in [('legacy',{'verified':False,'reproduced':True}),
                              ('checked',{'verified':False,'reproduced':True,'escape_checked':True}),
                              ('failed',{'verified':False,'reproduced':False})]:
                (app.data/'runs'/(name+'.json')).write_text(json.dumps({'game':GAME.id,'best':best}),encoding='utf-8')
            rows={r['id']:r for r in app.history()}
            self.assertTrue(all(r['damage_only'] and not r['verified'] for r in rows.values()))
            self.assertFalse(rows['legacy']['escape_checked'])
            self.assertTrue(rows['checked']['escape_checked'])
            self.assertTrue(rows['failed']['failed_validation'])

    def test_isolated_runtime_preserves_installation_and_state_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            install = root/'installation'
            (install/'ROMs').mkdir(parents=True)
            (install/'data').mkdir()
            for name in ('flycast.exe','libcrypto.dll','ROMs/mvsc2.zip','data/naomi.zip',
                         'data/mvsc2.zip.eeprom','data/mvsc2.zip.nvmem'):
                (install/name).write_bytes(b'fixture')
            config = '[dojo]\nEnable = yes\nTraining = yes\n[config]\nDreamcast.AutoSaveState = yes\n'
            (install/'emu.cfg').write_text(config)
            states = [root/'one.state', root/'two.state']
            for i,p in enumerate(states): p.write_bytes(bytes([i]))
            before = {p: p.read_bytes() for p in install.rglob('*') if p.is_file()}
            app = Dashboard(root)
            app.prepare({'game': GAME.id, 'emulator': str(install/'flycast.exe'),
                         'snapshots': list(map(str, states)), 'rules': RULES, 'instance_count': 2})
            session = app.session(GAME.id)
            snapshots = json.loads((session/'session.json').read_text())['snapshots']
            self.assertEqual([s['file'] for s in snapshots], ['root.state','state_2.state'])
            for i,s in enumerate(snapshots):
                self.assertEqual((session/'bridge'/s['file']).read_bytes(), bytes([i]))
                self.assertEqual(states[i].read_bytes(), bytes([i]))
            self.assertEqual(before, {p:p.read_bytes() for p in before})
            args = GAME.launch_arguments(install/'flycast.exe', session/'connect.lua')
            self.assertEqual(Path(args[0]), session/'flycast/flycast.exe')
            self.assertEqual(Path(args[1]), install/'ROMs/mvsc2.zip')
            second = app.sessions(GAME.id)[1]
            self.assertEqual(Path(GAME.launch_arguments(install/'flycast.exe', second/'connect.lua')[0]),
                             second/'flycast/flycast.exe')
            self.assertIn(second.as_posix(), (second/'flycast/flycast.lua').read_text())
            self.assertEqual((second/'bridge/state_2.state').read_bytes(), states[1].read_bytes())
            copied = (session/'flycast/emu.cfg').read_text()
            self.assertIn('Dreamcast.AutoSaveState = no', copied)
            self.assertIn('Training = no', copied)
            self.assertIn('COMBOCHAN_PROFILE_SHA256', (session/'connect.lua').read_text())
            self.assertFalse(Dashboard(root).profile(GAME.id)['rules']['true_combo'])

    def test_bridge_accepts_state_names_but_not_paths(self):
        for name in ('root.state','state_2.state','root.fs'):
            Bridge(Path('.'), snapshot=name)
        for name in ('../root.state','a/b.state','a\\b.state','root.state.net','root.state.exe','root'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                Bridge(Path('.'), snapshot=name)

    def test_worker_uses_state_snapshot_and_never_verifies_damage_string(self):
        calls = []

        class FixtureBridge:
            def __init__(self, directory, **kwargs):
                self_test.assertEqual(kwargs['snapshot'], 'root.state')
                self_test.assertEqual(kwargs['rom'], 'mvsc2')

            def run(self, trials, speed='turbo'):
                calls.extend(trials)
                records = []
                for t in trials:
                    for repetition in range(1, t.repeats+1):
                        record = damage_record()
                        record.update(id=t.id, repetition=repetition, defense=t.defense)
                        frame_count = 1+t.tail+sum(s.frames for s in t.steps)
                        while len(record['trace']) < frame_count:
                            record['trace'].append({**record['trace'][-1], 'frame': len(record['trace'])})
                        records.append(record)
                return records, {'job': 'synthetic-test'}

        self_test = self
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder)
            (session/'bridge').mkdir()
            (session/'bridge/root.state').write_bytes(b'fixture')
            source = Path(__file__).resolve().parents[1]/GAME.runner_path
            (session/'bridge/ready.json').write_text(json.dumps({
                'script_content': source.read_bytes().decode('utf-8'),
                'profile_sha256': GAME.profile_sha256}), encoding='utf-8')
            events = []
            with patch('combochan.dashboard_worker.Bridge', FixtureBridge):
                execute({'game': GAME.id, 'session': str(session), 'action': 'search',
                         'model': 'unused', 'rules': {**RULES, 'groups': ['normals'], 'budget': 24, 'depth': 1}},
                        lambda **event: events.append(event))
            result = events[-1]['result']
            self.assertTrue(result['best']['reproduced'])
            self.assertFalse(result['best']['verified'])
            self.assertIsNone(result['starting_hitstun'])
            self.assertTrue(result['best']['escape_checked'])
            self.assertEqual({t.defense for t in calls}, {'neutral','stand','crouch','jump'})
            self.assertEqual(calls[0].repeats, 100)


if __name__ == '__main__':
    unittest.main()
