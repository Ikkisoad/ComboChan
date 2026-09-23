const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage(); const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let bootstrap=0, rejected=0;
 page.on('response',r=>{if(r.url().endsWith('/api/save')&&r.status()===403)rejected++});
 await page.route('**/api/bootstrap',async route=>{if(bootstrap++===0)await route.fulfill({json:{token:'stale-token-from-before-server-restart'}});else await route.continue()});
 await page.goto('http://127.0.0.1:8790');
 await page.waitForFunction(()=>document.querySelectorAll('[data-group]').length===3);
 const original=await page.locator('#budget').inputValue();
 try {
 await page.locator('#budget').fill(original==='42'?'43':'42');const edited=await page.locator('#budget').inputValue();
 await page.locator('#save').click();
 await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');
 await page.reload();await page.waitForFunction(()=>document.querySelectorAll('[data-group]').length===3);
 if(await page.locator('#budget').inputValue()!==edited)throw Error('Saved budget did not survive reload');
 if(rejected!==1)throw Error('Did not exercise stale token recovery');
 const disabled=await page.locator('#start').isDisabled();const reason=await page.locator('#start-reason').innerText();
 if(disabled&&!reason.length)throw Error('Disabled search lacks explanation');
 if(await page.locator('#connection-help-button').isVisible()) {await page.locator('#connection-help-button').click();if(!await page.locator('#connect-help').evaluate(el=>el.open))throw Error('Connection guidance did not open')}
 console.log(JSON.stringify({savedAfterTokenRefresh:true,persistedAfterReload:true,searchDisabled:disabled,reason,errors}));
 if(errors.length)throw Error(errors.join('\n'));
 } finally {
 await page.locator('#budget').fill(original);await page.locator('#save').click();
 await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
