import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from combochan.dashboard import Dashboard, Server
from combochan.games import GAMES
from test_game_profile import profile


class WizardTests(unittest.TestCase):
    def setUp(self):
        self.registry=patch.dict(GAMES);self.registry.start();self.addCleanup(self.registry.stop)
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=Dashboard(Path(self.tmp.name))
        self.definition=profile();self.definition['id']='wizard-test'

    def test_save_reload_edit_and_conflict(self):
        saved=self.app.save_game_profile({'definition':self.definition})
        self.assertIn('wizard-test',self.app.status()['game_definitions'])
        del GAMES['wizard-test']
        restarted=Dashboard(Path(self.tmp.name))
        self.assertEqual(GAMES['wizard-test'].title,'My Game')
        changed={**self.definition,'title':'Updated game'}
        data={'definition':changed,'original_id':'wizard-test','original_sha256':saved['profile_sha256']}
        restarted.save_game_profile(data)
        self.assertEqual(GAMES['wizard-test'].title,'Updated game')
        with self.assertRaisesRegex(ValueError,'changed elsewhere'):restarted.save_game_profile(data)
        with self.assertRaisesRegex(ValueError,'already exists'):restarted.save_game_profile({'definition':self.definition})

    def test_busy_invalid_and_builtin_do_not_persist(self):
        self.app.job['stage']='searching'
        with self.assertRaisesRegex(ValueError,'active'):self.app.save_game_profile({'definition':self.definition})
        self.app.job['stage']='idle'
        for data in ({'definition':None},{'definition':{**self.definition,'id':'../escape'}},
                     {'definition':{**self.definition,'id':'vampire-savior'}}):
            with self.assertRaises(ValueError):self.app.save_game_profile(data)
        self.assertFalse((self.app.data/'game-profiles.json').exists())

    def test_edit_invalidates_session(self):
        saved=self.app.save_game_profile({'definition':self.definition})
        exe=Path(self.tmp.name)/'fcadefbneo.exe';exe.write_bytes(b'fake')
        snapshot=Path(self.tmp.name)/'state.fs';snapshot.write_bytes(b'snapshot')
        self.app.prepare({'game':'wizard-test','emulator':str(exe),'snapshot':str(snapshot)})
        self.assertTrue(self.app.connection('wizard-test')['prepared'])
        self.definition['players']['p1']['health']['address']=999
        self.app.save_game_profile({'definition':self.definition,'original_id':'wizard-test','original_sha256':saved['profile_sha256']})
        self.assertFalse(self.app.connection('wizard-test')['prepared'])

    def test_http_wizard_requires_token_and_serves_script(self):
        server=Server(('127.0.0.1',0),self.app)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        client=http.client.HTTPConnection('127.0.0.1',server.server_port)
        try:
            for path in ['/game-wizard.js','/api/game-profile-template']:
                client.request('GET',path);response=client.getresponse();self.assertEqual(response.status,200);response.read()
            body=json.dumps({'definition':self.definition})
            client.request('POST','/api/game-profiles/save',body);response=client.getresponse();self.assertEqual(response.status,403);response.read()
            headers={'X-ComboChan-Token':self.app.token,'Content-Type':'application/json'}
            for path in ['/api/game-profiles/validate','/api/game-profiles/save']:
                client.request('POST',path,body,headers);response=client.getresponse();self.assertEqual(response.status,200);response.read()
        finally:
            client.close();server.shutdown();server.server_close()
