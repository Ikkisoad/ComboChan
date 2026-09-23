const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8790');await page.waitForFunction(()=>document.querySelectorAll('[data-move]').length>0);
 const original=await page.locator('#max-start-delay').inputValue();
 try {
 if(original!=='0')throw Error('Initial delay should default to zero for existing profile');
 await page.locator('#max-start-delay').fill('5');await page.locator('#save').click();
 await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');
 await page.reload();await page.waitForFunction(()=>document.querySelectorAll('[data-move]').length>0);
 if(await page.locator('#max-start-delay').inputValue()!=='5')throw Error('Initial budget did not persist');
 if(await page.locator('#max-delay').inputValue()!=='60')throw Error('Inter-move budget unexpectedly changed');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS: default zero, save/reload five frames, independent continuation timing, no browser errors');
 }finally{
 await page.locator('#max-start-delay').fill(original);await page.locator('#save').click();
 await page.waitForFunction(()=>document.querySelector('#save-state').textContent==='Saved on this computer');await browser.close();
 }
})().catch(e=>{console.error(e);process.exit(1)});
