import copy
import json
from pathlib import Path
import tempfile
import time
import unittest

from combochan.dashboard import Dashboard, validate_rules
from combochan.dashboard_worker import escape_mismatch
from combochan.evaluate import trace_digest
from combochan.game_profile import template, validate_profile
from combochan.games import XMenVsStreetFighter, get_game


def live_records():
    fixture = json.loads((Path(__file__).parent/'fixtures/xmvsf_calibration.json').read_text())
    records = {}
    for packed in fixture['records']:
        changes = {row['frame']: row for row in packed['changes']}
        current = copy.deepcopy(packed['initial'])
        trace = [copy.deepcopy(current)]
        for frame in range(1,packed['frames']+1):
            current['frame'] = frame
            for player in ('p1','p2'):
                current[player].update(changes.get(frame,{}).get(player,{}))
            trace.append(copy.deepcopy(current))
        if trace_digest(trace) != packed['trace_sha256']:
            raise AssertionError('Live fixture did not reconstruct its original trace')
        records[packed['id']] = {**packed,'trace':trace}
    return records


class XMenVsStreetFighterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = live_records()

    def setUp(self):
        self.game = get_game('x-men-vs-street-fighter')
        self.rules = validate_rules({},self.game)

    def test_builtin_maps_active_health_and_received_counter(self):
        self.assertIsInstance(self.game,XMenVsStreetFighter)
        self.assertEqual(self.game.rom,'xmvsf')
        players = self.game.telemetry['players']
        self.assertEqual(players['p2']['health'],{'address':0xFF4611,'type':'u8',
                         'selector_address':0xFF4620,'alternate_address':0xFF4E11})
        self.assertEqual(players['p1']['recoverable']['alternate_address'],0xFF4A1B)
        self.assertEqual(players['p1']['x']['address'],0xFF400C)
        self.assertEqual(players['p2']['combo_hits']['address'],0xFF4110)
        self.assertEqual(players['p1']['combo_hits']['address'],0xFF4510)
        self.assertEqual(self.game.telemetry['inputs']['HP']['p1'],'P1 Strong Punch')
        self.assertEqual(self.game.profile_sha256,XMenVsStreetFighter().profile_sha256)
        self.assertIn(self.game.profile_sha256,self.game.session_script())
        self.assertTrue(self.game.public()['combo_validated'])
        self.assertFalse(self.game.vsav_ordering)

    def test_actions_and_button_exclusions(self):
        actions = self.game.search_actions(self.rules)
        self.assertEqual(len(actions),42)
        self.assertIn('236PP',{a.name for a in actions})
        self.assertIn('super jump forward',{a.name for a in actions})
        disabled = validate_rules({'disabled_buttons':['HP']},self.game)
        self.assertTrue(all('HP' not in step.buttons for a in self.game.search_actions(disabled) for step in a.steps))
        with self.assertRaisesRegex(ValueError,'X-Men'):
            validate_rules({'custom_moves':[{'name':'Assist','sequence':'A1','enabled':True}]},self.game)

    def test_live_positive_survives_all_defenses(self):
        reference = self.game.score(self.records['chain_2_neutral'],self.rules)
        self.assertTrue(reference['candidate_valid'])
        self.assertEqual(reference['damage'],17)
        self.assertEqual(reference['hit_count'],2)
        self.assertEqual(reference['validation'],'engine_counter_and_telemetry')
        for defense in ('stand','crouch','jump'):
            score = self.game.score(self.records['chain_2_'+defense],self.rules)
            self.assertFalse(escape_mismatch(reference,score))

    def test_live_counter_reset_without_idle_frame_rejected(self):
        score = self.game.score(self.records['chain_16_neutral'],self.rules)
        self.assertFalse(score['candidate_valid'])
        self.assertEqual(score['gaps'],[])
        self.assertIn('combo_counter_break',score['rejection_reasons'])

    def test_live_delayed_string_and_guard_escape(self):
        score = self.game.score(self.records['chain_60_neutral'],self.rules)
        self.assertFalse(score['candidate_valid'])
        self.assertIn('recovery_gap',score['rejection_reasons'])
        damage_rules = validate_rules({'true_combo':False},self.game)
        reference = self.game.score(self.records['chain_60_neutral'],damage_rules)
        defended = self.game.score(self.records['chain_60_stand'],damage_rules)
        self.assertTrue(reference['candidate_valid'])
        self.assertEqual(reference['damage'],27)
        self.assertTrue(escape_mismatch(reference,defended))

    def test_live_whiff_and_normal_damage(self):
        for name in ('neutral','attack_LP'):
            self.assertIn('no_damage',self.game.score(self.records[name],self.rules)['rejection_reasons'])
        self.assertEqual(self.game.score(self.records['approach_HP'],self.rules)['damage'],15)

    def test_tag_transition_rejected_even_in_damage_mode(self):
        record = self.records['tag']
        self.assertEqual({row['p1']['active_character'] for row in record['trace']},{0,1})
        score = self.game.score(record,validate_rules({'true_combo':False},self.game))
        self.assertFalse(score['candidate_valid'])
        self.assertIn('tag_or_character_transition',score['rejection_reasons'])
        # A snapshot already using an anchor remains usable without switching.
        anchored = copy.deepcopy(self.records['approach_HP'])
        for row in anchored['trace']:
            row['p1']['active_character'] = row['p2']['active_character'] = 1
        self.assertTrue(self.game.score(anchored,self.rules)['candidate_valid'])

    def test_live_hyper_meter_spending_and_settling(self):
        cap = validate_rules({'resources':'cap','stock_cap':0},self.game)
        score = self.game.score(self.records['236PP'],cap)
        self.assertEqual(score['stocks_spent'],1)
        self.assertIn('meter_spent',score['rejection_reasons'])
        self.assertIn('unresolved_hitstun',score['rejection_reasons'])
        # Save-state resources do not reject a measured stock expenditure.
        self.assertNotIn('meter_spent',self.game.score(self.records['236PP'],self.rules)['rejection_reasons'])

    def test_invalid_telemetry_and_reserved_id(self):
        row = copy.deepcopy(self.records['neutral']['trace'][0])
        row['p2']['health'] = 145
        with self.assertRaisesRegex(ValueError,'0-144'):self.game.validate_initial(row)
        row['p2']['health'] = 144
        row['p1']['active_character'] = 2
        with self.assertRaisesRegex(ValueError,'point or anchor'):self.game.validate_initial(row)
        data = template();data['id'] = self.game.id
        with self.assertRaisesRegex(ValueError,'reserved'):validate_profile(data)

    def test_dashboard_prepares_isolated_hashed_session(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exe = root/'fcadefbneo.exe';exe.write_bytes(b'fake')
            state = root/'xmvsf.fs';state.write_bytes(b'original state')
            app = Dashboard(root)
            self.assertTrue(app.profile(self.game.id)['rules']['true_combo'])
            app.prepare({'game':self.game.id,'emulator':str(exe),'snapshot':str(state)})
            session = app.session(self.game.id)
            self.assertEqual((session/'bridge/root.fs').read_bytes(),state.read_bytes())
            self.assertIn('COMBOCHAN_GAME = ',(session/'connect.lua').read_text())
            ready = {'rom':self.game.rom,'profile_sha256':self.game.profile_sha256}
            (session/'bridge/ready.json').write_text(json.dumps(ready))
            (session/'bridge/heartbeat.json').write_text(json.dumps({'time':time.time()}))
            self.assertTrue(app.connection(self.game.id)['connected'])
            ready['rom'] = 'xmvsfu'
            (session/'bridge/ready.json').write_text(json.dumps(ready))
            self.assertFalse(app.connection(self.game.id)['connected'])
            self.assertEqual(state.read_bytes(),b'original state')


if __name__ == '__main__':
    unittest.main()
