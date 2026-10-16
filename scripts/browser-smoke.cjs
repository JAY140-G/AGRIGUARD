/* Optional: PLAYWRIGHT_MODULE=/path/to/playwright node scripts/browser-smoke.cjs */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||'playwright');
const crypto=require('node:crypto');
const fs=require('node:fs');
async function main(){
 const browser=await chromium.launch({executablePath:process.env.CHROMIUM_PATH||'/usr/bin/chromium',headless:true,args:['--no-sandbox','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const context=await browser.newContext({viewport:{width:1440,height:1050}});
 await context.addInitScript(()=>localStorage.setItem('agriscan-map-style','offline'));
 const page=await context.newPage();const errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 page.on('console',m=>{if(m.text().startsWith('Map error:'))errors.push(m.text())});
 fs.mkdirSync('.data/screenshots',{recursive:true});
 try{
  await page.goto(process.env.APP_URL||'http://127.0.0.1:8080');
  await page.getByRole('button',{name:'Create an account',exact:true}).click();
  await page.getByLabel('Email address').fill(`browser-${crypto.randomUUID()}@test.example`);
  await page.getByLabel('Password',{exact:true}).fill(crypto.randomBytes(20).toString('hex'));
  await page.getByRole('button',{name:'Create account',exact:true}).click();
  await page.getByRole('heading',{name:'Your fields, in focus.'}).waitFor();
  await page.getByRole('button',{name:'Add farm',exact:true}).click();
  await page.getByLabel('Farm name').fill('Browser test field');
  await page.getByRole('button',{name:'Draw boundary',exact:true}).click();
  const bounds=await page.locator('.map-canvas').boundingBox();
  for(const [x,y] of [[.25,.3],[.6,.3],[.6,.7],[.25,.7]])await page.mouse.click(bounds.x+bounds.width*x,bounds.y+bounds.height*y);
  await page.getByRole('button',{name:'Finish polygon',exact:true}).click();
  await page.locator('.vertex-marker').first().waitFor();
  await page.getByRole('button',{name:'Use sample field in Jaipur',exact:true}).click();
  await page.getByRole('button',{name:'Save farm',exact:true}).click();
  await page.getByRole('heading',{name:'Your farms',exact:true}).waitFor();
  await page.getByRole('button',{name:'Dashboard',exact:true}).click();
  await page.screenshot({path:'.data/screenshots/dashboard.png',fullPage:true});
  await page.getByRole('button',{name:'Mission planner',exact:true}).click();
  await page.getByLabel('Altitude (m)',{exact:true}).fill('120');
  await page.getByLabel('Front overlap (%)',{exact:true}).fill('0');
  await page.getByLabel('Side overlap (%)',{exact:true}).fill('0');
  await page.getByRole('button',{name:'Generate survey',exact:true}).click();
  await page.getByRole('button',{name:'Run simulation',exact:true}).waitFor();
  await page.waitForFunction(()=>Number(document.querySelector('.map-canvas')?.dataset.routeFeatures)>0);
  await page.screenshot({path:'.data/screenshots/planner.png',fullPage:true});
  await page.getByRole('button',{name:'Run simulation',exact:true}).click();
  await page.getByRole('button',{name:'Pause',exact:true}).click();
  await page.locator('.flight-status .state-badge.paused').waitFor();
  await page.getByRole('button',{name:'Resume',exact:true}).click();
  await page.locator('.flight-status .state-badge.completed').waitFor({timeout:60000});
  await page.getByRole('button',{name:'Review captured images',exact:true}).click();
  await page.locator('.photo-card').first().waitFor();
  await page.locator('.photo-card').first().click();
  await page.getByRole('heading',{name:'Image details',exact:true}).waitFor();
  await page.getByRole('button',{name:'Needs inspection',exact:true}).click();
  await page.locator('.feedback-buttons button.primary').waitFor();
  await page.screenshot({path:'.data/screenshots/image-detail.png',fullPage:true});
  await page.getByRole('button',{name:'Close image details',exact:true}).click();
  const farms=await (await context.request.get((process.env.APP_URL||'http://127.0.0.1:8080')+'/api/farms')).json();
  // Use absolute URLs for RequestContext compatibility across Playwright versions.
  const base=process.env.APP_URL||'http://127.0.0.1:8080';
  for(const kind of ['csv','geojson']){
   const r=await context.request.get(`${base}/api/farms/${farms[0].id}/export/${kind}`);
   if(!r.ok())throw new Error(`Export ${kind}: ${r.status()}`);
   if(kind==='csv'&&!(await r.text()).includes('Simulated analysis'))throw new Error('Missing demo label in CSV');
   if(kind==='geojson'&&(await r.json()).type!=='FeatureCollection')throw new Error('Invalid GeoJSON');
  }
  await page.screenshot({path:'.data/screenshots/results.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:'.data/screenshots/mobile.png',fullPage:true});
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  if(overflow)throw new Error('Mobile page overflows horizontally');
  if(errors.length)throw new Error('Browser errors: '+errors.join('; '));
  console.log('PASS: registration → farm → plan → pause/resume → completed simulation → review/feedback → CSV/GeoJSON; mobile layout.');
 }catch(e){await page.screenshot({path:'.data/screenshots/failure.png',fullPage:true});throw e}finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exit(1)});
