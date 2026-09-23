'use strict';
const $ = id => document.getElementById(id);
const busyStages = new Set(['starting','checking','model','searching','validating','replaying','stopping']);
let token = '', currentGame = '', state = null, dirty = false, pending = false, initialized = false, offline = false;
let resultTab='all', clearedResults=[];
const defaults = {resources:'state',stock_cap:0,true_combo:true,policy:'heuristic',budget:600,depth:5,beam:8,seed:0,delays:[0,2,4,6,8,12,16],max_frames:180,tail:90,groups:['normals','motions','movement'],custom_moves:[],disabled_actions:[],auto_timing:true,max_delay:60,max_start_delay:0};
const fieldMap = {'stock_cap':'stock-cap','true_combo':'true-combo','max_frames':'max-frames','auto_timing':'auto-timing','max_delay':'max-delay','max_start_delay':'max-start-delay'};
function notice(message, success=false) { $('notice-text').textContent=message; $('notice').hidden=false; $('notice').classList.toggle('success',success); }
function hideNotice() { $('notice').hidden=true; }
async function api(path, data, retry=true) {
  const response=await fetch(path, data===undefined ? {} : {method:'POST',headers:{'Content-Type':'application/json','X-ComboChan-Token':token},body:JSON.stringify(data)});
  const result=await response.json();
  if(response.status===403 && data!==undefined && retry) {
    token=(await api('/api/bootstrap')).token;
    return api(path,data,false);
  }
  if(!response.ok) throw new Error(result.error || `Request failed (${response.status})`);
  return result;
}
function el(tag,text,className) { const node=document.createElement(tag); if(text!==undefined) node.textContent=text; if(className) node.className=className; return node; }
function markDirty() { dirty=true; $('save-state').textContent='Unsaved changes'; renderControls(); }
function loadRules(rules) {
  for (const [key,value] of Object.entries(rules)) {
    if(key==='custom_moves') { renderCustomMoves(value); continue; }
    if(key==='disabled_actions') { document.querySelectorAll('[data-move]').forEach(input=>input.checked=!value.includes(input.dataset.move)); continue; }
    if(key==='groups') { document.querySelectorAll('[data-group]').forEach(input=>input.checked=value.includes(input.dataset.group)); continue; }
    const input=$(fieldMap[key] || key); if(!input) continue;
    if(input.type==='checkbox') input.checked=value; else input.value=Array.isArray(value)?value.join(', '):value;
  }
  $('cap-field').hidden=$('resources').value!=='cap';
}
function readRules() {
  const result={};
  for(const key of Object.keys(defaults)) {
    if(key==='custom_moves') result.custom_moves=[...document.querySelectorAll('.custom-move')].map(row=>({name:row.querySelector('[data-name]').value,sequence:row.querySelector('[data-sequence]').value,enabled:row.querySelector('[data-enabled]').checked}));
    else if(key==='disabled_actions') result.disabled_actions=[...document.querySelectorAll('[data-move]:not(:checked)')].map(input=>input.dataset.move);
    else if(key==='groups') result.groups=[...document.querySelectorAll('[data-group]:checked')].map(input=>input.dataset.group);
    else if(key==='delays') {
      const text=$('delays').value.trim();
      if(!text || text.split(',').some(value=>!/^\d+$/.test(value.trim()))) throw new Error('Enter comma-separated whole frame counts for delays.');
      result.delays=text.split(',').map(Number);
    } else {
      const input=$(fieldMap[key]||key);
      if(input.type==='checkbox') result[key]=input.checked;
      else if(input.type==='number') { if(input.value==='' || !input.checkValidity()) throw new Error(`Check ${input.previousElementSibling.textContent.toLowerCase()}.`); result[key]=Number(input.value); }
      else result[key]=input.value;
    }
  }
  if(!result.groups.length && !result.custom_moves.some(move=>move.enabled)) throw new Error('Enable at least one input group or custom move.');
  return result;
}
function setupData() { return {game:currentGame,emulator:$('emulator').value,snapshot:$('snapshot').value,rules:readRules()}; }
function changedPaths() { const profile=state?.profiles[currentGame]; return !profile || $('emulator').value.trim()!==profile.emulator || $('snapshot').value.trim()!==profile.snapshot; }
function chooseGame(id) {
  currentGame=id;
  const game=state.games.find(game=>game.id===id), profile=state.profiles[id];
  $('breadcrumb-game').textContent=game.title; $('game-title').replaceChildren(document.createTextNode(game.title),el('span','.','title-dot'));
  $('rom-label').textContent=game.rom.toUpperCase(); $('emulator-label').textContent=game.emulator;
  $('emulator').value=profile.emulator; $('snapshot').value=profile.snapshot;
  $('capability-note').textContent=game.limits;
  $('input-groups').replaceChildren(...game.groups.map(group=>{
    const label=el('label',undefined,'group-option'), input=el('input'); input.type='checkbox'; input.dataset.group=group.id;
    input.addEventListener('change',markDirty); label.append(input,document.createTextNode(group.label)); return label;
  }));
  $('built-in-moves').replaceChildren(...(game.moves||[]).map(move=>{
    const label=el('label',undefined,'group-option'),input=el('input');input.type='checkbox';input.dataset.move=move.name;input.dataset.moveGroup=move.group;
    input.addEventListener('change',markDirty);label.append(input,document.createTextNode(move.name));return label;
  }));
  loadRules({...defaults,...profile.rules}); dirty=false; $('save-state').textContent='Settings saved locally';
  document.querySelectorAll('[data-game]').forEach(button=>button.classList.toggle('active',button.dataset.game===id));
  render();
}
function renderControls() {
  if(!state || !currentGame) return;
  const connection=state.connections[currentGame], busy=busyStages.has(state.job.stage), pathsChanged=changedPaths();
  const blocked=offline||pending||busy;
  for(const id of ['prepare','save','reset-rules','add-move','add-lilith']) $(id).disabled=blocked;
  document.querySelectorAll('[data-pick]').forEach(b=>b.disabled=blocked);
  $('launch').disabled=blocked||!connection.prepared||connection.connected||pathsChanged;
  const reason=offline?'Dashboard is offline. Restart Start Dashboard.cmd, then refresh this page.':pending?'Please wait for the current request to finish.':busy?'An experiment is active. Wait for it to finish or stop it first.':pathsChanged?'Emulator or save-state paths changed. Click Prepare session to connect this setup.':!connection.prepared?'Select an emulator and save state, then click Prepare session.':!connection.connected?'The session runner is not responding. Launch the emulator or load the prepared script, then unpause the game, close menus, and disable Misc → Options → Auto pause.':connection.pending?'The runner has an unfinished request. Let it finish; if it was interrupted, prepare a new session.':'';
  $('start').disabled=Boolean(reason);
  $('start').title=reason||'Start a search with the current rules';
  $('start-reason').textContent=reason||'Runner connected. Ready to search with the current rules.';
  $('connection-help-button').hidden=connection.connected||!connection.prepared||busy;
  $('check').disabled=blocked||!connection.connected||connection.pending||pathsChanged;
  $('stop').disabled=!busy||state.job.stage==='stopping'||pending;
  $('copy-script').disabled=!connection.script;
  $('emulator').disabled=busy; $('snapshot').disabled=busy;
  document.querySelectorAll('.rules-panel input,.rules-panel select,[data-remove-move]').forEach(input=>input.disabled=busy);
  $('cap-field').hidden=$('resources').value!=='cap';
}
function renderHistory() {
  const all=state.history.filter(r=>r.game===currentGame), favorites=all.filter(r=>r.favorite);
  const history=resultTab==='favorites'?favorites:all;
  $('all-results-count').textContent=all.length;$('favorites-count').textContent=favorites.length;
  for(const [id,active] of [['all-results-tab',resultTab==='all'],['favorites-tab',resultTab==='favorites']]) {
    $(id).setAttribute('aria-selected',String(active));$(id).tabIndex=active?0:-1;
  }
  $('result-list').setAttribute('aria-labelledby',resultTab==='favorites'?'favorites-tab':'all-results-tab');
  $('clear-results').hidden=resultTab==='favorites';
  $('clear-results').disabled=pending||offline||!all.some(r=>!r.favorite);
  $('undo-clear-results').hidden=!clearedResults.length;$('undo-clear-results').disabled=pending||offline;
  $('results-library-note').textContent=resultTab==='favorites'?'Your starred routes stay here when you clear saved results.':'Clear results removes non-favorites from this list. Favorites are kept.';
  $('empty-results-title').textContent=resultTab==='favorites'?'No favorites yet.':'No saved results.';
  $('empty-results-message').textContent=resultTab==='favorites'?'Star a saved result to keep it in this list.':'Completed searches appear here. Favorites are preserved when clearing results.';
  $('result-count').textContent=history.length; $('empty-results').hidden=history.length>0;
  $('results').replaceChildren(...history.map(result=>{
    const row=el('tr'), name=el('td'), route=el('div',result.notation.replace(/^root\s*>\s*/,''),'route-name');
    const date=new Date(result.created*1000).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
    name.append(route,el('div',`${date} · ${result.evaluated} trials`,'route-meta'));
    const damage=el('td',String(result.damage),'damage-cell'), policy=el('td',result.policy==='laya'?'Laya':result.policy==='random'?'Random':'Heuristic');
    const validation=el('td'); validation.title=result.failed_validation?'The route failed repeatability or defensive replay checks. It is not a verified combo.':''; validation.append(el('span',result.verified?'✓ Verified combo':result.failed_validation?'Failed validation':'Unverified',result.verified?'verified':'candidate'));
    const action=el('td'), buttons=el('div',undefined,'result-actions'), replay=el('button','Replay ↗'); replay.type='button';
    const connection=state.connections[currentGame];
    replay.disabled=pending||busyStages.has(state.job.stage)||!connection.connected||result.snapshot_sha256!==connection.snapshot_sha256;
    replay.title=result.snapshot_sha256!==connection.snapshot_sha256?'Prepare this result’s original save state to replay.':'Replay at normal speed';
    replay.addEventListener('click',()=>perform(async()=>{await api('/api/start',{game:currentGame,action:'replay',result_id:result.id,rules:readRules()});}));
    const download=el('a','Export'); download.href='/api/export/'+encodeURIComponent(result.id); download.download='combochan-'+result.id+'.json';
    const favorite=el('button',result.favorite?'★ Favorited':'☆ Favorite','favorite-button');favorite.type='button';
    favorite.setAttribute('aria-pressed',String(Boolean(result.favorite)));favorite.setAttribute('aria-label',(result.favorite?'Remove from favorites: ':'Add to favorites: ')+result.notation);
    favorite.disabled=pending||offline;favorite.addEventListener('click',()=>perform(async()=>{await api('/api/results/favorite',{id:result.id,favorite:!result.favorite})}));
    buttons.append(favorite,replay,download); action.append(buttons); row.append(name,damage,policy,validation,action); return row;
  }));
}
function render() {
  if(!state || !currentGame) return;
  const connection=state.connections[currentGame], job=state.job, busy=busyStages.has(job.stage);
  $('connection').replaceChildren(el('i'),document.createTextNode(connection.label)); $('connection').classList.toggle('online',connection.connected);
  $('setup-state').textContent=connection.connected?'Session ready':connection.prepared?'Session prepared':'Setup required';
  $('script-path').value=connection.script||'';
  $('model-note').textContent=state.model_available?'Local Laya weights installed. Game outcomes decide the result.':'Laya weights not installed. Heuristic and random search are ready to use.';
  const layaOption=$('policy').querySelector('[value="laya"]'); layaOption.disabled=!state.model_available;
  const titles={idle:'Find your next route.',starting:'Setting things up.',checking:'Same state. Every time.',model:'Laya is thinking.',searching:'Exploring possibilities.',validating:'Put it to the test.',replaying:'Watch it connect.',complete:'Experiment complete.',failed:'Let’s get back on track.',cancelled:'Experiment stopped.',stopping:'Finishing this batch.'};
  $('run-stage').textContent=job.stage==='idle'?'READY WHEN YOU ARE':job.stage.toUpperCase();
  $('run-heading').textContent=titles[job.stage]||job.stage;
  $('run-message').textContent=job.stage==='idle'?(connection.connected?'Runner connected. Start a search or check restoration first.':connection.prepared?'Load your prepared session script to connect the runner.':'Prepare a session to get started.'):job.message;
  const history=state.history.filter(r=>r.game===currentGame);
  $('best-damage').textContent=job.damage ?? (history.length?Math.max(...history.map(r=>r.damage)):'—');
  $('trial-count').textContent=job.completed || '—';
  $('progress').max=job.budget||600; $('progress').value=job.completed||0;
  $('progress-text').textContent=job.completed?`${job.completed} / ${job.budget||600} trials${job.depth?' · depth '+job.depth:''}`:busy?'Preparing experiment':'No active search';
  const seconds=busy && job.started?Math.floor(Date.now()/1000-job.started):Math.floor(job.elapsed||0);
  $('elapsed').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');
  $('run-pulse').classList.toggle('active',busy);
  $('current-route').hidden=!job.notation; $('current-route').textContent=job.notation||'';
  $('run-log').textContent=(job.logs||[]).join('\n')||job.message||'No events yet.';
  renderControls(); renderHistory();
}
async function refresh() { state=await api('/api/state'); offline=false; if(!initialized) {
  initialized=true; $('game-count').textContent=String(state.games.length).padStart(2,'0');
  $('games').replaceChildren(...state.games.map(game=>{const button=el('button',undefined,'game-tab'); button.dataset.game=game.id; button.type='button'; button.append(el('span',game.badge||game.title.slice(0,2),'game-icon'),el('span',game.title),el('span','›','chevron')); button.addEventListener('click',()=>{if(dirty && !confirm('Discard unsaved settings and switch games?'))return;chooseGame(game.id)}); return button;}));
  chooseGame(state.games[0].id);
} else render(); }
async function perform(callback) { if(pending)return; pending=true;hideNotice();renderControls();try { await callback(); await refresh(); } catch(error) { notice(error.message); } finally {pending=false;renderControls();if(state)renderHistory();} }
function renderCustomMoves(moves) {
  $('custom-moves').replaceChildren();
  moves.forEach(addCustomMove);
}
function addCustomMove(move={name:'New move',sequence:'LP',enabled:true}) {
  const row=el('div',undefined,'custom-move');
  const enabled=el('input');enabled.type='checkbox';enabled.dataset.enabled='';enabled.checked=move.enabled;enabled.setAttribute('aria-label','Enable custom move');
  const name=el('input');name.dataset.name='';name.value=move.name;name.placeholder='Move name';name.setAttribute('aria-label','Move name');
  const sequence=el('input');sequence.dataset.sequence='';sequence.value=move.sequence;sequence.placeholder='LP, N, LP, F, LK, HP';sequence.setAttribute('aria-label','Move input sequence');
  const remove=el('button','Remove','text-button');remove.type='button';remove.dataset.removeMove='';remove.addEventListener('click',()=>{row.remove();markDirty()});
  [enabled,name,sequence].forEach(input=>input.addEventListener('input',markDirty));
  row.append(enabled,name,sequence,remove);$('custom-moves').append(row);
}
$('add-move').addEventListener('click',()=>{addCustomMove();markDirty()});
$('add-lilith').addEventListener('click',()=>{
  const names=[...document.querySelectorAll('[data-name]')].map(input=>input.value);
  let name='Lilith demon';let suffix=2;while(names.includes(name))name='Lilith demon '+suffix++;
  addCustomMove({name,sequence:'LP, N, LP, F, LK, HP',enabled:true});markDirty();
});
function chooseResultTab(tab,focus=false){resultTab=tab;renderHistory();if(focus)$(tab==='favorites'?'favorites-tab':'all-results-tab').focus()}
$('all-results-tab').addEventListener('click',()=>chooseResultTab('all'));
$('favorites-tab').addEventListener('click',()=>chooseResultTab('favorites'));
for(const id of ['all-results-tab','favorites-tab']) $(id).addEventListener('keydown',event=>{
  if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) {event.preventDefault();chooseResultTab(event.key==='Home'?'all':event.key==='End'?'favorites':resultTab==='all'?'favorites':'all',true)}
});
$('clear-results').addEventListener('click',()=>perform(async()=>{const result=await api('/api/results/clear',{game:currentGame});clearedResults=result.cleared;notice(result.message,true)}));
$('undo-clear-results').addEventListener('click',()=>perform(async()=>{await api('/api/results/restore',{ids:clearedResults});clearedResults=[];notice('Results restored.',true)}));
$('dismiss-notice').addEventListener('click',hideNotice);
$('resources').addEventListener('change',()=>{$('cap-field').hidden=$('resources').value!=='cap'});
document.querySelectorAll('.rules-panel input,.rules-panel select,#emulator,#snapshot').forEach(input=>input.addEventListener('input',markDirty));
$('reset-rules').addEventListener('click',()=>{loadRules(defaults);markDirty()});
$('save').addEventListener('click',()=>perform(async()=>{
  $('save-state').textContent='Saving…';
  try {
    const saved=await api('/api/save',setupData());
    state.profiles[currentGame]=saved;
    dirty=false;$('save-state').textContent='Saved on this computer';notice('Settings saved.',true);
  } catch(error) { $('save-state').textContent='Not saved: '+error.message; throw error; }
}));
$('connection-help-button').addEventListener('click',()=>{$('connect-help').open=true;$('connect-help').scrollIntoView({behavior:'smooth',block:'center'})});
$('prepare').addEventListener('click',()=>perform(async()=>{await api('/api/prepare',setupData());dirty=false;$('save-state').textContent='Settings saved locally';$('connect-help').open=true;notice('Session prepared. Launch the emulator or load the generated script in your existing window.',true)}));
$('launch').addEventListener('click',()=>perform(async()=>{const result=await api('/api/launch',{game:currentGame});notice(result.message,true)}));
$('start').addEventListener('click',()=>perform(async()=>{await api('/api/start',{game:currentGame,action:'search',rules:readRules()})}));
$('check').addEventListener('click',()=>perform(async()=>{await api('/api/start',{game:currentGame,action:'check',rules:readRules()})}));
$('stop').addEventListener('click',()=>perform(async()=>{await api('/api/stop',{})}));
document.querySelectorAll('[data-pick]').forEach(button=>button.addEventListener('click',()=>perform(async()=>{const result=await api('/api/pick',{kind:button.dataset.pick});if(result.path){$(button.dataset.pick).value=result.path;markDirty()}})));
$('copy-script').addEventListener('click',async()=>{try {await navigator.clipboard.writeText($('script-path').value);notice('Session script path copied.',true)}catch{$('script-path').select();notice('Select and copy the script path from the field.')}});
$('future-game').addEventListener('click',()=>$('future-dialog').showModal());
$('close-future').addEventListener('click',()=>$('future-dialog').close());$('future-ok').addEventListener('click',()=>$('future-dialog').close());
async function boot(){try{token=(await api('/api/bootstrap')).token;await refresh()}catch(error){notice('Dashboard connection failed: '+error.message)}}
boot();setInterval(async()=>{try{if(!pending)await refresh()}catch{offline=true;$('connection').textContent='Dashboard offline';renderControls();}},1800);
