// Uses a temporary dashboard profile and fixture files; never launches an emulator.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('node:child_process');
const path=require('node:path');
const assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..');
const python=process.env.PYTHON||path.join(root,'.venv',process.platform==='win32'?'Scripts/python.exe':'bin/python');
const code=`
import tempfile
from pathlib import Path
from combochan.dashboard import Dashboard, Server
with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp)
    exe=root/'fcadefbneo.exe'; exe.write_bytes(b'fixture')
    state=root/'test.fs'; state.write_bytes(b'fixture')
    app=Dashboard(root)
    app.save({'game':'vampire-savior','emulator':str(exe),'snapshot':str(state)})
    server=Server(('127.0.0.1',0),app)
    print(server.server_port,flush=True)
    server.serve_forever()
`;
(async()=>{
 const child=spawn(python,['-u','-c',code],{cwd:root,windowsHide:true,env:{...process.env,PYTHONUTF8:'1'}});
 let browser;
 try {
  const port=await new Promise((resolve,reject)=>{
   child.stdout.once('data',data=>resolve(Number(data.toString().trim())));
   child.once('error',reject);child.once('exit',code=>reject(Error(`Fixture server exited: ${code}`)));
   child.stderr.on('data',data=>process.stderr.write(data));
  });
  browser=await chromium.launch({channel:'chrome',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:1050}});
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(`http://127.0.0.1:${port}`);
  await page.waitForFunction(()=>document.querySelectorAll('[data-move]').length>0);
  assert.equal(await page.locator('#instance-count').inputValue(),'1');
  await page.locator('#instance-count').fill('3');
  await page.locator('#save').click();
  await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');
  await page.reload();
  await page.waitForFunction(()=>document.querySelector('#instance-count').value==='3');
  await page.locator('#prepare').click();
  await page.waitForFunction(()=>document.querySelectorAll('#script-instance option').length===3);
  assert.match(await page.locator('#connection').innerText(),/0\/3 runners connected/);
  assert.equal(await page.locator('#launch').isEnabled(),true);
  assert.match(await page.locator('#launch').innerText(),/Launch emulators/);
  const first=await page.locator('#script-path').inputValue();
  await page.locator('#script-instance').selectOption('1');
  const second=await page.locator('#script-path').inputValue();
  assert.notEqual(first,second);assert.match(second,/instance-2/);
  await page.locator('#instance-count').fill('2');
  assert.equal(await page.locator('#launch').isDisabled(),true);
  assert.match(await page.locator('#start-reason').innerText(),/count or paths changed/);
  await page.locator('#instance-count').fill('17');
  await page.locator('#save').click();
  await page.waitForFunction(()=>document.querySelector('#notice-text').textContent.includes('between 1 and 16'));
  await page.locator('#instance-count').fill('3');
  await page.route('**/api/state',async route=>{
   const response=await route.fetch();const state=await response.json();
   state.job={stage:'searching',message:'Fixture search',game:'vampire-savior',completed:0};
   await route.fulfill({json:state});
  });
  await page.waitForFunction(()=>document.querySelector('#instance-count').disabled);
  await page.unroute('**/api/state');
  await page.waitForFunction(()=>!document.querySelector('#instance-count').disabled);
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.locator('#instance-count').isVisible(),true);
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  assert.deepEqual(errors,[]);
  console.log('PASS: count persists, session preparation creates three scripts, count changes require preparation, invalid counts rejected, active searches lock count, mobile layout fits.');
 } finally {
  if(browser)await browser.close();
  child.kill();
 }
})().catch(error=>{console.error(error);process.exitCode=1;});
