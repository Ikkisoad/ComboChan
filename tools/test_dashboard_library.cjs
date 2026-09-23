const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const {spawn}=require('child_process');const readline=require('readline');
const fixture=`import tempfile,json,threading,sys
from pathlib import Path
from combochan.dashboard import Dashboard,Server
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);folder=root/'artifacts/dashboard/runs';folder.mkdir(parents=True)
 for i in range(3):(folder/(str(i)+'.json')).write_text(json.dumps({'best':{'notation':'Test route '+str(i),'damage':i+1}}))
 server=Server(('127.0.0.1',0),Dashboard(root))
 def stop():
  sys.stdin.read();server.shutdown()
 threading.Thread(target=stop,daemon=True).start()
 print(server.server_port,flush=True)
 server.serve_forever();server.server_close()
`;
(async()=>{
 const server=spawn(process.env.TEST_PYTHON||'.venv/Scripts/python.exe',['-u','-c',fixture],{stdio:['pipe','pipe','inherit'],windowsHide:true});
 const lines=readline.createInterface({input:server.stdout});
 const port=await new Promise((resolve,reject)=>{lines.once('line',resolve);server.once('error',reject);server.once('exit',code=>reject(Error('Fixture server exited '+code)))});
 let browser;
 try {
 browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:'+port);await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===3);
 await page.locator('.favorite-button').first().click();await page.waitForFunction(()=>document.querySelector('#favorites-count').textContent==='1');
 await page.locator('#favorites-tab').click();if(await page.locator('#results tr').count()!==1)throw Error('Favorite tab did not filter');
 await page.locator('#all-results-tab').click();await page.locator('#clear-results').click();await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===1);
 await page.locator('#undo-clear-results').click();await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===3);
 await page.locator('#clear-results').click();await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===1);
 await page.reload();await page.waitForFunction(()=>document.querySelector('#favorites-count').textContent==='1');
 if(await page.locator('#results tr').count()!==1)throw Error('Clear did not persist');
 await page.locator('#favorites-tab').click();await page.locator('.favorite-button').click();await page.waitForFunction(()=>document.querySelectorAll('#results tr').length===0);
 if(!await page.locator('#empty-results-title').textContent().then(t=>t==='No favorites yet.'))throw Error('Empty state missing');
 await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS: favorite/unfavorite, tabs, clear preserves favorites, undo, reload persistence, mobile layout; disposable data only');
 }finally{if(browser)await browser.close();server.stdin.end();lines.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
