'use strict';
(() => {
  const steps=['Game details','Controls','Memory values','Moves','Review'];
  const codes=['U','D','L','R','LP','MP','HP','LK','MK','HK'];
  const fields={health:['Health','u16','Required. Raw health that decreases when damage is taken.'],x:['Horizontal position','s16','Required. Increases toward screen right; used for forward/back.'],stun1:['Hitstun','u8','Required. Zero outside hitstun, nonzero while unable to recover.'],stun2:['Second hitstun signal','u8','Optional additional hitstun flag.'],stocks:['Meter stocks','u8','Required for P1 if you want a stock-spending cap.'],meter:['Meter gauge','u16','Optional raw meter gauge.'],combo_hits:['Hits received','u8','Optional counter that increases for each hit in a connected combo.'],recoverable:['Second health pool','u16','Optional second health pool, not damage.'],y:['Vertical position','s16','Optional vertical position.'],facing:['Facing value','u8','Optional facing value; directions use horizontal positions.'],state:['State value','u16','Optional animation/state value, for inspection.']};
  let definition, original=null, originalHash=null, step=0, saving=false, storageOK=true;
  const dialog=$('game-wizard'), content=$('wizard-content');
  const key=()=>`combochan.game-wizard.${original||'new'}`;
  function number(value) {return value.trim()===''?null:Number(value)}
  function field(parent,id,label,value,help='',type='text') {
    const wrap=el('div',undefined,'field'), caption=el('label',label), input=el('input');
    caption.htmlFor=id;input.id=id;input.type=type;input.value=value??'';input.autocomplete='off';
    wrap.append(caption,input);if(help)wrap.append(el('small',help));parent.append(wrap);return input;
  }
  function heading(title,description) {content.append(el('h3',title),el('p',description,'muted'));}
  function fail(message) {$('wizard-error').textContent=message;$('wizard-error').hidden=false;$('wizard-error').focus();}
  function collect() {
    if(step===0) {definition.title=$('wg-title').value.trim();definition.id=$('wg-id').value.trim();definition.rom=$('wg-rom').value.trim();definition.health_max=number($('wg-health').value);}
    if(step===1) {definition.inputs={};for(const code of codes)if($(`wg-${code}-on`).checked)definition.inputs[code]={p1:$(`wg-${code}-p1`).value.trim(),p2:$(`wg-${code}-p2`).value.trim()};}
    if(step===2) {definition.players={p1:{},p2:{}};for(const player of ['p1','p2'])for(const name of Object.keys(fields)) {
      const prefix=`wg-${player}-${name}`,address=$(prefix+'-address').value.trim();
      if(address || ['health','x','stun1'].includes(name)) {
        const spec={address:/^\d+$/.test(address)?Number(address):address||null,type:$(prefix+'-type').value};
        for(const option of ['mask','equals']) {const value=$(prefix+'-'+option).value.trim();if(value)spec[option]=number(value);}
        definition.players[player][name]=spec;
      }
    }}
    if(step===3) definition.moves=[...content.querySelectorAll('.wizard-move')].map(row=>({name:row.querySelector('[data-wname]').value.trim(),sequence:row.querySelector('[data-wsequence]').value.trim()}));
    if(step===4) definition.combo_validated=$('wg-calibrated').checked;
  }
  function saveDraft() {
    try {localStorage.setItem(key(),JSON.stringify({definition,step,originalHash}));storageOK=true;} catch {storageOK=false;}
    $('wizard-draft-note').textContent=storageOK?'Draft saved in this browser. Close and reopen to continue.':'Browser draft storage is unavailable. Keep this window open until you save.';
  }
  function collectDraft() {collect();saveDraft();}
  function controls() {
    heading('Map the emulator controls','Use the exact names shown by FBNeo joypad.get(). Directions are required. Enable only the attack aliases your game uses. F/B are calculated automatically.');
    for(const code of codes) {
      const row=el('div',undefined,'wizard-controls'), toggle=el('label',undefined,'group-option'), check=el('input');check.type='checkbox';check.id=`wg-${code}-on`;check.checked=!!definition.inputs[code];check.disabled=['U','D','L','R'].includes(code);toggle.append(check,document.createTextNode(code));row.append(toggle);
      for(const player of ['p1','p2']) {const input=field(row,`wg-${code}-${player}`,`${player.toUpperCase()} ${code}`,definition.inputs[code]?.[player]||'', '', 'text');input.placeholder=`${player.toUpperCase()} exact input name`;input.disabled=!check.checked;}
      check.addEventListener('change',()=>{for(const player of ['p1','p2'])$(`wg-${code}-${player}`).disabled=!check.checked;collectDraft()});content.append(row);
    }
  }
  function telemetryRow(parent,player,name) {
    const [label,type,help]=fields[name],spec=definition.players[player][name]||{},prefix=`wg-${player}-${name}`;
    const row=el('fieldset',undefined,'wizard-memory');row.append(el('legend',label),el('p',help,'small muted'));
    const grid=el('div',undefined,'wizard-memory-grid');const address=field(grid,prefix+'-address','Memory address',spec.address===undefined||spec.address===null?'':typeof spec.address==='number'?'0x'+spec.address.toString(16):spec.address);address.placeholder='0x… or decimal';
    const wrap=el('div',undefined,'field'),caption=el('label','Read type'),select=el('select');caption.htmlFor=prefix+'-type';select.id=prefix+'-type';for(const [value,label] of [['u8','Byte (u8)'],['u16','Word (u16)'],['s16','Signed word (s16)']]){const option=el('option',label);option.value=value;select.append(option)}select.value=spec.type||type;wrap.append(caption,select);grid.append(wrap);
    field(grid,prefix+'-mask','Bit mask (optional)',spec.mask??'','Decimal or 0x hex.');field(grid,prefix+'-equals','Equals (optional)',spec.equals??'','Outputs 1 when equal; otherwise 0.');row.append(grid);parent.append(row);
  }
  function memory() {
    heading('Tell the runner what to measure','Enter absolute addresses from your game’s memory map or emulator debugger. The wizard cannot discover them. Check values while idle, moving, taking damage and recovering. A nonzero animation ID is not necessarily hitstun.');
    for(const player of ['p1','p2']) {
      content.append(el('h4',player==='p1'?'Player 1 — attacker':'Player 2 — defender'));
      for(const name of ['health','x','stun1'])telemetryRow(content,player,name);
      const details=el('details',undefined,'wizard-optional');details.append(el('summary','Optional signals: stocks, combo counter and more'));
      for(const name of Object.keys(fields).filter(n=>!['health','x','stun1'].includes(n)))telemetryRow(details,player,name);content.append(details);
    }
  }
  function addMove(move={name:'',sequence:''}) {
    const row=el('div',undefined,'wizard-move'),id='wm-'+crypto.randomUUID();
    const name=field(row,id+'-name','Move name',move.name),sequence=field(row,id+'-sequence','Input sequence',move.sequence);name.dataset.wname='';sequence.dataset.wsequence='';sequence.placeholder='D:2, D+F:2, F+LP';
    const remove=el('button','Remove','text-button');remove.type='button';remove.setAttribute('aria-label','Remove move');remove.addEventListener('click',()=>{row.remove();definition.combo_validated=false;collectDraft()});row.append(remove);$('wizard-moves').append(row);
  }
  function review() {
    heading('Review and save','Your game will appear in the sidebar immediately. Then choose an emulator and save states, prepare a session, connect the runner, and check restoration.');
    const list=el('dl',undefined,'wizard-review');for(const [label,value] of [['Game',definition.title],['ROM',definition.rom],['Maximum health',definition.health_max],['Controls',Object.keys(definition.inputs).join(', ')],['Mapped signals',Object.entries(definition.players).map(([p,f])=>`${p.toUpperCase()}: ${Object.keys(f).join(', ')}`).join(' · ')],['Moves',definition.moves.map(m=>m.name).join(', ')]]){list.append(el('dt',label),el('dd',String(value)))}content.append(list);
    const label=el('label',undefined,'group-option'),check=el('input');check.type='checkbox';check.id='wg-calibrated';check.checked=definition.combo_validated;label.append(check,document.createTextNode('I have calibrated hitstun, known connected/disconnected sequences, and guard/jump escape controls for these mappings.'));content.append(label,el('p','Leave this unchecked for a new game. You can search damage strings now and return through Edit game setup after calibration to enable true-combo checks.','small muted'));
    if(original)content.append(el('p','Changed mappings require preparing a new session. Existing results remain saved and require their original profile for replay.','small muted'));
  }
  function renderStep() {
    content.replaceChildren();$('wizard-error').hidden=true;
    $('wizard-title').textContent=original?'Edit game setup':'Add your game';
    $('wizard-steps').replaceChildren(...steps.map((name,index)=>{const item=el('li',`${index+1}. ${name}`);if(index===step)item.setAttribute('aria-current','step');return item}));
    $('wizard-position').textContent=`Step ${step+1} of ${steps.length}`;$('wizard-back').disabled=step===0;$('wizard-next').textContent=step===4?'Save game':'Continue';
    if(step===0) {
      heading('Start with the game','This setup supports compatible two-player games in Fightcade FBNeo with .fs save states. Other emulator backends need an adapter.');
      field(content,'wg-title','Game name',definition.title);
      field(content,'wg-id','Unique game ID',definition.id,'Lowercase letters, numbers, hyphens or underscores.').disabled=!!original;
      field(content,'wg-rom','ROM name',definition.rom,'Exact value returned by emu.romname().');
      const health=field(content,'wg-health','Maximum raw health',definition.health_max,'The largest valid health value, not the displayed percentage.','number');health.min=1;health.max=65535;
    } else if(step===1)controls();else if(step===2)memory();else if(step===3) {
      heading('Define the moves to search','Use mapped attack aliases plus U/D/L/R/F/B. Commas separate steps, + holds buttons together, :frames sets duration, and N releases all buttons. Example: LP, N, LP. Each move allows 64 steps and 240 frames.');
      content.append(el('p','Mapped attacks: '+Object.keys(definition.inputs).filter(c=>!['U','D','L','R'].includes(c)).join(', '),'small muted'));
      const rows=el('div');rows.id='wizard-moves';content.append(rows);definition.moves.forEach(addMove);
      const add=el('button','Add move','secondary');add.type='button';add.id='wizard-add-move';add.addEventListener('click',()=>{addMove();collectDraft();$('wizard-moves').lastElementChild.querySelector('input').focus()});content.append(add);
    } else review();
    dialog.scrollTop=0;saveDraft();content.querySelector('input:not(:disabled),select')?.focus();
  }
  function validateStep() {
    if(step===0) {
      if(!definition.title || definition.title.length>80)throw Error('Enter a game name with 1–80 characters.');
      for(const field of ['id','rom'])if(!/^[a-z0-9][a-z0-9_-]{0,63}$/.test(definition[field]))throw Error(`Enter a valid ${field==='id'?'game ID':'ROM name'} using lowercase letters, numbers, underscores or hyphens.`);
      if(!original && state.games.some(g=>g.id===definition.id))throw Error('This game ID already exists. Choose another ID.');
      if(!Number.isInteger(definition.health_max)||definition.health_max<1||definition.health_max>65535)throw Error('Maximum health must be an integer between 1 and 65535.');
    }
    if(step===1) {const names=[];for(const [code,mapping] of Object.entries(definition.inputs))for(const [player,name] of Object.entries(mapping)){if(!name||name.length>100)throw Error(`Enter the exact ${player.toUpperCase()} name for ${code}.`);names.push(name)}if(new Set(names).size!==names.length)throw Error('Each control must have a unique emulator input name.');}
    if(step===2)for(const player of ['p1','p2'])for(const [name,spec] of Object.entries(definition.players[player])) {
      const value=typeof spec.address==='number'?spec.address:/^(0x[0-9a-f]+|\d+)$/i.test(spec.address||'')?Number(spec.address):NaN;
      if(!Number.isInteger(value)||value<0||value>0xfffffffe)throw Error(`Enter a valid address for ${player.toUpperCase()} ${fields[name][0]}.`);
      for(const option of ['mask','equals'])if(option in spec&&(!Number.isInteger(spec[option])||spec[option]<0||spec[option]>65535))throw Error(`${player.toUpperCase()} ${fields[name][0]} ${option} must be an integer from 0 to 65535.`);
    }
  }
  async function openWizard(edit=false) {
    if(!state||saving)return;
    if(busyStages.has(state.job.stage)){notice('Wait for the active job to finish before editing game setup.');return;}
    if(dirty){if(!confirm('Discard unsaved search settings and open game setup?'))return;chooseGame(currentGame);}
    original=edit?currentGame:null;originalHash=edit?state.game_definitions[original].sha256:null;
    try {
      definition=edit?structuredClone(state.game_definitions[original].definition):await api('/api/game-profile-template');
      if(!edit){definition.id='';definition.title='';definition.rom='';}
      step=0;
      try {const draft=JSON.parse(localStorage.getItem(key())||'null');if(draft&&draft.originalHash===originalHash&&draft.definition&&Number.isInteger(draft.step)&&draft.step>=0&&draft.step<5){definition=draft.definition;step=draft.step;}}catch{}
      dialog.showModal();renderStep();
    } catch(error){notice(error.message);}
  }
  content.addEventListener('input',()=>{if(step<4)definition.combo_validated=false;collectDraft()});
  $('wizard-back').addEventListener('click',()=>{collectDraft();step--;renderStep()});
  $('wizard-close').addEventListener('click',()=>{if(!saving){collectDraft();dialog.close()}});
  dialog.addEventListener('cancel',event=>{if(saving)event.preventDefault();else collectDraft()});
  $('wizard-form').addEventListener('submit',async event=>{
    event.preventDefault();if(saving)return;
    try {
      collectDraft();validateStep();saving=true;
      for(const id of ['wizard-next','wizard-back','wizard-close'])$(id).disabled=true;
      if(step>=3)await api('/api/game-profiles/validate',{definition});
      if(step<4){step++;renderStep();return;}
      const result=await api('/api/game-profiles/save',{definition,original_id:original,original_sha256:originalHash});
      try{localStorage.removeItem(key())}catch{}
      dialog.close();await refresh();chooseGame(result.game);
      notice('Game saved. Select your emulator and save states, then prepare a session and check restoration.',true);
      $('setup-title').scrollIntoView({behavior:'smooth',block:'start'});$('emulator').focus();
    }catch(error){fail(error.message)}finally{saving=false;$('wizard-next').disabled=false;$('wizard-back').disabled=step===0;$('wizard-close').disabled=false;}
  });
  $('future-game').addEventListener('click',()=>openWizard());
  $('edit-game-profile').addEventListener('click',()=>openWizard(true));
})();
