// Run against an isolated Dashboard with a temporary data directory.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const assert=require('node:assert/strict');
(async()=>{
 const url=process.argv[2];assert.ok(url,'Pass the isolated dashboard URL');
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],searches=[];
  let busy=false,legacy=false;
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/state',async route=>{
   const response=await route.fetch(),state=await response.json();
   for(const connection of Object.values(state.connections))Object.assign(connection,{prepared:true,connected:true,pending:false});
   if(busy)state.job={stage:'searching',queue_index:2,queue_total:4,starter:'c.HP',snapshot_source:'second.fs',message:'Testing.',completed:12,budget:24};
   if(legacy){delete state.profiles['vampire-savior'].rules.starters;state.profiles['vampire-savior'].rules.starter='c.LK';}
   await route.fulfill({response,json:state});
  });
  await page.route('**/api/start',async route=>{
   searches.push(route.request().postDataJSON());await route.fulfill({json:{id:'browser-test'}});
  });
  const starter=page.locator('#starter');
  const ready=async()=>{await page.waitForFunction(()=>document.querySelectorAll('[data-group]').length>0);};
  const saved=async()=>{await page.locator('#save').click();await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');};
  await page.goto(url);await ready();await page.locator('#reset-rules').click();
  assert.equal(await starter.inputValue(),'');
  await starter.fill('2LK2LK; 2HP');
  await page.locator('#budget').fill('24'); // Unrelated changes must retain the text.
  await saved();await page.reload();await ready();
  assert.equal(await starter.inputValue(),'2LK2LK; 2HP');
  await page.locator('#start').click();await page.waitForFunction(()=>!document.querySelector('#start').disabled);
  assert.deepEqual(searches[0].rules.starters,['2LK2LK','2HP']);assert.equal(searches[0].rules.budget,24);
  await page.locator('#button-controls summary').click();
  await page.locator('[data-search-button="LK"]').uncheck();
  assert.equal(await starter.inputValue(),'2LK2LK; 2HP');
  await page.locator('#save').click();await page.locator('#notice').filter({hasText:'Unknown or disabled move'}).waitFor();
  await page.locator('[data-search-button="LK"]').check();
  await starter.fill('2LK2LK;');
  await page.locator('#save').click();await page.locator('#notice').filter({hasText:'Enter a starter between each semicolon'}).waitFor();
  await starter.fill('2LK2LK');await page.locator('#depth').fill('1');
  await page.locator('#save').click();await page.locator('#notice').filter({hasText:'Increase Maximum actions'}).waitFor();
  await page.locator('#depth').fill('5');
  await page.locator('summary').filter({hasText:'Configure available moves'}).click();
  await page.locator('#add-move').click();
  const row=page.locator('.custom-move').last();
  await row.locator('[data-name]').fill('Opening');await row.locator('[data-sequence]').fill('LP, N, HP');
  await starter.fill('Opening > 2HP; c.LK > c.LK');await saved();
  await page.reload();await ready();assert.equal(await starter.inputValue(),'Opening > 2HP; c.LK > c.LK');
  await starter.fill('');await saved();await page.reload();await ready();assert.equal(await starter.inputValue(),'');
  // Read an old profile without the new field, then save through the real API.
  legacy=true;await page.reload();await ready();assert.equal(await starter.inputValue(),'c.LK');
  await saved();legacy=false;await page.reload();await ready();assert.equal(await starter.inputValue(),'c.LK');
  await starter.fill('c.LK; c.HP');await saved();await page.reload();await ready();assert.equal(await starter.inputValue(),'c.LK; c.HP');
  busy=true;await page.evaluate(()=>refresh());assert.ok(await starter.isDisabled());
  assert.match(await page.locator('#run-message').innerText(),/Run 2 of 4.*starter c.HP/);
  busy=false;await page.evaluate(()=>refresh());
  await page.setViewportSize({width:390,height:844});await starter.fill('2LK2LK; 2HP');await saved();
  assert.ok(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Mobile page overflow');
  await page.locator('[data-game="marvel-vs-capcom-2"]').click();await ready();
  await page.locator('#special-notation').fill('41236K');await page.locator('#add-special').click();
  assert.deepEqual(await page.locator('[data-name]').evaluateAll(inputs=>inputs.map(input=>input.value)),['41236LK','41236HK']);
  await page.locator('#add-special').click();assert.equal(await page.locator('.custom-move').count(),2);
  await starter.fill('2LK > 41236LK');await saved();await page.reload();await ready();
  await page.locator('[data-game="marvel-vs-capcom-2"]').click();await ready();
  assert.equal(await starter.inputValue(),'2LK > 41236LK');
  assert.deepEqual(await page.locator('[data-sequence]').evaluateAll(inputs=>inputs.map(input=>input.value)),['41236LK','41236HK']);
  await page.locator('#available-moves summary').click();
  await page.locator('.custom-move').last().locator('[data-enabled]').uncheck();await saved();
  assert.ok(!await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),'Special move controls overflow');
  assert.deepEqual(errors,[]);
  console.log('PASS: starter strings, real save/reload, search payload, disabled moves, depth validation, custom prefixes, unrestricted reset, legacy settings, busy progress, mobile layout');
 }finally{for(const p of browser.contexts().flatMap(c=>c.pages()))await p.unrouteAll({behavior:'ignoreErrors'});await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
