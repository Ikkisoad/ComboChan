import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from combochan.dashboard import Dashboard, validate_rules
from combochan.dashboard_worker import execute
from combochan.game_profile import ConfiguredGame, lua_value, template, validate_profile
from combochan.games import GAMES
from test_dashboard import SimulatedBridge


def profile():
    data = template()
    data['health_max'] = 300
    data['rom'] = 'testrom'
    for index, fields in enumerate(data['players'].values()):
        for offset, spec in enumerate(fields.values()):
            spec['address'] = hex(0x1000 + index * 256 + offset * 2)
    return data


class ProfileTests(unittest.TestCase):
    def test_template_requires_manual_values(self):
        with self.assertRaisesRegex(ValueError, 'health_max'):
            ConfiguredGame(template())

    def test_profile_is_copied_and_normalized(self):
        data = profile()
        game = ConfiguredGame(data)
        self.assertEqual(game.definition['players']['p1']['health']['address'], 0x1000)
        self.assertIsInstance(data['players']['p1']['health']['address'], str)
        data['title'] = 'Changed'
        self.assertEqual(game.title, 'My Game')
        self.assertEqual(game.profile_sha256, ConfiguredGame(game.definition).profile_sha256)

    def test_bad_fields_rejected(self):
        mutations = [lambda d: d.update(version=True), lambda d: d.update(id='vampire-savior'),
                     lambda d: d['players']['p1'].pop('stun1'),
                     lambda d: d['players']['p1']['health'].update(address=None),
                     lambda d: d['players']['p1']['health'].update(type='function()'),
                     lambda d: d['players']['p1']['health'].update(mask=-1),
                     lambda d: d['inputs']['LP'].update(p1='P1 Up'),
                     lambda d: d['moves'][0].update(sequence='HP'),
                     lambda d: d.update(unexpected=True)]
        for change in mutations:
            with self.subTest(change=change):
                data = profile(); change(data)
                with self.assertRaises(ValueError): validate_profile(data)

    def test_rules_require_real_capabilities(self):
        game = ConfiguredGame(profile())
        rules = validate_rules({'true_combo': False}, game)
        self.assertEqual(rules['groups'], ['configured'])
        self.assertEqual(len(game.search_actions(rules)), 2)
        with self.assertRaisesRegex(ValueError, 'combo_validated'):
            validate_rules({'true_combo': True}, game)
        with self.assertRaisesRegex(ValueError, 'stocks'):
            validate_rules({'true_combo': False, 'resources': 'cap'}, game)
        with self.assertRaisesRegex(ValueError, 'absent'):
            validate_rules({'true_combo': False, 'custom_moves': [{'name': 'bad', 'sequence': 'HK'}]}, game)

    def test_lua_strings_are_data(self):
        self.assertEqual(lua_value('"\\\n'), '"\\034\\092\\010"')
        script = ConfiguredGame(profile()).session_script()
        self.assertIn('COMBOCHAN_GAME = {', script)
        self.assertNotIn('None', script)

    def test_dashboard_session_identity(self):
        game = ConfiguredGame(profile())
        with patch.dict(GAMES, {game.id: game}), tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            exe = root / 'fcadefbneo.exe'; exe.write_bytes(b'fake')
            state = root / 'test.fs'; state.write_bytes(b'snapshot')
            app = Dashboard(root)
            self.assertEqual(app.profile(game.id)['snapshot'], '')
            app.prepare({'game': game.id, 'emulator': str(exe), 'snapshot': str(state)})
            session = app.session(game.id)
            self.assertEqual(json.loads((session/'game-profile.json').read_text()), game.definition)
            self.assertIn(game.profile_sha256, (session/'connect.lua').read_text())
            (session/'bridge/heartbeat.json').write_text(json.dumps({'time': time.time()}))
            ready = {'rom': game.rom, 'profile_sha256': 'wrong'}
            (session/'bridge/ready.json').write_text(json.dumps(ready))
            self.assertFalse(app.connection(game.id)['connected'])
            ready['profile_sha256'] = game.profile_sha256
            (session/'bridge/ready.json').write_text(json.dumps(ready))
            self.assertTrue(app.connection(game.id)['connected'])
            changed = profile(); changed['players']['p1']['health']['address'] = 1234
            GAMES[game.id] = ConfiguredGame(changed)
            self.assertFalse(app.connection(game.id)['prepared'])
            self.assertEqual(state.read_bytes(), b'snapshot')

    def test_worker_profile_search_replay_and_stale_rejection(self):
        data = profile(); data['combo_validated'] = True
        game = ConfiguredGame(data)
        # No global registration: exercises subprocess reconstruction from job data.
        with tempfile.TemporaryDirectory() as folder:
            session = Path(folder); (session/'bridge').mkdir()
            (session/'bridge/root.fs').write_bytes(b'snapshot')
            script = Path(__file__).resolve().parents[1]/'bridge/runner.lua'
            ready = {'script_content': script.read_bytes().decode('utf-8'), 'profile_sha256': game.profile_sha256}
            (session/'bridge/ready.json').write_text(json.dumps(ready), encoding='utf-8')
            config = {'game': game.id, 'game_profile': data, 'session': str(session), 'action': 'search',
                      'model': 'unused', 'rules': validate_rules({'budget': 24, 'depth': 1}, game)}
            events = []
            with patch('combochan.dashboard_worker.Bridge', SimulatedBridge):
                execute(config, lambda **e: events.append(e))
                result = events[-1]['result']
                self.assertTrue(result['best']['verified'])
                self.assertEqual(result['best']['profile_sha256'], game.profile_sha256)
                self.assertEqual(result['game_profile'], game.definition)
                replay = {**config, 'action': 'replay', 'replay': result['best']}
                execute(replay, lambda **e: events.append(e))
                self.assertTrue(events[-1]['result']['replay'])
                replay['replay'] = {**result['best'], 'profile_sha256': 'wrong'}
                with self.assertRaisesRegex(ValueError, 'original game profile'): execute(replay)
                ready['profile_sha256'] = 'wrong'
                (session/'bridge/ready.json').write_text(json.dumps(ready), encoding='utf-8')
                with self.assertRaisesRegex(RuntimeError, 'profile changed'): execute(config)


if __name__ == '__main__':
    unittest.main()
