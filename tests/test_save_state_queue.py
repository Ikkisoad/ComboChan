import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from combochan.bridge import Bridge, Step, Trial
from combochan.dashboard import Dashboard, DEFAULT_RULES, atomic_json
from combochan.dashboard_worker import Cancelled, execute_queue
from test_dashboard import SimulatedBridge


class QueueTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        (self.root/'bridge').mkdir()
        script=Path(__file__).resolve().parents[1]/'bridge/runner.lua'
        (self.root/'bridge/runner.lua').write_bytes(script.read_bytes())
        self.exe=self.root/'fcadefbneo.exe'; self.exe.write_bytes(b'exe')
        self.states=[self.root/'first.fs',self.root/'second.fs']
        for i,p in enumerate(self.states): p.write_bytes(f'state {i}'.encode())
        self.app=Dashboard(self.root)
        self.data={'game':'vampire-savior','emulator':str(self.exe),
                   'snapshots':list(map(str,self.states)),
                   'rules':{**DEFAULT_RULES,'budget':24,'depth':1,'groups':['normals']}}
        self.app.prepare(self.data)
        self.session=self.app.session('vampire-savior')
        atomic_json(self.session/'bridge/ready.json',{'protocol':1,'rom':'vsavj','script_content':script.read_bytes().decode('utf-8')})
        atomic_json(self.session/'bridge/heartbeat.json',{'time':time.time()})
        self.prepared=json.loads((self.session/'session.json').read_text())['snapshots']
        self.config={'game':'vampire-savior','session':str(self.session),'action':'search',
                     'model':'unused','rules':self.data['rules'],'snapshots':self.prepared}

    def test_preparation_copies_all_states_and_persists_order(self):
        self.assertEqual([s['source'] for s in self.prepared],self.data['snapshots'])
        for source,item in zip(self.states,self.prepared):
            self.assertEqual((self.session/'bridge'/item['file']).read_bytes(),source.read_bytes())
        self.assertEqual(Dashboard(self.root).profile('vampire-savior')['snapshots'],self.data['snapshots'])
        self.assertEqual(self.app.connection('vampire-savior')['snapshot_hashes'],[s['snapshot_sha256'] for s in self.prepared])

    def test_reordering_invalidates_prepared_session(self):
        self.app.save({**self.data,'snapshots':self.data['snapshots'][::-1]})
        self.assertFalse(self.app.connection('vampire-savior')['prepared'])

    def test_queue_validation(self):
        for paths in ([],[''],[None],['x']*101,'x', ['bad'+chr(0)]):
            with self.subTest(paths=paths), self.assertRaises(ValueError):
                self.app.save({**self.data,'snapshots':paths})
        with self.assertRaises(ValueError):
            self.app.prepare({**self.data,'snapshots':[str(self.states[0]),str(self.root/'missing.fs')]})

    def test_legacy_single_state_still_prepares(self):
        self.app.prepare({'game':'vampire-savior','emulator':str(self.exe),'snapshot':str(self.states[0])})
        self.assertEqual(self.app.profile('vampire-savior')['snapshots'],[str(self.states[0])])

    def run_queue(self, action='search'):
        events=[]; selected=[]
        def bridge(*args,**kwargs):
            selected.append(kwargs['snapshot'])
            return SimulatedBridge()
        with patch('combochan.dashboard_worker.Bridge',side_effect=bridge):
            execute_queue({**self.config,'action':action},lambda **e:events.append(e))
        return events,selected

    def test_search_runs_each_state_with_full_budget_and_correct_hash(self):
        events,selected=self.run_queue()
        self.assertEqual(selected,['root.fs','state_2.fs'])
        results=[e for e in events if 'result' in e]
        self.assertEqual([e['queue_index'] for e in results],[1,2])
        self.assertEqual([e['result']['snapshot_sha256'] for e in results],[s['snapshot_sha256'] for s in self.prepared])
        self.assertEqual([e['result']['rules']['budget'] for e in results],[24,24])
        self.assertEqual([e['result']['snapshot_source'] for e in results],self.data['snapshots'])
        self.assertEqual(sum(e['stage']=='complete' for e in events),1)
        self.assertTrue(all(e['result']['best']['verified'] for e in results))

    def test_check_visits_all_states_and_keeps_verification_files(self):
        events,selected=self.run_queue('check')
        self.assertEqual(len(selected),2)
        self.assertEqual(sum('result' in e for e in events),2)
        self.assertTrue((self.session/'verify.json').exists())
        self.assertTrue((self.session/'state_2.fs.verify.json').exists())

    def test_each_starter_runs_independently_for_each_state(self):
        self.config['rules']={**self.config['rules'],'starters':['c.LK','c.HP'],'depth':2}
        events,selected=self.run_queue()
        self.assertEqual(selected,['root.fs','root.fs','state_2.fs','state_2.fs'])
        results=[e for e in events if 'result' in e]
        self.assertEqual([e['queue_index'] for e in results],[1,2,3,4])
        self.assertEqual([e['queue_total'] for e in results],[4]*4)
        self.assertEqual([e['state_index'] for e in results],[1,1,2,2])
        self.assertEqual([e['starter'] for e in results],['c.LK','c.HP']*2)
        for event in results:
            result=event['result']
            self.assertEqual(result['evaluated'],24)
            self.assertEqual(result['rules']['starters'],[event['starter']])
            self.assertEqual(result['rules']['budget'],24)
            self.assertTrue(result['best']['verified'])
            self.assertTrue(result['best']['notation'].startswith(event['starter']))
        self.app.job={'id':'starters','stage':'starting','logs':[]}
        process=Mock(stdout=io.StringIO('\n'.join(json.dumps(e) for e in events)),wait=lambda:0)
        self.app.watch(process,'starters')
        self.assertEqual(set(self.app.result_files()),{'starters-1','starters-2','starters-3','starters-4'})
        self.assertEqual([r['starter'] for r in self.app.history()].count('c.LK'),2)

    def test_multiple_starters_work_without_snapshot_queue(self):
        config={**self.config,'rules':{**self.config['rules'],'starters':['c.LK','c.HP']}}
        config.pop('snapshots')
        events=[]
        with patch('combochan.dashboard_worker.Bridge',SimulatedBridge):
            execute_queue(config,lambda **e:events.append(e))
        self.assertEqual([e['result']['starter'] for e in events if 'result' in e],['c.LK','c.HP'])

    def test_sequence_starters_keep_complete_prefixes_in_separate_results(self):
        self.config['rules']={**self.config['rules'],'starters':['2LK2LK','2HP'],'depth':3}
        events,selected=self.run_queue()
        results=[e['result'] for e in events if 'result' in e]
        self.assertEqual([r['starter'] for r in results],['2LK2LK','2HP']*2)
        for result in results:
            route=result['best']
            if result['starter']=='2LK2LK':
                self.assertEqual(route['notation'].count('c.LK'),2)
                self.assertEqual([s['buttons'] for s in route['steps'] if s['buttons']],[('D','LK'),('D','LK')])
                self.assertTrue(any(not s['buttons'] and s['frames']>=1 for s in route['steps']))
            else:self.assertTrue(route['notation'].startswith('c.HP'))

    def test_incomplete_prefix_cannot_be_saved_as_best(self):
        class BrokenPrefixBridge(SimulatedBridge):
            def run(self,trials,speed='turbo'):
                records,manifest=super().run(trials,speed)
                for record in records:
                    if record['id'].startswith('d2_'):
                        for row in record['trace']:row['p2']['health']=288
                return records,manifest
        config={**self.config,'rules':{**self.config['rules'],'starters':['2LK2LK'],'depth':2}}
        events=[]
        with patch('combochan.dashboard_worker.Bridge',BrokenPrefixBridge):
            execute_queue(config,lambda **e:events.append(e))
        self.assertTrue(all(e['result']['best'] is None for e in events if 'result' in e))

    def test_starter_selections_persist_and_checks_do_not_repeat_for_each_starter(self):
        self.app.save({**self.data,'rules':{**self.data['rules'],'starters':['c.LK','c.HP']}})
        self.assertEqual(Dashboard(self.root).profile('vampire-savior')['rules']['starters'],['c.LK','c.HP'])
        self.config['rules']=self.app.profile('vampire-savior')['rules']
        events,selected=self.run_queue('check')
        self.assertEqual(selected,['root.fs','state_2.fs'])
        self.assertEqual(sum('result' in e for e in events),2)

    def test_stop_between_starters_keeps_first_result_and_skips_rest(self):
        calls=[];events=[]
        config={**self.config,'rules':{**self.config['rules'],'starters':['c.LK','c.HP']}}
        def execute(config,emit):
            calls.append(config['rules']['starter'])
            emit(stage='complete',result={'best':None})
            (self.session/'cancel.flag').write_text('stop')
        with patch('combochan.dashboard_worker.execute',side_effect=execute):
            with self.assertRaises(Cancelled):execute_queue(config,lambda **e:events.append(e))
        self.assertEqual(calls,['c.LK'])
        self.assertEqual(len([e for e in events if 'result' in e]),1)

    def test_failure_does_not_start_next_starter(self):
        config={**self.config,'rules':{**self.config['rules'],'starters':['c.LK','c.HP']}}
        with patch('combochan.dashboard_worker.execute',side_effect=RuntimeError('emulator failed')) as execute:
            with self.assertRaisesRegex(RuntimeError,'emulator failed'):execute_queue(config,lambda **e:None)
        self.assertEqual(execute.call_count,1)

    def test_stop_between_states_does_not_start_next(self):
        calls=[]
        def execute(config,emit):
            calls.append(config['snapshot_file'])
            emit(stage='complete',result={'best':None})
            (self.session/'cancel.flag').write_text('stop')
        with patch('combochan.dashboard_worker.execute',side_effect=execute):
            with self.assertRaises(Cancelled): execute_queue(self.config,lambda **e:None)
        self.assertEqual(calls,['root.fs'])

    def test_failure_does_not_start_next_state(self):
        with patch('combochan.dashboard_worker.execute',side_effect=RuntimeError('emulator failed')) as execute:
            with self.assertRaisesRegex(RuntimeError,'emulator failed'):
                execute_queue(self.config,lambda **e:None)
        self.assertEqual(execute.call_count,1)

    def test_watch_keeps_separate_results_and_busy_until_exit(self):
        events,_=self.run_queue()
        self.app.job={'id':'batch','stage':'starting','logs':[]}
        def wait():
            self.assertNotEqual(self.app.job['stage'],'complete')
            with self.assertRaises(ValueError): self.app.idle()
            return 0
        process=Mock(stdout=io.StringIO('\n'.join(json.dumps(e) for e in events)),wait=wait)
        self.app.watch(process,'batch')
        self.assertEqual(self.app.job['stage'],'complete')
        self.assertEqual(set(self.app.result_files()),{'batch-1','batch-2'})
        self.assertEqual({r['snapshot_source'] for r in self.app.history()},set(self.data['snapshots']))

    def test_replay_selects_matching_queued_state_only(self):
        self.app.save({**self.data,'rules':{**self.data['rules'],'starters':['c.LK','c.HP']}})
        atomic_json(self.app.data/'runs/saved.json',{'game':'vampire-savior','best':{'snapshot_sha256':self.prepared[1]['snapshot_sha256']}})
        with patch('combochan.dashboard.subprocess.Popen'),patch('combochan.dashboard.threading.Thread'):
            run=self.app.start({'game':'vampire-savior','action':'replay','result_id':'saved'})
        config=json.loads((self.session/(run['id']+'.job.json')).read_text())
        self.assertEqual(config['snapshot_file'],'state_2.fs')
        with patch('combochan.dashboard_worker.execute') as execute:
            execute_queue(config)
        self.assertEqual(execute.call_count,1)
        self.assertEqual(execute.call_args.args[0]['snapshot_file'],'state_2.fs')

    def test_bridge_request_and_manifest_use_selected_snapshot(self):
        directory=self.session/'bridge'
        def finish(_):
            request=directory/'request.tsv'
            header=request.read_text().splitlines()[0].split('\t')
            self.assertEqual(header[2],'state_2.fs')
            request.unlink()
            record={'id':'trial','repetition':1,'defense':'neutral','trace':[{}, {}, {}]}
            (directory/(header[1]+'.jsonl')).write_text(json.dumps(record))
        with patch('combochan.bridge.time.sleep',side_effect=finish):
            _,manifest=Bridge(directory,snapshot='state_2.fs').run([Trial('trial',(Step(1),),tail=1)])
        self.assertEqual(manifest['snapshot_sha256'],self.prepared[1]['snapshot_sha256'])
        self.assertEqual(self.states[1].read_bytes(),b'state 1')

    def test_bridge_rejects_paths_outside_session(self):
        for filename in ('../state.fs','C:/state.fs','state.fs\tbad','state.txt','.fs'):
            with self.subTest(filename=filename),self.assertRaises(ValueError):
                Bridge(self.session/'bridge',snapshot=filename)

    def test_legacy_session_exposes_replay_hash(self):
        metadata=json.loads((self.session/'session.json').read_text())
        metadata.pop('snapshots')
        atomic_json(self.session/'session.json',metadata)
        self.assertEqual(self.app.connection('vampire-savior')['snapshot_hashes'],[metadata['snapshot_sha256']])
