const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8790');await page.waitForFunction(()=>document.querySelectorAll('#results tr').length>0);
 const rows=page.locator('#results tr');const latest=await rows.nth(0).innerText();const second=await rows.nth(1).innerText();
 if(!latest.includes('Failed validation')||!second.includes('Failed validation'))throw Error('Latest failed routes were not labeled correctly');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('PASS: both latest results show Failed validation; no browser errors');await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
