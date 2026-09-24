"""Loopback-only dashboard. No web framework, CDN, or cloud service required."""
from __future__ import annotations
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
import uuid
import webbrowser

from .games import GAMES, get_game
from .moves import validate_custom_moves

ROOT=Path(__file__).resolve().parents[1]
DEFAULT_RULES={'resources':'state','stock_cap':0,'true_combo':True,'policy':'heuristic',
               'budget':600,'depth':5,'beam':8,'seed':0,'delays':[0,2,4,6,8,12,16],
               'custom_moves':[],'disabled_actions':[],'auto_timing':True,'max_delay':60,'max_start_delay':0,
               'max_frames':180,'tail':90,'groups':['normals','motions','movement']}
BUSY={'starting','checking','model','searching','validating','replaying','stopping'}


def validate_rules(data,game):
    if not isinstance(data,dict): raise ValueError('Rules must be an object.')
    rules={**DEFAULT_RULES,'groups':[g['id'] for g in game.groups],**data}
    bounds={'budget':(24,5000),'depth':(1,8),'beam':(1,32),'seed':(0,2147483647),
            'max_start_delay':(0,120),'max_delay':(0,120),'max_frames':(1,960),'tail':(10,600),'stock_cap':(0,99)}
    for key,(low,high) in bounds.items():
        if type(rules[key]) is not int or not low<=rules[key]<=high:
            raise ValueError(f'{key} must be an integer between {low} and {high}.')
    if rules['resources'] not in ('state','cap'): raise ValueError('Unknown resource rule.')
    if rules['policy'] not in ('heuristic','random','laya'): raise ValueError('Unknown search policy.')
    if type(rules['true_combo']) is not bool: raise ValueError('True-combo rule must be a boolean.')
    if not isinstance(rules['delays'],list) or not 1<=len(rules['delays'])<=32 or any(type(n) is not int or not 0<=n<=60 for n in rules['delays']):
        raise ValueError('Delays must contain 1-32 frame counts between 0 and 60.')
    rules['delays']=sorted(set(rules['delays']))
    allowed={g['id'] for g in game.groups}
    if not isinstance(rules['groups'],list) or any(not isinstance(g,str) for g in rules['groups']) or not set(rules['groups'])<=allowed:
        raise ValueError('Select at least one supported input group.')
    rules['custom_moves']=validate_custom_moves(rules['custom_moves'])
    if type(rules['auto_timing']) is not bool: raise ValueError('Automatic timing must be a boolean.')
    disabled=rules['disabled_actions']
    names={a.name for a in game.actions([g['id'] for g in game.groups])}
    if not isinstance(disabled,list) or any(not isinstance(n,str) or n not in names for n in disabled):
        raise ValueError('Unknown disabled move.')
    if not game.search_actions(rules): raise ValueError('Enable at least one built-in or custom move.')
    if hasattr(game,'validate_rules'): game.validate_rules(rules)
    return {k:rules[k] for k in DEFAULT_RULES}


def atomic_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,indent=2),encoding='utf-8')
    os.replace(temp,path)


def read_json(path,default=None):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError): return default


class Dashboard:
    def __init__(self,root=ROOT):
        self.root=Path(root)
        self.data=self.root/'artifacts/dashboard'
        self.config=read_json(self.data/'config.json',{}) or {}
        from .game_profile import ConfiguredGame
        profile_file=self.data/'game-profiles.json'
        self.game_definitions=json.loads(profile_file.read_text(encoding='utf-8')) if profile_file.exists() else {}
        if not isinstance(self.game_definitions,dict): raise ValueError('Invalid saved game profiles.')
        for game_id,definition in self.game_definitions.items():
            game=ConfiguredGame(definition)
            if game.id!=game_id: raise ValueError('Saved game profile ID mismatch.')
            GAMES[game.id]=game
        self.token=secrets.token_urlsafe(32)
        self.lock=threading.RLock()
        self.job={'stage':'idle','message':'Prepare a session to get started.','completed':0}
        self.process=None
        self.owned_emulators=[]

    def profile(self,game_id):
        game=get_game(game_id)
        default_exe=Path('G:/Games/Fightcade/emulator/fbneo/fcadefbneo.exe')
        default_state=Path('G:/Games/Fightcade/emulator/fbneo/savestates/vsavj slot 01.fs')
        value={ 'emulator':str(default_exe) if default_exe.exists() else '',
                 'snapshot':str(default_state) if game.id=='vampire-savior' and default_state.exists() else '',
                 'rules':{**DEFAULT_RULES,'groups':[g['id'] for g in game.groups],
                          'true_combo':getattr(game,'definition',{}).get('combo_validated',True)},**self.config.get(game.id,{})}

        if hasattr(game,'definition'):
            rules={**value['rules']}
            rules['groups']=[g for g in rules.get('groups',[]) if g=='configured'] or ['configured']
            names={a.name for a in game.actions(['configured'])}
            rules['disabled_actions']=[n for n in rules.get('disabled_actions',[]) if n in names]
            if not game.definition['combo_validated']: rules['true_combo']=False
            if 'stocks' not in game.definition['players']['p1']: rules['resources']='state'
            value['rules']=rules
        return value

    def save_game_profile(self,data):
        from .game_profile import ConfiguredGame
        with self.lock:
            self.idle()
            game=ConfiguredGame(data.get('definition'))
            original=data.get('original_id')
            if original is None:
                if game.id in GAMES: raise ValueError('This game ID already exists. Choose a unique ID or edit that game.')
            else:
                if original!=game.id: raise ValueError('An existing game ID cannot be changed.')
                previous=get_game(original)
                if not hasattr(previous,'definition'): raise ValueError('Built-in games cannot be edited with this wizard.')
                if data.get('original_sha256')!=previous.profile_sha256:
                    raise ValueError('This profile changed elsewhere. Close the wizard and reopen Edit game setup.')
            definitions={**self.game_definitions,game.id:game.definition}
            atomic_json(self.data/'game-profiles.json',definitions)
            self.game_definitions=definitions
            GAMES[game.id]=game
            return {'game':game.id,'profile_sha256':game.profile_sha256}

    def idle(self):
        if self.job['stage'] in BUSY: raise ValueError('A job is active. Stop it or wait for it to finish first.')

    def session(self,game_id):
        value=self.profile(game_id).get('session')
        if not value: raise ValueError('Prepare a session first.')
        path=Path(value).resolve()
        if not path.is_relative_to((self.data/'sessions').resolve()): raise ValueError('Invalid session directory.')
        expected=getattr(get_game(game_id),'profile_sha256',None)
        if expected and read_json(path/'session.json',{}).get('profile_sha256')!=expected:
            raise ValueError('Game profile changed. Prepare a new session.')
        return path

    def connection(self,game_id):
        try:
            session=self.session(game_id)
            heartbeat=read_json(session/'bridge/heartbeat.json',{}) or {}
            ready=read_json(session/'bridge/ready.json',{}) or {}
            age=time.time()-heartbeat.get('time',0)
            connected=0<=age<6 and ready.get('rom')==get_game(game_id).rom
            expected=getattr(get_game(game_id),'profile_sha256',None)
            if expected: connected=connected and ready.get('profile_sha256')==expected
            return {'connected':connected,'prepared':True,'label':'Runner connected' if connected else 'Waiting for runner',
                    'script':str(session/'connect.lua'),'pending':(session/'bridge/request.tsv').exists(),
                    'snapshot_sha256':read_json(session/'session.json',{}).get('snapshot_sha256'),
                    'snapshot_hashes':[s['snapshot_sha256'] for s in read_json(session/'session.json',{}).get('snapshots',[])] or [read_json(session/'session.json',{}).get('snapshot_sha256')]}
        except ValueError:
            return {'connected':False,'prepared':False,'label':'No session prepared','script':'','pending':False}

    def result_files(self):
        files={}
        folder=self.data/'runs'
        if folder.exists():
            files.update({p.stem:p for p in folder.glob('*.json')})
        for p in (self.root/'artifacts').glob('search-*.json'):
            files['legacy-'+p.stem]=p
        return files

    def history(self):
        library=read_json(self.data/'result-library.json',{}) or {}
        items=[]
        for id,path in self.result_files().items():
            flags=library.get(id,{})
            if flags.get('hidden'): continue
            data=read_json(path,{}) or {}
            result=data.get('result',data)
            if not result.get('best'): continue
            best=result['best']
            items.append({'id':id,'favorite':bool(flags.get('favorite')),'game':result.get('game','vampire-savior'),'created':path.stat().st_mtime,
                'snapshot_source':result.get('snapshot_source',''),'damage':best.get('damage',0),'notation':best.get('notation',best.get('label','Saved route')),
                'verified':best.get('verified',False),'failed_validation':best.get('reproduced') is False,'policy':result.get('rules',{}).get('policy',result.get('policy','heuristic')),
                'evaluated':result.get('evaluated',0),'snapshot_sha256':best.get('snapshot_sha256',result.get('snapshot_sha256'))})
        return sorted(items,key=lambda r:r['created'],reverse=True)

    def favorite(self, data):
        with self.lock:
            id=data.get('id'); enabled=data.get('favorite')
            if not isinstance(id,str) or id not in self.result_files(): raise ValueError('Result not found.')
            if type(enabled) is not bool: raise ValueError('Favorite must be a boolean.')
            library=read_json(self.data/'result-library.json',{}) or {}
            flags=library.setdefault(id,{})
            flags.update(favorite=enabled,hidden=False)
            atomic_json(self.data/'result-library.json',library)
            return {'favorite':enabled}

    def clear_results(self, data):
        with self.lock:
            game=get_game(data.get('game'))
            library=read_json(self.data/'result-library.json',{}) or {}
            ids=[r['id'] for r in self.history() if r['game']==game.id and not r['favorite']]
            for id in ids: library.setdefault(id,{})['hidden']=True
            atomic_json(self.data/'result-library.json',library)
            return {'cleared':ids,'message':f'Cleared {len(ids)} results. Favorites kept.'}

    def restore_results(self, data):
        with self.lock:
            ids=data.get('ids')
            if not isinstance(ids,list) or any(not isinstance(id,str) for id in ids): raise ValueError('Invalid result list.')
            library=read_json(self.data/'result-library.json',{}) or {}
            files=self.result_files()
            for id in ids:
                if id in files: library.setdefault(id,{})['hidden']=False
            atomic_json(self.data/'result-library.json',library)
            return {'message':'Results restored.'}

    def status(self):
        with self.lock:
            return {'games':[g.public() for g in GAMES.values()],
                    'game_definitions':{g.id:{'definition':g.definition,'sha256':g.profile_sha256} for g in GAMES.values() if hasattr(g,'definition')},
                    'profiles':{g:self.profile(g) for g in GAMES},
                    'connections':{g:self.connection(g) for g in GAMES},'job':dict(self.job),'history':self.history(),
                    'model_available':(self.root/'models/laya/combochan-model.json').exists()}

    def save(self,data):
        with self.lock:
            self.idle()
            game=get_game(data.get('game'))
            profile=self.profile(game.id)
            for key in ('emulator','snapshot'):
                value=data.get(key,profile[key])
                if not isinstance(value,str) or len(value)>2048 or '\x00' in value: raise ValueError('Invalid path.')
                profile[key]=value.strip().strip('"')
            snapshots=data.get('snapshots', [profile['snapshot']] if 'snapshot' in data else profile.get('snapshots',[profile['snapshot']]))
            if not isinstance(snapshots,list) or not 1<=len(snapshots)<=100 or any(not isinstance(p,str) or not p.strip().strip(chr(34)) or len(p)>2048 or '\x00' in p for p in snapshots):
                raise ValueError('Provide 1-100 save-state paths.')
            profile['snapshots']=[p.strip().strip(chr(34)) for p in snapshots]
            profile['snapshot']=profile['snapshots'][0]
            profile['rules']=validate_rules(data.get('rules',profile['rules']),game)
            old=self.profile(game.id)
            if profile['emulator']!=old['emulator'] or profile['snapshots']!=old.get('snapshots',[old['snapshot']]):
                profile.pop('session',None)
            self.config[game.id]=profile
            atomic_json(self.data/'config.json',self.config)
            return profile

    def prepare(self,data):
        with self.lock:
            profile=self.save(data)
            game=get_game(data['game'])
            exe=Path(profile['emulator']); snapshot=Path(profile['snapshot'])
            if not exe.is_file() or exe.name.lower() not in game.executable_names:
                raise ValueError('Select the Fightcade fcadefbneo.exe executable.')
            for source in profile['snapshots']:
                state=Path(source)
                if not state.is_file() or state.suffix.lower() not in game.state_extensions: raise ValueError('Select an existing .fs save state: '+source)
                if state.stat().st_size>64*1024*1024: raise ValueError('Save state exceeds the supported 64 MB limit: '+source)
            session=self.data/'sessions'/uuid.uuid4().hex
            (session/'bridge').mkdir(parents=True)
            snapshots=[]
            for index,source in enumerate(profile['snapshots']):
                filename='root.fs' if index==0 else f'state_{index+1}.fs'
                target=session/'bridge'/filename
                shutil.copy2(source,target)
                snapshots.append({'file':filename,'source':source,'snapshot_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
            digest=snapshots[0]['snapshot_sha256']
            # JSON quoting with ASCII paths is valid Lua; use decimal escapes for non-ASCII UTF-8.
            def lua_string(value):
                return '"'+''.join(chr(b) if 32<=b<127 and b not in (34,92) else '\\%03d'%b for b in value.encode('utf-8'))+'"'
            script='COMBOCHAN_BRIDGE_DIR = '+lua_string((session/'bridge').as_posix()+'/')+'\n'
            if hasattr(game,'session_script'):
                script+=game.session_script()
                atomic_json(session/'game-profile.json',game.definition)
            else: script+='COMBOCHAN_GAME = nil\n'
            script+='return assert(loadfile('+lua_string((self.root/game.runner_path).as_posix())+'))()\n'
            (session/'connect.lua').write_text(script,encoding='ascii')
            atomic_json(session/'session.json',{'game':game.id,'source':str(snapshot),'snapshot_sha256':digest,'snapshots':snapshots,'created':time.time(),'profile_sha256':getattr(game,'profile_sha256',None)})
            profile['session']=str(session)
            self.config[game.id]=profile
            atomic_json(self.data/'config.json',self.config)
            return {'script':str(session/'connect.lua'),'snapshot_sha256':digest}

    def launch(self,game_id):
        with self.lock:
            self.idle()
            game=get_game(game_id); session=self.session(game_id)
            exe=Path(self.profile(game_id)['emulator'])
            if not exe.is_file() or exe.name.lower() not in game.executable_names: raise ValueError('Emulator path is invalid.')
            if self.connection(game_id)['connected']: raise ValueError('The runner is already connected.')
            self.owned_emulators=[p for p in self.owned_emulators if p.poll() is None]
            if self.owned_emulators: raise ValueError('The dashboard already opened an emulator. Load the session script there or close it before launching another.')
            process=subprocess.Popen(game.launch_arguments(exe,session/'connect.lua'),cwd=exe.parent)
            self.owned_emulators.append(process)
            return {'message':'Emulator launched. If it does not connect, load the prepared Lua script using the instructions below.'}

    def start(self,data):
        with self.lock:
            self.idle()
            game=get_game(data['game']); session=self.session(game.id)
            if not self.connection(game.id)['connected']: raise ValueError('Connect and unpause the prepared Lua runner first.')
            if (session/'bridge/request.tsv').exists() or (session/'bridge/client.lock').exists():
                raise ValueError('This session has an unfinished request. Let it finish or prepare a new session.')
            action=data.get('action','search')
            if action not in ('search','check','replay'): raise ValueError('Unknown action.')
            rules=validate_rules(data.get('rules',self.profile(game.id)['rules']),game)
            if action=='search' and rules['policy']=='laya' and not (self.root/'models/laya/combochan-model.json').exists():
                raise ValueError('Laya weights are not installed. Use the CLI model-download command or select another policy.')
            run_id=uuid.uuid4().hex
            config={'game':game.id,'session':str(session),'rules':rules,'action':action,'model':str(self.root/'models/laya')}
            prepared=read_json(session/'session.json',{})
            config['snapshots']=prepared.get('snapshots',[{'file':'root.fs','source':prepared.get('source',''),'snapshot_sha256':prepared['snapshot_sha256']}])
            if hasattr(game,'definition'): config['game_profile']=game.definition
            if action=='replay':
                path=self.result_files().get(data.get('result_id'))
                if path is None: raise ValueError('Result not found.')
                result=read_json(path,{})
                result=result.get('result',result)
                if result.get('game',game.id)!=game.id: raise ValueError('Result belongs to another game.')
                config['replay']=result['best']
                if getattr(game,'profile_sha256',None)!=config['replay'].get('profile_sha256'):
                    raise ValueError('Replay requires the original game profile.')
                matching=next((s for s in config['snapshots'] if s['snapshot_sha256']==config['replay']['snapshot_sha256']),None)
                if matching is None: raise ValueError('Prepare the original save state before replaying this result.')
                config['snapshot_file']=matching['file']
            (session/'cancel.flag').unlink(missing_ok=True)
            task_path=session/(run_id+'.job.json')
            atomic_json(task_path,config)
            self.job={'id':run_id,'game':game.id,'stage':'starting','message':'Starting '+action+'...','completed':0,
                      'budget':rules['budget'],'started':time.time(),'logs':[],'session':str(session)}
            flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
            self.process=subprocess.Popen([sys.executable,'-u','-m','combochan.dashboard_worker',str(task_path)],
                cwd=self.root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
                creationflags=flags,env={**os.environ,'PYTHONUTF8':'1'})
            threading.Thread(target=self.watch,args=(self.process,run_id),daemon=True).start()
            return {'id':run_id}

    def watch(self,process,run_id):
        terminal=None
        for line in process.stdout:
            with self.lock:
                if self.job.get('id')!=run_id: return
                try: event=json.loads(line)
                except ValueError:
                    self.job['logs']=(self.job['logs']+[line.strip()[:500]])[-30:]; continue
                if self.job.get('stage')=='stopping' and event.get('stage') in BUSY: event.pop('stage',None)
                if event.get('stage') in ('complete','failed','cancelled'):
                    terminal=event.pop('stage')
                self.job.update(event)
                if 'result' in event:
                    result_id=run_id+(f"-{event['queue_index']}" if 'queue_index' in event else '')
                    atomic_json(self.data/'runs'/(result_id+'.json'),{'id':result_id,'created':time.time(),'result':event['result']})
                    self.job.pop('result',None)
        code=process.wait()
        with self.lock:
            if self.job.get('id')==run_id:
                if terminal and (code==0 or terminal=='failed'): self.job['stage']=terminal
                else: self.job.update(stage='failed',message=f'Worker exited before finishing (code {code}). Check the run log.')

    def stop(self):
        with self.lock:
            if self.job['stage'] not in BUSY: return {'message':'No active job.'}
            (Path(self.job['session'])/'cancel.flag').write_text('stop',encoding='ascii')
            self.job.update(stage='stopping',message='Stopping after the active batch; remaining queued states will not run. Keep the emulator running until it finishes.')
            return {'message':self.job['message']}


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self,address,app):
        self.app=app
        super().__init__(address,Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def valid_host(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
    def send(self,data,status=200,kind='application/json'):
        content=json.dumps(data).encode('utf-8') if kind=='application/json' else data
        self.send_response(status)
        self.send_header('Content-Type',kind+'; charset=utf-8')
        self.send_header('Content-Length',str(len(content)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers(); self.wfile.write(content)
    def do_GET(self):
        if not self.valid_host(): return self.send({'error':'Invalid host'},403)
        path=urlparse(self.path).path
        if path=='/api/state': return self.send(self.server.app.status())
        if path=='/api/game-profile-template':
            from .game_profile import template
            return self.send(template())
        if path=='/api/bootstrap': return self.send({'token':self.server.app.token})
        if path.startswith('/api/export/'):
            result=self.server.app.result_files().get(path.rsplit('/',1)[-1])
            if result is None: return self.send({'error':'Result not found'},404)
            return self.send(read_json(result,{}))
        names={'/':'index.html','/app.js':'app.js','/game-wizard.js':'game-wizard.js','/style.css':'style.css'}
        if path not in names: return self.send({'error':'Not found'},404)
        file=Path(__file__).with_name('web')/names[path]
        kind={'html':'text/html','js':'application/javascript','css':'text/css'}[file.suffix[1:]]
        self.send(file.read_bytes(),kind=kind)
    def do_POST(self):
        if not self.valid_host() or not secrets.compare_digest(self.headers.get('X-ComboChan-Token',''),self.server.app.token):
            return self.send({'error':'Refresh the dashboard to reconnect.'},403)
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            return self.send({'error':'Invalid origin'},403)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=65536: raise ValueError('Invalid request size.')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('Expected an object.')
            app=self.server.app
            path=urlparse(self.path).path
            if path=='/api/save': result=app.save(data)
            elif path=='/api/game-profiles/save': result=app.save_game_profile(data)
            elif path=='/api/game-profiles/validate':
                from .game_profile import ConfiguredGame
                game=ConfiguredGame(data.get('definition'))
                result={'valid':True,'profile_sha256':game.profile_sha256}
            elif path=='/api/prepare': result=app.prepare(data)
            elif path=='/api/launch': result=app.launch(data['game'])
            elif path=='/api/start': result=app.start(data)
            elif path=='/api/stop': result=app.stop()
            elif path=='/api/results/favorite': result=app.favorite(data)
            elif path=='/api/results/clear': result=app.clear_results(data)
            elif path=='/api/results/restore': result=app.restore_results(data)
            elif path=='/api/pick':
                if data.get('kind') not in ('emulator','snapshot','snapshots'): raise ValueError('Unknown file kind.')
                try:
                    response=subprocess.run([sys.executable,'-m','combochan.file_picker',data['kind']],cwd=app.root,
                                            capture_output=True,text=True,encoding='utf-8',timeout=120,
                                            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
                                            env={**os.environ,'PYTHONUTF8':'1'})
                    if response.returncode: raise ValueError('The native file picker is unavailable. Paste the full file path instead.')
                    result=json.loads(response.stdout)
                except subprocess.TimeoutExpired: raise ValueError('File selection timed out. Paste the full path or try again.')
            else: return self.send({'error':'Not found'},404)
            return self.send(result)
        except (ValueError,KeyError,OSError,TypeError) as exc:
            return self.send({'error':str(exc)},400)


def main():
    parser=argparse.ArgumentParser(description='ComboChan local dashboard')
    parser.add_argument('--port',type=int,default=8790)
    parser.add_argument('--open',action='store_true')
    parser.add_argument('--game-profile',type=Path,action='append',default=[],help='Load a custom FBNeo JSON profile; repeat for multiple games.')
    args=parser.parse_args()
    from .game_profile import ConfiguredGame
    try:
        for path in args.game_profile:
            game=ConfiguredGame(json.loads(path.read_text(encoding='utf-8')))
            if game.id in GAMES: raise ValueError('Duplicate game id: '+game.id)
            GAMES[game.id]=game
    except (OSError,ValueError) as exc: parser.error(str(exc))
    try: server=Server(('127.0.0.1',args.port),Dashboard())
    except (OSError,ValueError) as exc: raise SystemExit(f'Cannot start dashboard: {exc}. Try --port 8791.')
    url=f'http://127.0.0.1:{server.server_port}'
    print('ComboChan dashboard: '+url,flush=True)
    if args.open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()


if __name__=='__main__': main()
