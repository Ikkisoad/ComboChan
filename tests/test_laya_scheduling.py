import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from combochan.policy import Policy
from combochan.dashboard import DEFAULT_RULES
from combochan.dashboard_worker import execute, Cancelled
from test_dashboard import SimulatedBridge

class FakeAgent:
    def __init__(self,events):self.events=events
    def predict(self,context,question):
        options=question['next']['criteria']
        self.events.append(('model',len(options)))
        return {'answers':{'next':{'probabilities':{key:float(key) for key in options}}}}

class LayaSchedulingTests(unittest.TestCase):
    def policy(self,events):
        policy=Policy('heuristic');policy.mode='laya';policy.agent=FakeAgent(events)
        return policy

    def test_single_bounded_call_preserves_unique_batch(self):
        events=[];policy=self.policy(events)
        candidates=[{'label':str(i),'notation':str(i)} for i in range(100)]
        progress=[]
        batch=policy.guided_batch(candidates,{},progress=lambda *v:progress.append(v))
        self.assertEqual(events,[('model',12)])
        self.assertEqual(len(batch),16)
        self.assertEqual(len({id(c) for c in batch}),16)
        self.assertEqual(len(candidates),100)
        self.assertEqual(len(policy.calls),1)
        self.assertEqual(progress[0][0],12)

    def test_cancel_before_inference_does_not_invoke_model(self):
        events=[];policy=self.policy(events)
        def cancel():raise Cancelled()
        with self.assertRaises(Cancelled):policy.guided_batch([{'label':'a'},{'label':'b'}],{},check_cancel=cancel)
        self.assertEqual(events,[])

    def test_worker_runs_trials_between_model_calls(self):
        timeline=[];policy=self.policy(timeline)
        class Bridge(SimulatedBridge):
            def run(self,trials,speed='turbo'):
                if trials[0].id.startswith('d'):timeline.append(('trials',len(trials)))
                return super().run(trials,speed)
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory);(session/'bridge').mkdir();(session/'bridge/root.fs').write_bytes(b'test')
            script=Path(__file__).resolve().parents[1]/'bridge/runner.lua'
            (session/'bridge/ready.json').write_text(json.dumps({'script_content':script.read_bytes().decode('utf-8')}),encoding='utf-8')
            rules={**DEFAULT_RULES,'policy':'laya','budget':72,'depth':1,'max_start_delay':5,'groups':['normals']}
            events=[]
            with patch('combochan.dashboard_worker.Policy',return_value=policy),patch('combochan.dashboard_worker.Bridge',Bridge):
                execute({'game':'vampire-savior','session':str(session),'rules':rules,'action':'search','model':'unused'},lambda **e:events.append(e))
            self.assertEqual(timeline,[('model',12),('trials',16),('trials',16),('trials',16),('trials',16),('model',8),('trials',8)])
            self.assertEqual(events[-1]['result']['evaluated'],72)
            self.assertTrue(any('model_wait_seconds' in event for event in events))

if __name__=='__main__':unittest.main()
