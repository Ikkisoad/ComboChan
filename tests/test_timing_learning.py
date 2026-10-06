import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from combochan.bridge import Step
from combochan.dashboard import DEFAULT_RULES
from combochan.dashboard_worker import continuation_candidates
from combochan.games import Action
from combochan.timing import observe, preferred_delays, stun_end
from combochan.dashboard_worker import execute
from test_dashboard import SimulatedBridge


class TimingLearningTests(unittest.TestCase):
    def test_warmup_uses_budget_and_validation_replays_root(self):
        calls=[]
        class RecordingBridge(SimulatedBridge):
            def run(self,trials,speed='turbo'):
                calls.extend(trials)
                return super().run(trials,speed)
        with tempfile.TemporaryDirectory() as folder:
            session=Path(folder);(session/'bridge').mkdir()
            (session/'bridge/root.fs').write_bytes(b'fixture')
            runner=Path(__file__).resolve().parents[1]/'bridge/runner.lua'
            (session/'bridge/ready.json').write_text(json.dumps({'script_content':runner.read_bytes().decode()}))
            rules={**DEFAULT_RULES,'budget':24,'depth':2,'groups':['normals']}
            events=[]
            with patch('combochan.dashboard_worker.Bridge',RecordingBridge):
                execute({'game':'vampire-savior','session':str(session),'action':'search','model':'unused','rules':rules},lambda **event:events.append(event))
            result=events[-1]['result']
            probes=[t for t in calls if t.id.startswith('timing_')]
            searches=[t for t in calls if t.id.startswith('d')]
            self.assertEqual(len(probes),2)
            self.assertEqual(result['evaluated'],len(probes)+len(searches))
            self.assertLessEqual(result['evaluated'],rules['budget'])
            self.assertEqual(len(result['timing_observations']),2)
            self.assertTrue(any(t.checkpoint_steps for t in searches))
            self.assertTrue(all(t.checkpoint_steps==0 for t in calls if t.id.startswith('best_')))

    def test_observes_contact_and_hitstun_without_inventing_recovery(self):
        action=Action('LP',(Step(1,('LP',)),),'normals')
        trace=[{'frame':f,'p2':{'stun1':int(3<=f<12),'stun2':0}} for f in range(20)]
        score={'damage':5,'damage_events':[{'frame':3,'damage':5}]}
        learned=observe(action,trace,score)
        self.assertEqual(learned['contact_latency'],3)
        self.assertEqual(learned['hitstun_frames'],9)
        self.assertEqual(stun_end(trace,score),12)
        self.assertIsNone(learned['startup_frames'])
        self.assertIsNone(learned['frame_advantage'])
        for row in trace: row['p2']['combo_hits']=1
        self.assertIsNone(observe(action,trace,score)['hitstun_frames'])
        self.assertIsNone(stun_end(trace,score))
        for row in trace: row['p2']['stun1']=None
        self.assertIsNone(observe(action,trace,score)['hitstun_frames'])

    def test_cancel_and_link_windows_precede_broad_sweep(self):
        action=Action('HP',(Step(1,('HP',)),),'normals')
        parent={'steps':(Step(1,('LP',)),),'notation':'LP','contact_frames':[4],
                'stun_ends_at':12,'last':'LP'}
        observation={'contact_latency':3}
        # A 3-frame observed contact latency must hit strictly before recovery.
        preferred=preferred_delays(parent,action,observation,60)
        self.assertEqual(preferred[:3],[4,5,3])
        self.assertIn(7,preferred)
        rules={**DEFAULT_RULES,'_timing_observations':{'HP':observation}}
        candidates=continuation_candidates(parent,[action],rules,False)
        self.assertEqual(candidates[0]['delay'],4)
        self.assertEqual({c['delay'] for c in candidates},set(range(61)))
        manual=continuation_candidates(parent,[action],{**rules,'auto_timing':False,'delays':[11]},False)
        self.assertEqual([c['delay'] for c in manual],[11])

    def test_whiff_does_not_produce_startup_estimate(self):
        learned=observe(Action('HP',(Step(1,('HP',)),),'normals'),[],{'damage':0,'damage_events':[]})
        self.assertIsNone(learned['contact_latency'])
        self.assertIsNone(learned['hitstun_frames'])


if __name__=='__main__': unittest.main()
