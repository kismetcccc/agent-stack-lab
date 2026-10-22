import {test, expect, type Page} from '@playwright/test';
import {noPageOverflow, password, requireRealBackend, screenshot, submitTopic} from './helpers';

async function register(page: Page) {
  await page.goto('/#lab');
  await page.getByRole('button', {name: '没有帐号？创建帐号'}).click();
  const username = `browser_${Date.now()}_${Math.floor(Math.random()*100000)}`;
  await page.getByLabel('用户名', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '注册并登录', exact: true}).click();
  await expect(page.getByRole('button', {name: '退出登录'})).toBeVisible();
  const cookie = (await page.context().cookies()).find(c => c.name === 'lab_session');
  expect(cookie?.httpOnly).toBe(true);
  return username;
}

async function login(page: Page, username: string) {
  await page.getByLabel('用户名', {exact:true}).fill(username);
  await page.getByLabel('密码', {exact:true}).fill(password);
  await page.getByRole('button', {name:'登录', exact:true}).click();
  await expect(page.getByRole('button', {name:'退出登录'})).toBeVisible();
}

test.describe('real four-store browser chain', () => {
  test.beforeEach(async ({request}) => {await requireRealBackend(request);});

  test('register/login → real events/attempts/result/cache; refresh/history/logout', async ({page}, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    const username = await register(page);
    await page.getByRole('button', {name:'退出登录'}).click();
    await login(page, username);
    const prompt = '解释 MySQL、Kafka、MongoDB 与 Redis 在可靠任务链路中的职责与边界。';
    const taskUrl = await submitTopic(page, prompt);
    await expect(page.getByTestId('task-events')).toContainText('succeeded');
    await expect(page.getByTestId('task-attempts')).toContainText('succeeded');
    await page.getByTestId("task-attempts").locator("summary").click();
    await expect(page.getByTestId('cache-status')).toContainText(/hit|miss/);
    await expect(page.getByTestId('task-detail')).toContainText(/deterministic|确定性/);
    await noPageOverflow(page);
    await screenshot(page, info, 'real-task-result');
    await page.reload();
    await expect(page.getByTestId('report-content')).toContainText(prompt);
    await expect(page.getByTestId('cache-status')).toContainText('hit');
    await page.getByRole('button', {name:'关闭任务详情'}).click();
    await expect(page).not.toHaveURL(/task=/);
    await page.goBack();
    await expect(page).toHaveURL(taskUrl);
    await expect(page.getByTestId('report-content')).toContainText(prompt);
    await page.goForward();
    await expect(page).not.toHaveURL(/task=/);
    await page.goBack();
    await expect(page.getByTestId('report-content')).toContainText(prompt);
    await page.getByRole('button', {name:'退出登录'}).click();
    await expect(page.getByRole('button', {name:'登录', exact:true})).toBeVisible();
    await expect(page.getByTestId('report-content')).toHaveCount(0);
    await expect(page.getByTestId('task-events')).toHaveCount(0);
    let taskReads = 0;
    page.on('request', r => {if(r.url().includes('/api/v1/tasks')) taskReads++;});
    await page.waitForTimeout(4000);
    expect(taskReads).toBe(0);
    await page.goBack();
    await expect(page.getByTestId('report-content')).toHaveCount(0);
    expect(errors).toEqual([]);
  });

  test('synchronous repeated submits create exactly one real task', async ({page}) => {
    await register(page);
    const prompt = '同一个提交事件为什么需要幂等键？';
    await page.getByLabel('研究主题 / 任务要求').fill(prompt);
    let submissions = 0;
    page.on('request', r => {if(r.method()==='POST' && r.url().endsWith('/api/v1/tasks')) submissions++;});
    await page.locator('textarea#prompt').evaluate(el => {
      const form = el.closest('form')!;
      form.requestSubmit(); form.requestSubmit();
    });
    await expect(page.getByTestId('report-content')).toContainText(prompt);
    expect(submissions).toBe(1);
    const list = await page.request.get('/api/v1/tasks');
    expect(list.status()).toBe(200);
    expect((await list.json()).total).toBe(1);
  });

  test('late real response cannot overwrite a newly selected task', async ({page}) => {
    await register(page);
    const firstPrompt = '任务 A：解释事务 Outbox。';
    const secondPrompt = '任务 B：解释 Redis 缓存失效。';
    const firstUrl = await submitTopic(page, firstPrompt);
    const firstId = new URLSearchParams(firstUrl.split('?')[1]).get('task')!;
    const secondUrl = await submitTopic(page, secondPrompt);
    let release!: () => void;
    const gate = new Promise<void>(resolve => {release=resolve;});
    let started!: () => void;
    const observed = new Promise<void>(resolve => {started=resolve;});
    await page.route(`**/api/v1/tasks/${firstId}`, async route => {
      const actualResponse = await route.fetch(); // actual backend response, never fabricated
      started();
      await gate;
      try {await route.fulfill({response:actualResponse});} catch { /* expected if aborted on navigation */ }
    });
    await page.evaluate(url => {location.hash=new URL(url).hash;}, firstUrl);
    await observed;
    await page.evaluate(url => {location.hash=new URL(url).hash;}, secondUrl);
    await expect(page.getByTestId('report-content')).toContainText(secondPrompt);
    release();
    await page.waitForTimeout(300);
    await expect(page.getByTestId('report-content')).toContainText(secondPrompt);
    await expect(page.getByTestId('report-content')).not.toContainText(firstPrompt);
    await page.unroute(`**/api/v1/tasks/${firstId}`);
  });

  test('real 403 and 404 are explained; failed submit can retry', async ({page}) => {
    await register(page);
    await page.route('**/api/v1/tasks', async route => {
      if(route.request().method()==='POST') {
        await route.continue({headers:{...route.request().headers(),'x-csrf-token':'intentionally-invalid'}});
      } else {await route.continue();}
    });
    await page.getByLabel('研究主题 / 任务要求').fill('演示 CSRF 失败后安全重试。');
    const rejected = page.waitForResponse(r => r.url().endsWith('/api/v1/tasks') && r.status()===403);
    await page.getByRole('button', {name:'提交报告任务'}).click();
    await rejected;
    await expect(page.getByRole('alert')).toContainText(/CSRF|权限/);
    await expect(page.getByTestId('report-content')).toHaveCount(0);
    await page.unroute('**/api/v1/tasks');
    await page.getByRole('button', {name:'提交报告任务'}).click();
    await expect(page.getByTestId('report-content')).toContainText('CSRF');
    const current = new URL(page.url());
    current.hash = current.hash.replace(/task=[^&]+/, 'task=00000000-0000-0000-0000-000000000000');
    await page.evaluate(hash => {location.hash=hash;}, current.hash);
    await expect(page.getByRole('alert')).toContainText(/不存在|不属于/);
    await expect(page.getByTestId('report-content')).toHaveCount(0);
  });

  test('XSS-shaped task content stays literal text on result and list', async ({page}) => {
    await register(page);
    const prompt = '<img src=x onerror="window.__xss=1"><script>window.__xss=2</script> Explain outbox.';
    await submitTopic(page,prompt);
    expect(await page.evaluate(() => (window as unknown as {__xss?: number}).__xss)).toBeUndefined();
    await expect(page.getByTestId('report-content').locator('img,script')).toHaveCount(0);
    await expect(page.getByTestId('task-detail')).toContainText(prompt);
    await noPageOverflow(page);
  });
  test('another tab CSRF rotation recovers once for submit and logout without duplicates', async ({page}) => {
    await register(page);
    // Same cookie jar, but original page still has its previous in-memory CSRF token.
    const rotated = await page.request.get('/api/v1/auth/me');
    expect(rotated.status()).toBe(200);
    const taskStatuses: number[] = [];
    page.on('response', response => {
      if(response.request().method()==='POST' && response.url().endsWith('/api/v1/tasks')) taskStatuses.push(response.status());
    });
    await submitTopic(page, '另一标签页轮换 CSRF 后，仍安全创建一个任务。');
    expect(taskStatuses).toEqual([403,202]);
    const list = await page.request.get('/api/v1/tasks');
    expect((await list.json()).total).toBe(1);
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(200);
    const logoutStatuses: number[] = [];
    page.on('response', response => {
      if(response.request().method()==='POST' && response.url().endsWith('/api/v1/auth/logout')) logoutStatuses.push(response.status());
    });
    await page.getByRole('button',{name:'退出登录'}).click();
    await expect(page.getByRole('button',{name:'登录',exact:true})).toBeVisible();
    expect(logoutStatuses).toEqual([403,204]);
    await expect(page.getByTestId('report-content')).toHaveCount(0);
    expect((await page.request.get('/api/v1/tasks')).status()).toBe(401);
  });

  test('logout in flight locks submission and clears private draft', async ({page}) => {
    const username = await register(page);
    await page.getByLabel('研究主题 / 任务要求').fill('退出过程中不应创建的私密草稿');
    let release!: () => void;
    const gate = new Promise<void>(resolve => {release=resolve;});
    let started!: () => void;
    const observed = new Promise<void>(resolve => {started=resolve;});
    await page.route('**/api/v1/auth/logout',async route => {
      const actualResponse = await route.fetch();
      started();
      await gate;
      try {await route.fulfill({response:actualResponse});} catch { /* navigation may abort */ }
    });
    let taskPosts=0;
    page.on('request',r => {if(r.method()==='POST' && r.url().endsWith('/api/v1/tasks')) taskPosts++;});
    await page.getByRole('button',{name:'退出登录'}).click();
    await observed;
    try {
      const submit = page.getByRole('button',{name:'提交报告任务',exact:true});
      if(await submit.count()) await expect(submit).toBeDisabled();
      const textarea = page.getByLabel('研究主题 / 任务要求');
      if(await textarea.count()) {
        await textarea.evaluate(el => {el.closest('form')!.requestSubmit();});
      }
      await page.waitForTimeout(300);
      expect(taskPosts).toBe(0);
    } finally {release();}
    await expect(page.getByRole('button',{name:'登录',exact:true})).toBeVisible();
    await page.unroute('**/api/v1/auth/logout');
    await login(page,username);
    await expect(page.getByLabel('研究主题 / 任务要求')).toHaveValue('');
    const list = await page.request.get('/api/v1/tasks');
    expect((await list.json()).total).toBe(0);
  });

});
