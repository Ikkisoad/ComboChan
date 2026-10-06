import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from combochan.bridge import Step
from combochan.dashboard import Dashboard, DEFAULT_RULES, Server, validate_rules
from combochan.dashboard_worker import execute, Cancelled
from combochan.games import get_game
from test_core import recording


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        (self.root/'bridge').mkdir()
        (self.root/'bridge/runner.lua').write_text('-- fixture',encoding='utf-8')
        self.exe=self.root/'fcadefbneo.exe'; self.exe.write_bytes(b'fixture')
        self.snapshot=self.root/'scenario.fs'; self.snapshot.write_bytes(b'state-copy-test')
        self.app=Dashboard(self.root)
        self.data={'game':'vampire-savior','emulator':str(self.exe),'snapshot':str(self.snapshot),'rules':dict(DEFAULT_RULES)}

    def test_state_resources_allow_spend(self):
        game=get_game('vampire-savior')
        record=recording((4,),stock_drop=3)
        self.assertTrue(game.score(record,DEFAULT_RULES)['candidate_valid'])
        self.assertFalse(game.score(record,{**DEFAULT_RULES,'resources':'cap','stock_cap':0})['candidate_valid'])

    def test_rule_validation(self):
        for change in ({'budget':0},{'depth':65},{'max_frames':961},{'delays':[-1]},{'groups':[]},{'groups':['unimplemented']},{'groups':[{}]},{'true_combo':'yes'}):
            with self.assertRaises(ValueError): validate_rules({**DEFAULT_RULES,**change},get_game('vampire-savior'))

    def test_dashboard_accepts_64_actions_and_64_move_starter(self):
        game=get_game('vampire-savior')
        starter='2LK'*64
        rules=validate_rules({'depth':64,'starters':[starter]},game)
        self.assertEqual(len(rules['starters']),1)
        long_name='x'*80
        named_starter=' > '.join([long_name]*64)
        named_rules=validate_rules({'depth':64,'starters':[named_starter],
            'custom_moves':[{'name':long_name,'sequence':'LP, N, HP','enabled':True}]},game)
        self.assertEqual(len(named_rules['starters'][0]),5309)
        with self.assertRaisesRegex(ValueError,'at most 64 moves'):
            validate_rules({'depth':64,'starters':['2LK'*65]},game)

    def test_prepare_preserves_original_and_isolates_sessions(self):
        before=self.snapshot.read_bytes()
        first=self.app.prepare(self.data)
        session1=self.app.session('vampire-savior')
        second=self.app.prepare(self.data)
        session2=self.app.session('vampire-savior')
        self.assertNotEqual(session1,session2)
        self.assertEqual(before,self.snapshot.read_bytes())
        self.assertEqual(before,(session1/'bridge/root.fs').read_bytes())
        self.assertEqual(first['snapshot_sha256'],second['snapshot_sha256'])
        self.assertIn('COMBOCHAN_BRIDGE_DIR',(session1/'connect.lua').read_text())
        self.assertIn('return assert(loadfile(', (session1/'connect.lua').read_text())
        self.assertNotIn('dofile(', (session1/'connect.lua').read_text())

    def test_stale_ready_does_not_mean_connected(self):
        self.app.prepare(self.data); session=self.app.session('vampire-savior')
        (session/'bridge/ready.json').write_text(json.dumps({'rom':'vsavj'}))
        (session/'bridge/heartbeat.json').write_text(json.dumps({'time':time.time()-30}))
        self.assertFalse(self.app.connection('vampire-savior')['connected'])
        (session/'bridge/heartbeat.json').write_text(json.dumps({'time':time.time()}))
        self.assertTrue(self.app.connection('vampire-savior')['connected'])

    def test_change_snapshot_requires_preparation(self):
        self.app.prepare(self.data)
        other=self.root/'other.fs'; other.write_bytes(b'other')
        self.app.save({**self.data,'snapshot':str(other)})
        self.assertFalse(self.app.connection('vampire-savior')['prepared'])

    def test_cannot_modify_running_session(self):
        self.app.job={'stage':'searching'}
        with self.assertRaises(ValueError): self.app.prepare(self.data)

    def test_disconnected_run_rejected(self):
        self.app.prepare(self.data)
        with self.assertRaises(ValueError): self.app.start({'game':'vampire-savior','action':'search'})

    def test_windows_emulator_launch_requests_visible_window(self):
        self.app.prepare(self.data)
        with patch('combochan.dashboard.os.name', 'nt'), \
             patch('combochan.windows_launch.launch_visible') as launch:
            self.app.launch('vampire-savior')
        self.assertEqual(launch.call_args.args[0][0], str(self.exe))
        self.assertEqual(launch.call_args.args[1], self.exe.parent)
        self.assertIs(self.app.owned_emulators[0], launch.return_value)

    def test_close_emulators_only_requests_owned_processes_for_selected_game(self):
        class Process:
            def __init__(self): self.close_calls=0
            def poll(self): return None
            def terminate(self): self.close_calls+=1
            def close_gracefully(self): self.close_calls+=1
        self.app.prepare(self.data)
        old_session=self.app.session('vampire-savior')
        self.app.prepare(self.data)
        current_session=self.app.session('vampire-savior')
        other={**self.data,'game':'x-men-vs-street-fighter'}
        self.app.prepare(other)
        selected_old,selected_current,unrelated=Process(),Process(),Process()
        self.app.owned_emulators=[selected_old,selected_current,unrelated]
        self.app.emulator_sessions={str(old_session):selected_old,str(current_session):selected_current,
                                    str(self.app.session('x-men-vs-street-fighter')):unrelated}
        result=self.app.close_emulators('vampire-savior')
        self.assertEqual([selected_old.close_calls,selected_current.close_calls,unrelated.close_calls],[1,1,0])
        self.assertEqual((result['requested'],result['pending']), (2,2))
        self.assertEqual(len(self.app.owned_emulators),3)
        self.assertEqual(self.app.emulator_status('vampire-savior'),{'owned':2,'close_requested':2})

    def test_failed_emulator_close_retains_owned_handle(self):
        class FailingProcess:
            def poll(self): return None
            def terminate(self): raise OSError('close failed')
            def close_gracefully(self): raise OSError('close failed')
        self.app.prepare(self.data)
        session=self.app.session('vampire-savior')
        process=FailingProcess()
        self.app.owned_emulators=[process]
        self.app.emulator_sessions[str(session)]=process
        result=self.app.close_emulators('vampire-savior')
        self.assertEqual(result['failed'],1)
        self.assertEqual(result['pending'],1)
        self.assertIs(self.app.owned_emulators[0],process)
        self.assertIs(self.app.emulator_sessions[str(session)],process)

    def test_windows_close_with_no_window_stays_retryable(self):
        class WindowlessProcess:
            def __init__(self): self.close_calls=0
            def poll(self): return None
            def close_gracefully(self): self.close_calls+=1; return 0
        self.app.prepare(self.data)
        session=self.app.session('vampire-savior')
        process=WindowlessProcess()
        self.app.owned_emulators=[process]
        self.app.emulator_sessions[str(session)]=process
        first=self.app.close_emulators('vampire-savior')
        second=self.app.close_emulators('vampire-savior')
        self.assertEqual((first['failed'],first['pending']),(1,1))
        self.assertEqual((second['failed'],second['pending']),(1,1))
        self.assertEqual(process.close_calls,2)
        self.assertNotIn(id(process),self.app.emulator_close_requested)

    def test_close_emulators_rejected_while_job_active(self):
        self.app.job={'stage':'searching'}
        with self.assertRaisesRegex(ValueError,'A job is active'):
            self.app.close_emulators('vampire-savior')

    def test_stop_is_cooperative(self):
        self.app.prepare(self.data); session=self.app.session('vampire-savior')
        self.app.job={'stage':'searching','session':str(session)}
        self.app.stop()
        self.assertTrue((session/'cancel.flag').exists())
        self.assertEqual(self.app.job['stage'],'stopping')

    def test_save_persists_rules(self):
        self.app.save({**self.data,'rules':{**DEFAULT_RULES,'budget':42}})
        self.assertEqual(Dashboard(self.root).profile('vampire-savior')['rules']['budget'],42)

    def test_save_special_library_alongside_starter(self):
        rules={**DEFAULT_RULES,'true_combo':False,'starters':['2LK'],
               'custom_moves':[{'name':'41236LK','sequence':'41236LK','enabled':True}]}
        self.app.save({**self.data,'game':'marvel-vs-capcom-2','rules':rules})
        saved=Dashboard(self.root).profile('marvel-vs-capcom-2')['rules']
        self.assertEqual(saved['starters'],['2LK'])
        self.assertEqual(saved['custom_moves'],rules['custom_moves'])
        self.assertIn('41236LK',[action.name for action in get_game('marvel-vs-capcom-2').search_actions(saved)])

    def test_export_cannot_read_arbitrary_files(self):
        self.assertNotIn('../../scenario.fs',self.app.result_files())

    def test_action_library_has_relative_motions(self):
        actions=get_game('vampire-savior').actions(['normals','motions','movement'])
        self.assertGreater(len(actions),12)
        for action in actions:
            for step in action.steps: self.assertIsInstance(step,Step)
        self.assertTrue(any('F' in step.buttons for action in actions for step in action.steps))

    def test_http_requires_token_and_same_origin(self):
        server=Server(('127.0.0.1',0),self.app)
        thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
        try:
            client=http.client.HTTPConnection('127.0.0.1',server.server_port)
            client.request('GET','/api/state'); response=client.getresponse(); self.assertEqual(response.status,200); response.read()
            body=json.dumps(self.data)
            client.request('POST','/api/save',body,{'Content-Type':'application/json'})
            response=client.getresponse(); self.assertEqual(response.status,403); response.read()
            headers={'X-ComboChan-Token':self.app.token,'Content-Type':'application/json','Origin':'https://example.org'}
            client.request('POST','/api/save',body,headers)
            response=client.getresponse(); self.assertEqual(response.status,403); response.read()
            headers.pop('Origin'); client.request('POST','/api/save',body,headers)
            response=client.getresponse(); self.assertEqual(response.status,200); response.read(); client.close()
        finally: server.shutdown(); server.server_close()


class SimulatedBridge:
    """Deterministic test double only; never used by the application."""
    def __init__(self,*args,**kwargs): pass
    def run(self,trials,speed='turbo'):
        records=[]
        for trial in trials:
            for repetition in range(1,trial.repeats+1):
                trace=[]
                total=sum(s.frames for s in trial.steps)+trial.tail
                attack=any(any(b in s.buttons for b in ('LP','LK','MP','MK','HP','HK')) for s in trial.steps)
                for frame in range(total+1):
                    p={'health':288-(5 if attack and frame>=2 else 0),'recoverable':288,'stocks':2,'meter':0,'x':20,'y':40,'state':512,'facing':0,'stun1':int(attack and 2<=frame<6),'stun2':0}
                    trace.append({'frame':frame,'p1':{**p,'x':0,'health':288},'p2':p})
                records.append({'id':trial.id,'repetition':repetition,'defense':trial.defense,'trace':trace})
        return records,{'job':'unit-test-only'}


class WorkerTests(unittest.TestCase):
    def test_unfinished_super_gets_extended_settling_and_replay_tail(self):
        class LongAnimationBridge(SimulatedBridge):
            def run(self,trials,speed='turbo'):
                records,manifest=super().run(trials,speed)
                for trial,record in zip(trials,records):
                    if trial.id.startswith('d') and trial.tail<300:
                        for row in record['trace'][-10:]:row['p2']['stun1']=1
                return records,manifest
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory);(session/'bridge').mkdir();(session/'bridge/root.fs').write_bytes(b'test')
            script=Path(__file__).resolve().parents[1]/'bridge/runner.lua'
            (session/'bridge/ready.json').write_text(json.dumps({'script_content':script.read_bytes().decode('utf-8')}),encoding='utf-8')
            events=[]
            with patch('combochan.dashboard_worker.Bridge',LongAnimationBridge):
                execute({'game':'vampire-savior','session':str(session),'action':'search','model':'unused','rules':{**DEFAULT_RULES,'budget':24,'depth':1,'groups':['normals']}},lambda **e:events.append(e))
            self.assertTrue(events[-1]['result']['best']['verified'])
            self.assertEqual(events[-1]['result']['best']['tail'],600)

    def test_worker_search_and_validation_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            session=Path(directory); (session/'bridge').mkdir()
            (session/'bridge/root.fs').write_bytes(b'test')
            script=Path(__file__).resolve().parents[1]/'bridge/runner.lua'
            (session/'bridge/ready.json').write_text(json.dumps({'script_content':script.read_bytes().decode('utf-8')}),encoding='utf-8')
            config={'game':'vampire-savior','session':str(session),'action':'search','model':'unused',
                    'rules':{**DEFAULT_RULES,'budget':24,'depth':1,'groups':['normals']}}
            events=[]
            with patch('combochan.dashboard_worker.Bridge',SimulatedBridge):
                execute(config,lambda **event:events.append(event))
            self.assertEqual(events[-1]['stage'],'complete')
            self.assertTrue(events[-1]['result']['best']['verified'])
            self.assertEqual(events[-1]['result']['best']['damage'],5)
            self.assertEqual(events[-1]['result']['evaluated'],12)
            (session/'cancel.flag').write_text('stop')
            with patch('combochan.dashboard_worker.Bridge',SimulatedBridge):
                with self.assertRaises(Cancelled): execute(config,lambda **event:None)


if __name__=='__main__': unittest.main()
