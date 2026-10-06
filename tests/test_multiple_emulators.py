from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from combochan.bridge import BridgePool, Step, Trial
from combochan.dashboard import Dashboard, DEFAULT_RULES, atomic_json
from combochan.dashboard_worker import Cancelled, execute_queue
from test_dashboard import SimulatedBridge


class MultipleEmulatorsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.exe = self.root/'fcadefbneo.exe'
        self.exe.write_bytes(b'fixture')
        self.states = [self.root/'one.fs', self.root/'two.fs']
        for i, path in enumerate(self.states):
            path.write_bytes(bytes([i]))
        self.app = Dashboard(self.root)
        self.data = {'game': 'vampire-savior', 'emulator': str(self.exe),
                     'snapshots': list(map(str, self.states)), 'instance_count': 3,
                     'rules': {**DEFAULT_RULES, 'budget': 24, 'depth': 2, 'groups': ['normals']}}
        self.app.prepare(self.data)
        self.sessions = self.app.sessions('vampire-savior')
        script = Path(__file__).resolve().parents[1]/'bridge/runner.lua'
        for session in self.sessions:
            atomic_json(session/'bridge/ready.json', {'rom': 'vsavj', 'script_content': script.read_bytes().decode('utf-8')})
            atomic_json(session/'bridge/heartbeat.json', {'time': time.time()})
        self.config = {'game': 'vampire-savior', 'session': str(self.sessions[0]),
                       'sessions': list(map(str, self.sessions)), 'action': 'search',
                       'model': 'unused', 'rules': self.data['rules'],
                       'snapshots': json.loads((self.sessions[0]/'session.json').read_text())['snapshots']}

    def test_isolated_snapshots_scripts_and_persisted_count(self):
        self.assertEqual(Dashboard(self.root).profile('vampire-savior')['instance_count'], 3)
        scripts = []
        for session in self.sessions:
            for name, source in zip(('root.fs', 'state_2.fs'), self.states):
                self.assertEqual((session/'bridge'/name).read_bytes(), source.read_bytes())
            scripts.append((session/'connect.lua').read_text())
        self.assertEqual(len(set(scripts)), 3)
        self.assertEqual(self.app.profile('street-fighter-iii-third-strike')['instance_count'], 1)

    def test_invalid_count_rejected_and_change_requires_preparation(self):
        for count in (0, 17, -1, 1.5, '2', True, None):
            with self.subTest(count=count), self.assertRaises(ValueError):
                self.app.save({**self.data, 'instance_count': count})
        self.app.save({**self.data, 'instance_count': 2})
        self.assertFalse(self.app.connection('vampire-savior')['prepared'])

    def test_all_runners_must_be_fresh_and_have_no_pending_requests(self):
        self.assertTrue(self.app.connection('vampire-savior')['connected'])
        atomic_json(self.sessions[1]/'bridge/heartbeat.json', {'time': time.time()-30})
        connection = self.app.connection('vampire-savior')
        self.assertEqual(connection['label'], '2/3 runners connected')
        with self.assertRaises(ValueError):
            self.app.start({'game': 'vampire-savior'})
        atomic_json(self.sessions[1]/'bridge/heartbeat.json', {'time': time.time()})
        (self.sessions[2]/'bridge/client.lock').write_text('busy')
        self.assertTrue(self.app.connection('vampire-savior')['pending'])
        with self.assertRaisesRegex(ValueError, 'unfinished request'):
            self.app.start({'game': 'vampire-savior'})

    def test_launch_retries_only_missing_or_exited_instances(self):
        for session in self.sessions:
            (session/'bridge/heartbeat.json').unlink()
        processes = [Mock(poll=Mock(return_value=None)) for _ in range(4)]
        with patch('combochan.games.VampireSavior.launch_arguments',
                   side_effect=lambda exe, script: [str(exe), str(script)]), \
             patch('combochan.windows_launch.launch_visible' if os.name=='nt' else 'combochan.dashboard.subprocess.Popen', side_effect=processes) as launch:
            self.assertEqual(self.app.launch('vampire-savior')['launched'], 3)
            self.assertEqual(self.app.launch('vampire-savior')['launched'], 0)
            processes[1].poll.return_value = 0
            self.assertEqual(self.app.launch('vampire-savior')['launched'], 1)
            self.assertEqual(launch.call_count, 4)
            self.assertEqual([call.args[0][1] for call in launch.call_args_list[:3]],
                             [str(path/'connect.lua') for path in self.sessions])

    def test_partial_launch_failure_can_be_retried(self):
        for session in self.sessions:
            (session/'bridge/heartbeat.json').unlink()
        process = Mock(poll=Mock(return_value=None))
        with patch('combochan.games.VampireSavior.launch_arguments', return_value=[str(self.exe)]), \
             patch('combochan.windows_launch.launch_visible' if os.name=='nt' else 'combochan.dashboard.subprocess.Popen', side_effect=[process, OSError('launch failed'), process, process]):
            with self.assertRaisesRegex(ValueError, 'Launched 1'):
                self.app.launch('vampire-savior')
            self.assertEqual(self.app.launch('vampire-savior')['launched'], 2)

    def test_worker_receives_all_session_paths(self):
        with patch('combochan.dashboard.subprocess.Popen'), patch('combochan.dashboard.threading.Thread'):
            result = self.app.start({'game': 'vampire-savior'})
        config = json.loads((self.sessions[0]/(result['id']+'.job.json')).read_text())
        self.assertEqual(config['sessions'], list(map(str, self.sessions)))

    def run_simulation(self, events, transform=None):
        calls = []
        class Simulator(SimulatedBridge):
            def __init__(self, directory, **kwargs):
                self.directory = directory
            def run(self, trials, speed='turbo'):
                calls.append((self.directory, trials, speed))
                rows, _ = super().run(trials, speed)
                if transform:
                    transform(self.directory, rows)
                return rows, {'job': str(self.directory), 'trials': [asdict(t) for t in trials]}
        with patch('combochan.dashboard_worker.Bridge', Simulator):
            execute_queue(self.config, lambda **event: events.append(event))
        return calls

    def test_parallel_search_preserves_queue_budgets_results_and_gates(self):
        events = []
        calls = self.run_simulation(events)
        results = [event['result'] for event in events if 'result' in event]
        self.assertEqual(len(results), 2)
        self.assertEqual([result['evaluated'] for result in results], [24, 24])
        self.assertTrue(all(result['best']['verified'] for result in results))
        gates = [trials[0] for _, trials, _ in calls if trials[0].id=='restore']
        self.assertEqual(len(gates), 6)
        self.assertTrue(all(trial.repeats==100 for trial in gates))
        self.assertEqual(len({directory for directory, trials, _ in calls if trials[0].id.startswith('d')}), 3)
        gate = json.loads((self.sessions[0]/'verify.json').read_text())
        self.assertEqual(gate['repeatability']['restore']['runs'], 300)
        self.assertEqual(len(gate['manifest']['worker_manifests']), 3)

    def test_different_emulator_traces_stop_search(self):
        def change(directory, rows):
            if directory==self.sessions[1]/'bridge':
                for row in rows:
                    row['trace'][0]['p1']['x'] += 1
        with self.assertRaisesRegex(RuntimeError, 'matching across all instances'):
            self.run_simulation([], change)

    def test_cancel_waits_for_active_batch_and_skips_search(self):
        def stop(directory, rows):
            (self.sessions[0]/'cancel.flag').write_text('stop')
        with self.assertRaises(Cancelled):
            self.run_simulation([], stop)

    def test_outdated_secondary_runner_rejected_before_trials(self):
        atomic_json(self.sessions[1]/'bridge/ready.json', {'script_content': 'old'})
        with patch('combochan.dashboard_worker.Bridge') as bridge:
            with self.assertRaisesRegex(RuntimeError, 'outdated'):
                execute_queue(self.config, lambda **event: None)
            bridge.return_value.run.assert_not_called()


class BridgePoolTests(unittest.TestCase):
    def test_trials_execute_concurrently_once_and_return_in_request_order(self):
        barrier = threading.Barrier(3)
        assignments = []
        class Runner:
            def run(self, trials, speed):
                assignments.extend(trial.id for trial in trials)
                barrier.wait(timeout=5)
                rows = [{'id': t.id, 'repetition': r} for t in reversed(trials) for r in range(t.repeats, 0, -1)]
                return rows, {'trials': [asdict(t) for t in trials], 'raw_results': 'trace.jsonl'}
        trials = [Trial(f't{i}', (Step(1),), repeats=2) for i in range(8)]
        records, manifest = BridgePool([Runner() for _ in range(3)]).run(trials)
        self.assertCountEqual(assignments, [t.id for t in trials])
        self.assertEqual([(r['id'], r['repetition']) for r in records],
                         [(t.id, r) for t in trials for r in (1, 2)])
        self.assertEqual(len(manifest['worker_manifests']), 3)
        self.assertTrue(all(m['raw_results']=='trace.jsonl' for m in manifest['worker_manifests']))

    def test_failed_batch_waits_for_other_active_workers(self):
        barrier = threading.Barrier(2)
        finished = threading.Event()
        def fail(trials, speed):
            barrier.wait(timeout=5)
            raise RuntimeError('emulator failed')
        def finish(trials, speed):
            barrier.wait(timeout=5)
            time.sleep(.05)
            finished.set()
            return [], {}
        pool = BridgePool([Mock(run=fail), Mock(run=finish)])
        with self.assertRaisesRegex(RuntimeError, 'emulator failed'):
            pool.run([Trial('one', (Step(1),)), Trial('two', (Step(1),))])
        self.assertTrue(finished.is_set())


if __name__=='__main__':
    unittest.main()
