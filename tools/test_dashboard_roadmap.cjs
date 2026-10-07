// Isolated API/browser regression; emulator processes below are test doubles.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const python=process.env.PYTHON||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const code=`
import tempfile
from pathlib import Path
from combochan.dashboard import Dashboard, Server, atomic_json
class FakeEmulator:
    exited=False
    def poll(self): return 0 if self.exited else None
    def close_gracefully(self): self.exited=True; return 1
    def terminate(self): self.exited=True
with tempfile.TemporaryDirectory() as tmp:
    app=Dashboard(Path(tmp))
    session=app.data/'sessions'/'fake'
    atomic_json(session/'session.json',{'game':'marvel-vs-capcom-2'})
    process=FakeEmulator(); app.owned_emulators=[process]; app.emulator_sessions[str(session)]=process
    server=Server(('127.0.0.1',0),app)
    print(server.server_port,flush=True)
    server.serve_forever()
`;
(async()=>{
 const child=spawn(python,['-u','-c',code],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser,page;
 try {
  const port=await new Promise((resolve,reject)=>{
   child.stdout.once('data',data=>resolve(Number(data.toString().trim())));
   child.once('error',reject);child.once('exit',code=>reject(Error(`Fixture server exited: ${code}`)));
   child.stderr.on('data',data=>process.stderr.write(data));
  });
  const url=`http://127.0.0.1:${port}`;
  await new Promise((resolve,reject)=>{
   const test=spawn(process.execPath,[path.join(root,'tools/test_dashboard_starters.cjs'),url],{cwd:root,windowsHide:true,stdio:'inherit'});
   test.on('error',reject);test.on('exit',code=>code===0?resolve():reject(Error('Starter browser regression failed')));
  });
  browser=await chromium.launch({channel:'chrome',headless:true});page=await browser.newPage();
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const select=async()=>{await page.locator('[data-game="marvel-vs-capcom-2"]').click();};
  const save=async()=>{await page.locator('#save').click();await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');};
  await page.goto(url);await select();await page.locator('#reset-rules').click();
  assert.equal(await page.locator('[data-group="tags"]').isChecked(),false);
  await page.locator('#special-notation').fill('41236K');await page.locator('#add-special').click();
  await page.locator('[data-group="tags"]').check();await page.locator('#starter').fill('Tag 1 > 41236LK');
  await page.locator('#depth').fill('64');await page.locator('#learn-timing').uncheck();await page.locator('#checkpoints').uncheck();
  await save();await page.reload();await select();
  assert.equal(await page.locator('[data-group="tags"]').isChecked(),true);
  assert.equal(await page.locator('#starter').inputValue(),'Tag 1 > 41236LK');
  assert.equal(await page.locator('#depth').inputValue(),'64');
  assert.equal(await page.locator('#learn-timing').isChecked(),false);
  assert.equal(await page.locator('#checkpoints').isChecked(),false);
  assert.equal(await page.locator('#close-emulators').isEnabled(),true);
  let busy=true;
  await page.route('**/api/state',async route=>{
   const response=await route.fetch(),state=await response.json();
   if(busy)state.job={stage:'searching',message:'Fixture search',completed:0};
   await route.fulfill({json:state});
  });
  await page.evaluate(()=>refresh());assert.equal(await page.locator('#close-emulators').isDisabled(),true);
  assert.match(await page.locator('#emulator-status').innerText(),/current batch/);
  busy=false;await page.evaluate(()=>refresh());
  await page.locator('#close-emulators').click();
  await page.waitForFunction(()=>document.querySelector('#close-emulators').disabled);
  assert.match(await page.locator('#notice-text').innerText(),/1 emulator.*0 are still running/);
  await page.locator('#reset-rules').click();assert.equal(await page.locator('[data-group="tags"]').isChecked(),false);
  await save();await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: optional tags, saved long routes and timing controls, close API with fake owned process, busy guard, mobile layout.');
 } finally {
  if(page)await page.unrouteAll({behavior:'ignoreErrors'});
  if(browser)await browser.close();child.kill();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
