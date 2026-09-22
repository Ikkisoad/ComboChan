import copy
import unittest

from combochan.bridge import Step, Trial
from combochan.evaluate import evaluate, repeatability


def recording(events=(), recovery_frames=(), healing_frame=None, stock_drop=None):
    trace=[]
    health=288
    for frame in range(40):
        if frame in events: health-=10
        if frame==healing_frame: health+=10
        p={"health":health,"recoverable":health,"stocks":0,"meter":0,"x":0,"y":40,
           "facing":0,"stun1":int(bool(events) and min(events)<=frame<25 and frame not in recovery_frames),
           "stun2":0,"state":512}
        p1={**p,"health":288,"stocks":int(stock_drop is not None and frame<stock_drop)}
        trace.append({"frame":frame,"p1":p1,"p2":p})
    return {"id":"test","repetition":1,"defense":"neutral","trace":trace}


class EvaluatorTests(unittest.TestCase):
    def test_connected_damage(self):
        result=evaluate(recording((4,12)))
        self.assertTrue(result['candidate_valid'])
        self.assertEqual(result['damage'],20)

    def test_recovery_gap_rejected(self):
        result=evaluate(recording((4,20),range(12,19)))
        self.assertIn('recovery_gap',result['rejection_reasons'])

    def test_refill_not_mistaken_for_damage(self):
        result=evaluate(recording((4,),healing_frame=30))
        self.assertEqual(result['damage'],10)
        self.assertEqual(result['health_loss'],0)
        self.assertFalse(result['candidate_valid'])

    def test_meter_spend_rejected(self):
        self.assertIn('meter_spent',evaluate(recording((4,),stock_drop=3))['rejection_reasons'])

    def test_whiff_rejected(self):
        self.assertFalse(evaluate(recording())['candidate_valid'])

    def test_trace_difference_detected(self):
        a=recording((4,)); b=copy.deepcopy(a)
        b['trace'][20]['p1']['x']=1
        self.assertFalse(repeatability([a,b])['test']['identical'])

    def test_missing_frame_rejected(self):
        a=recording((4,)); del a['trace'][4]
        with self.assertRaises(ValueError): evaluate(a)


class InputTests(unittest.TestCase):
    def test_invalid_button(self):
        with self.assertRaises(ValueError): Step(1,('Reset',))

    def test_conflicting_directions(self):
        with self.assertRaises(ValueError): Step(1,('L','R'))

    def test_frame_limits(self):
        for frames in (0,-1,241,1.5):
            with self.assertRaises(ValueError): Step(frames)

    def test_request_injection_rejected(self):
        with self.assertRaises(ValueError): Trial('bad\nID',(Step(1),)).validate()


if __name__=='__main__': unittest.main()
