import json,tempfile,unittest
from pathlib import Path
from combochan.dashboard import Dashboard

class ResultLibraryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.app=Dashboard(self.root)
  self.runs=self.root/'artifacts/dashboard/runs';self.runs.mkdir(parents=True)
  for id,game in [('one','vampire-savior'),('two','vampire-savior'),('other','future-game')]:
   (self.runs/(id+'.json')).write_text(json.dumps({'result':{'game':game,'best':{'damage':10,'notation':id}}}))
 def test_favorite_persists_after_reload(self):
  self.app.favorite({'id':'one','favorite':True})
  self.assertTrue(next(r for r in Dashboard(self.root).history() if r['id']=='one')['favorite'])
  self.app.favorite({'id':'one','favorite':False})
  self.assertFalse(next(r for r in self.app.history() if r['id']=='one')['favorite'])
 def test_clear_preserves_favorites_other_games_and_files(self):
  self.app.favorite({'id':'one','favorite':True})
  cleared=self.app.clear_results({'game':'vampire-savior'})
  self.assertEqual(cleared['cleared'],['two'])
  self.assertEqual({r['id'] for r in Dashboard(self.root).history()},{'one','other'})
  self.assertTrue((self.runs/'two.json').exists())
  self.app.restore_results({'ids':cleared['cleared']})
  self.assertEqual(len(self.app.history()),3)
 def test_clear_includes_results_beyond_old_display_limit(self):
  for i in range(40):(self.runs/(str(i)+'.json')).write_text(json.dumps({'best':{'damage':1}}))
  self.assertEqual(len(self.app.clear_results({'game':'vampire-savior'})['cleared']),42)
 def test_invalid_favorite_and_ids_are_rejected(self):
  for data in ({'id':'../secret','favorite':True},{'id':'one','favorite':'yes'}):
   with self.assertRaises(ValueError):self.app.favorite(data)
 def test_legacy_results_can_be_favorited_and_cleared(self):
  p=self.root/'artifacts/search-heuristic-0.json';p.write_text(json.dumps({'best':{'damage':4}}))
  self.app.favorite({'id':'legacy-search-heuristic-0','favorite':True})
  self.app.clear_results({'game':'vampire-savior'})
  self.assertTrue(any(r['id']=='legacy-search-heuristic-0' for r in self.app.history()))
if __name__=='__main__':unittest.main()
