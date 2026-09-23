"""Bounded emulator diagnostic for the user's Lilith route (separate session)."""
import hashlib,json,shutil,subprocess,time,uuid
from pathlib import Path
from combochan.bridge import Bridge,Step,Trial
from combochan.games import get_game
from combochan.moves import parse_sequence
from combochan.dashboard import DEFAULT_RULES

def main():
 root=Path.cwd();profile=json.loads((root/'artifacts/dashboard/config.json').read_text())['vampire-savior']
 folder=root/'artifacts/route-tests'/uuid.uuid4().hex;bridge_dir=folder/'bridge';bridge_dir.mkdir(parents=True)
 shutil.copy2(Path(profile['session'])/'bridge/root.fs',bridge_dir/'root.fs')
 script=folder/'connect.lua';script.write_text('COMBOCHAN_BRIDGE_DIR = '+json.dumps(bridge_dir.as_posix()+'/')+'\nreturn assert(loadfile('+json.dumps((root/'bridge/runner.lua').as_posix())+'))()\n',encoding='ascii')
 game=get_game('vampire-savior');exe=Path(profile['emulator']);proc=subprocess.Popen(game.launch_arguments(exe,script),cwd=exe.parent)
 print('Diagnostic session: '+str(folder),flush=True)
 try:
  for _ in range(30):
   if (bridge_dir/'ready.json').exists():break
   time.sleep(1)
  bridge=Bridge(bridge_dir,timeout=45);rules={**DEFAULT_RULES,'true_combo':True}
  targets=[('jHP',('HP',)),('2LK',('D','LK')),('2MK',('D','MK')),('2HP',('D','HP')),('Demon',None)]
  frontier=[{'steps':(),'notation':'','damage':0}];manifests=[];stages=[]
  for depth,(name,buttons) in enumerate(targets):
   candidates=[]
   for parent in frontier:
    for delay in ([0] if depth==0 else range(61)):
     variants=[(Step(hold,buttons),) for hold in (1,2,3)] if buttons else [parse_sequence(seq) for seq in ('LP, N, LP, F, LK, HP','LP:2, N:2, LP:2, F:2, LK:2, HP:2')]
     for action in variants:
      steps=parent['steps']+((Step(delay),) if delay else ())+action
      if sum(s.frames for s in steps)>240:continue
      candidates.append({'steps':steps,'notation':parent['notation']+(' > ' if parent['notation'] else '')+f'[{delay}f] '+name,'parent_damage':parent['damage']})
   survivors=[]
   for offset in range(0,len(candidates),16):
    batch=candidates[offset:offset+16];records,manifest=bridge.run([Trial(f'route_{depth}_{offset+i}',c['steps'],tail=240) for i,c in enumerate(batch)])
    manifests.append(manifest)
    for candidate,record in zip(batch,records):
     score=game.score(record,rules)
     if (score['candidate_valid'] and (depth==0 or score['damage']>candidate['parent_damage'])) or (depth==0 and score['rejection_reasons']==['no_damage']):
      candidate.update(damage=score['damage'],score=score);survivors.append(candidate)
   survivors.sort(key=lambda c:(-c['damage'],sum(s.frames for s in c['steps'])))
   # Keep distinct hit timings, not only duplicate holds of the same effective route.
   frontier=[];seen=set()
   for c in survivors:
    signature=tuple(h['frame'] for h in c['score']['damage_events'])
    if signature not in seen:frontier.append(c);seen.add(signature)
    if len(frontier)==4:break
   stages.append({'move':name,'trials':len(candidates),'valid_extensions':len(survivors),'best_damage':frontier[0]['damage'] if frontier else None})
   print(json.dumps(stages[-1]),flush=True)
   (folder/'progress.json').write_text(json.dumps(stages,indent=2))
   if not frontier:break
  result={'stages':stages,'manifests':manifests,'snapshot_sha256':hashlib.sha256((bridge_dir/'root.fs').read_bytes()).hexdigest()}
  if frontier:
   best=frontier[0];records,manifest=bridge.run([Trial('validate_'+d,best['steps'],tail=240,defense=d,repeats=3) for d in ('neutral','stand','crouch','jump')]);scores=[game.score(r,rules) for r in records]
   passed=all(s['candidate_valid'] and s['damage_events']==best['score']['damage_events'] for s in scores)
   result['best']={'notation':best['notation'],'damage':best['damage'],'verified':passed,'steps':[{'frames':s.frames,'buttons':s.buttons} for s in best['steps']],'validation':scores}
  (folder/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result.get('best',{'no_full_route':True})),flush=True)
 finally:proc.terminate()

if __name__=='__main__':main()
