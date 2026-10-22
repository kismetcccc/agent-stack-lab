// Static preview only: real backend absent/unknown is NOT full-chain evidence.
import {chromium} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
const destination = process.env.UI_SCREENSHOT_DIR || '../../test-results/ui-preview';
const base = process.env.UI_PREVIEW_URL || 'http://localhost:4173';
await mkdir(destination, {recursive:true});
const browser = await chromium.launch({chromiumSandbox:true});
try {
  for (const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]) {
    const context = await browser.newContext({viewport, deviceScaleFactor:1});
    const page = await context.newPage();
    await page.goto(base, {waitUntil:'networkidle'});
    await page.getByRole('main').waitFor();
    await page.evaluate(()=>document.fonts.ready);
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.waitForTimeout(100);
    await page.screenshot({path:`${destination}/${name}-architecture.png`,fullPage:true});
    console.log(name, await page.evaluate(()=>({viewport:innerWidth,scrollWidth:document.documentElement.scrollWidth})));
    await page.getByRole('button',{name:/MySQL/}).first().click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.waitForTimeout(100);
    await page.screenshot({path:`${destination}/${name}-mysql-detail.png`,fullPage:true});
    await page.getByRole('tab',{name:/查询与结果/}).click();
    await page.getByRole('link',{name:'Redis',exact:true}).click();
    await page.evaluate(()=>window.scrollTo(0,0));
    await page.waitForTimeout(100);
    await page.screenshot({path:`${destination}/${name}-query-redis.png`,fullPage:true});
    await context.close();
  }
} finally { await browser.close(); }
