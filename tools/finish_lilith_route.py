import json,shutil,subprocess,time,uuid,sys
from pathlib import Path
from combochan.bridge import Bridge,Step,Trial
from combochan.games import get_game
from combochan.dashboard import DEFAULT_RULES
from combochan.evaluate import repeatability

def main():
 root=Path.cwd()
 if len(sys.argv)!=2:raise SystemExit('Usage: python -m tools.finish_lilith_route PATH_TO_DIAGNOSTIC_BRIDGE')
 source=Path(sys.argv[1]).resolve();game=get_game('vampire-savior');choices=[]
 for path in source.glob('*.jsonl'):
  request=source/(path.stem+'.accepted.tsv')
  if not request.exists():continue
  inputs={r.split('\t')[0]:r.split('\t')[4] for r in request.read_text().splitlines()[1:]}
  for line in path.open():
   record=json.loads(line)
   if not record['id'].startswith('route_4_'):continue
   score=game.score(record,DEFAULT_RULES)
   if score['damage']>19 and score['rejection_reasons']==['unresolved_hitstun']:
    steps=tuple(Step(int(token.split(':')[0]),tuple(token.split(':')[1].split(',')) if token.split(':')[1] else ()) for token in inputs[record['id']].split(';'))
    choices.append((score['damage'],steps))
 choices.sort(key=lambda item:(-item[0],sum(s.frames for s in item[1])))
 selected=[];seen=set()
 for _,steps in choices:
  if steps not in seen:selected.append(steps);seen.add(steps)
  if len(selected)==12:break
 folder=root/'artifacts/route-tests'/uuid.uuid4().hex;bridge_dir=folder/'bridge';bridge_dir.mkdir(parents=True);shutil.copy2(source/'root.fs',bridge_dir/'root.fs')
 script=folder/'connect.lua';script.write_text('COMBOCHAN_BRIDGE_DIR = '+json.dumps(bridge_dir.as_posix()+'/')+'\nreturn assert(loadfile('+json.dumps((root/'bridge/runner.lua').as_posix())+'))()\n',encoding='ascii')
 profile=json.loads((root/'artifacts/dashboard/config.json').read_text())['vampire-savior'];exe=Path(profile['emulator']);proc=subprocess.Popen(game.launch_arguments(exe,script),cwd=exe.parent)
 try:
  for _ in range(30):
   if (bridge_dir/'ready.json').exists():break
   time.sleep(1)
  bridge=Bridge(bridge_dir,timeout=90);records,manifest=bridge.run([Trial('extended_'+str(i),steps,tail=360) for i,steps in enumerate(selected)])
  valid=[]
  for steps,record in zip(selected,records):
   score=game.score(record,DEFAULT_RULES);print(json.dumps({'damage':score['damage'],'rejections':score['rejection_reasons']}),flush=True)
   if score['candidate_valid']:valid.append((score,steps))
  valid.sort(key=lambda item:-item[0]['damage'])
  for score,steps in valid:
   replays,check_manifest=bridge.run([Trial('verify_'+d,steps,tail=360,defense=d,repeats=3) for d in ('neutral','stand','crouch','jump')])
   scores=[game.score(r,DEFAULT_RULES) for r in replays]
   passed=all(s['candidate_valid'] and s['damage_events']==score['damage_events'] for s in scores) and all(g['identical'] for g in repeatability(replays).values())
   if passed:
    import hashlib
    digest=hashlib.sha256((bridge_dir/'root.fs').read_bytes()).hexdigest();id=uuid.uuid4().hex
    best={'notation':'Saved jHP > 2LK > 2MK > 2HP > Lilith demon','damage':score['damage'],'steps':[{'frames':s.frames,'buttons':s.buttons} for s in steps],'tail':360,'verified':True,'reproduced':True,'snapshot_sha256':digest,'validation':scores,'starting_hitstun':True}
    result={'game':game.id,'rules':{**DEFAULT_RULES,'policy':'heuristic'},'best':best,'evaluated':len(selected)+3+183+732+732+488,'snapshot_sha256':digest,'session':str(folder),'manifests':[manifest,check_manifest],'scope':'User-specified route timing diagnostic; not unconstrained search.'}
    (folder/'result.json').write_text(json.dumps(result,indent=2));(root/'artifacts/dashboard/runs'/(id+'.json')).write_text(json.dumps({'id':id,'result':result},indent=2))
    print('VERIFIED '+str(folder/'result.json'),flush=True);break
  else: print('No route passed complete defensive validation.',flush=True)
 finally:proc.terminate()

if __name__=='__main__':main()
