import copy
import json
from pathlib import Path
import unittest
from combochan.evaluate import evaluate
from test_core import recording

class ComboCounterTests(unittest.TestCase):
    def test_real_wakeup_route_is_rejected_at_counter_restart(self):
        record=json.loads((Path(__file__).parent/'fixtures/vsav_wakeup_counter.json').read_text())
        score=evaluate(record,max_stocks=None)
        self.assertEqual(score['damage'],55)
        self.assertEqual(score['combo_counter_breaks'],[96])
        self.assertIn('combo_counter_break',score['rejection_reasons'])
        self.assertFalse(score['candidate_valid'])
        self.assertTrue(evaluate(record,max_stocks=None,require_combo=False)['candidate_valid'])

    def test_real_uninterrupted_suffix_keeps_counter_progression(self):
        record=json.loads((Path(__file__).parent/'fixtures/vsav_wakeup_counter.json').read_text())
        record['trace']=record['trace'][96:]
        for i,row in enumerate(record['trace']):row['frame']=i
        score=evaluate(record,max_stocks=None)
        self.assertEqual(score['damage'],32)
        self.assertTrue(score['candidate_valid'])

    def test_counter_reset_between_hits_even_without_stun_gap(self):
        record=recording((4,12))
        for row in record['trace']:
            f=row['frame'];row['p2']['combo_hits']=0 if f<4 or 8<=f<12 or f>=25 else 1
        self.assertIn(12,evaluate(record)['combo_counter_breaks'])

    def test_same_count_new_hit_rejected(self):
        record=recording((4,12))
        for row in record['trace']:row['p2']['combo_hits']=int(4<=row['frame']<25)
        self.assertIn(12,evaluate(record)['combo_counter_breaks'])

    def test_counter_clearing_after_last_hit_is_normal(self):
        record=recording((4,12))
        for row in record['trace']:
            f=row['frame'];row['p2']['combo_hits']=(1 if f<12 else 2) if 4<=f<25 else 0
        self.assertTrue(evaluate(record)['candidate_valid'])

if __name__=='__main__':unittest.main()
