import copy
import json
from pathlib import Path
import unittest

from combochan.dashboard import validate_rules
from combochan.dashboard_worker import escape_mismatch
from combochan.evaluate import trace_digest
from combochan.game_profile import template, validate_profile
from combochan.games import get_game


class MarvelVsCapcomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = json.loads((Path(__file__).parent/'fixtures/mvsc_calibration.json').read_text())
        cls.records = {}
        for packed in fixture['records']:
            current = copy.deepcopy(packed['initial'])
            trace = [copy.deepcopy(current)]
            changes = {row['frame']:row for row in packed['changes']}
            for frame in range(1,packed['frames']+1):
                current['frame'] = frame
                for player in ('p1','p2'):
                    current[player].update(changes.get(frame,{}).get(player,{}))
                trace.append(copy.deepcopy(current))
            if trace_digest(trace) != packed['trace_sha256']:
                raise AssertionError('Live MVC fixture changed during reconstruction')
            cls.records[packed['id']] = {**packed,'trace':trace}

    def setUp(self):
        self.game = get_game('marvel-vs-capcom')
        self.rules = validate_rules({},self.game)

    def test_live_connected_chain_survives_all_defenses(self):
        reference = self.game.score(self.records['validated_neutral'],self.rules)
        self.assertTrue(reference['candidate_valid'])
        self.assertEqual(reference['damage'],16)
        self.assertEqual(reference['hit_count'],3)
        for defense in ('stand','crouch','jump'):
            self.assertFalse(escape_mismatch(reference,self.game.score(self.records['validated_'+defense],self.rules)))

    def test_live_gaps_and_counter_resets_rejected(self):
        for name in ('negative','counter_reset'):
            reference = self.game.score(self.records[name+'_neutral'],self.rules)
            self.assertFalse(reference['candidate_valid'])
            self.assertIn('combo_counter_break',reference['rejection_reasons'])
            for defense in ('stand','crouch','jump'):
                defended = self.game.score(self.records[name+'_'+defense],self.rules)
                self.assertEqual(defended['hit_count'],1)
                self.assertTrue(escape_mismatch(reference,defended))
        self.assertIn('recovery_gap',self.game.score(self.records['negative_neutral'],self.rules)['rejection_reasons'])
        self.assertEqual(self.game.score(self.records['counter_reset_neutral'],self.rules)['gaps'],[])

    def test_live_damage_variation_stays_conservatively_rejected(self):
        reference = self.game.score(self.records['positive_neutral'],self.rules)
        defended = self.game.score(self.records['positive_stand'],self.rules)
        self.assertTrue(reference['candidate_valid'])
        self.assertTrue(defended['candidate_valid'])
        self.assertEqual(reference['damage'],16)
        self.assertEqual(defended['damage'],17)
        self.assertTrue(escape_mismatch(reference,defended))

    def test_live_meter_spending_and_character_guard(self):
        cap = validate_rules({'resources':'cap','stock_cap':0},self.game)
        score = self.game.score(self.records['hyper_neutral'],cap)
        self.assertEqual(score['stocks_spent'],1)
        self.assertIn('meter_spent',score['rejection_reasons'])
        changed = copy.deepcopy(self.records['validated_neutral'])
        changed['trace'][-1]['p1']['character_id'] = 30
        self.assertIn('tag_or_character_transition',self.game.score(changed,self.rules)['rejection_reasons'])

    def test_identity_mapping_and_unsupported_inputs(self):
        players = self.game.telemetry['players']
        self.assertEqual(self.game.rom,'mvsc')
        self.assertEqual(players['p2']['health']['address'],0xFF3671)
        self.assertEqual(players['p2']['combo_hits']['address'],0xFF3120)
        self.assertEqual(players['p1']['character_id']['type'],'u16')
        for sequence in ('HP+HK','MP+MK','LP+LK','A1'):
            with self.assertRaises(ValueError):
                validate_rules({'custom_moves':[{'name':'Unsupported','sequence':sequence,'enabled':True}]},self.game)
        definition = template();definition['id'] = self.game.id
        with self.assertRaisesRegex(ValueError,'reserved'):
            validate_profile(definition)


if __name__ == '__main__':
    unittest.main()
