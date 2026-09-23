const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8790');await page.waitForFunction(()=>document.querySelectorAll('[data-move]').length>0);
 const state=await (await page.request.get('http://127.0.0.1:8790/api/state')).json();const original=state.profiles['vampire-savior'];
 try {
 await page.getByText('Configure available moves',{exact:false}).click();
 await page.locator('#add-lilith').click();await page.locator('[data-move="LP"]').uncheck();
 await page.locator('#save').click();await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');
 await page.reload();await page.waitForFunction(()=>document.querySelectorAll('[data-move]').length>0);
 if(await page.locator('[data-move="LP"]').isChecked())throw Error('Move exclusion not saved');
 if(!await page.locator('[data-sequence]').last().inputValue().then(v=>v==='LP, N, LP, F, LK, HP'))throw Error('Demon sequence not saved');
 if(!await page.locator('#auto-timing').isChecked())throw Error('Automatic timing not default');
 await page.setViewportSize({width:390,height:844});
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Mobile overflow');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS: custom move persistence, built-in exclusion, timing controls, mobile layout, no JS errors');
 }finally {
 const token=(await(await page.request.get('http://127.0.0.1:8790/api/bootstrap')).json()).token;
 const response=await page.request.post('http://127.0.0.1:8790/api/save',{headers:{'X-ComboChan-Token':token},data:{game:'vampire-savior',...original}});
 if(!response.ok())throw Error('Could not restore original settings');await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
