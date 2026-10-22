import {test, expect, type Page} from '@playwright/test';
import {noPageOverflow, password, requireRealBackend, screenshot, submitTopic, openTaskComposer, closeTaskDetail} from './helpers';

const demo = '目标：[search:销量] [stats]\n材料：销量 10 20 30';
async function registerAgentUser(page: Page) {
  await page.goto('/#lab');
  await page.getByRole('button', {name: '没有帐号？创建帐号'}).click();
  await page.getByLabel('用户名', {exact:true}).fill(`agent_${Date.now()}_${Math.floor(Math.random()*100000)}`);
  await page.getByLabel('密码', {exact:true}).fill(password);
  await page.getByRole('button', {name:'注册并登录', exact:true}).click();
  await expect(page.getByRole('button', {name:'退出登录'})).toBeVisible();
}
const idFromUrl = (url: string) => new URLSearchParams(url.split('?')[1]).get('task')!;

test.describe('committed single-Agent actions against real stores', () => {
  test.beforeEach(async ({request}) => {await requireRealBackend(request);});

  test('scripted read/search/stats observations match real API, persist on refresh and remain safe text', async ({page}, info) => {
    await registerAgentUser(page);
    const xss = '<img src=x onerror="window.__agentXss=true">';
    const taskUrl = await submitTopic(page, `${demo}\n${xss}`);
    const taskId = idFromUrl(taskUrl);
    const response = await page.request.get(`/api/v1/tasks/${taskId}/agent-steps`);
    expect(response.status()).toBe(200);
    const committed = await response.json();
    expect(committed.availability).toBe('committed');
    expect(committed.controller_mode).toBe('scripted_test');
    expect(committed.items.map((s:any) => s.kind)).toEqual(['tool_call','tool_result','tool_call','tool_result','tool_call','tool_result','final']);
    const actions = page.getByTestId('agent-actions');
    await expect(actions.getByTestId('agent-controller-mode')).toHaveText('脚本测试策略 · 无真实模型推理');
    await expect(page.getByRole('heading', {name:'后台生命周期', exact:true})).toBeVisible();
    await expect(actions.getByRole('heading', {name:'Agent 工具动作', exact:true})).toBeVisible();
    await expect(actions).toContainText('不是实时追踪');
    const uiSteps = actions.getByTestId('agent-step');
    await expect(uiSteps).toHaveCount(committed.items.length);
    for (let i=0; i<committed.items.length; i++) {
      const step = committed.items[i];
      const row = uiSteps.nth(i);
      await expect(row).toContainText(step.id);
      if (step.kind==='tool_call') {
        await expect(row).toContainText(step.tool_name);
        expect(JSON.parse(await row.getByLabel('工具参数', {exact:true}).innerText())).toEqual(step.arguments);
      } else if (step.kind==='tool_result') {
        expect(JSON.parse(await row.getByLabel('工具结果', {exact:true}).innerText())).toEqual(step.result);
      } else {
        await expect(row.getByLabel('最终答复摘要', {exact:true})).toHaveText(step.content);
      }
    }
    const numeric = committed.items.find((s:any) => s.kind==='tool_result' && s.tool_name==='numeric_stats');
    expect(numeric.result.count).toBe(3);
    expect(Number(numeric.result.sum)).toBe(60);
    await expect(actions).toContainText(xss);
    expect(await page.evaluate(() => (window as any).__agentXss)).toBeUndefined();
    await expect(actions.locator('img,script')).toHaveCount(0);
    await expect(page.getByTestId('task-events')).not.toContainText('tool_call');
    await noPageOverflow(page);
    await screenshot(page, info, 'single-agent-actions');
    await page.reload();
    await expect(page.getByTestId('agent-step')).toHaveCount(7);
    await expect(page.getByTestId('cache-status')).toContainText('hit');
    expect((await (await page.request.get(`/api/v1/tasks/${taskId}/agent-steps`)).json())).toEqual(committed);
    await noPageOverflow(page);
    await closeTaskDetail(page);
    await page.getByRole('button', {name:'退出登录'}).click();
    await expect(page.getByTestId('agent-actions')).toHaveCount(0);
    await expect(page.getByTestId('report-content')).toHaveCount(0);
    await page.goBack();
    await expect(page.getByTestId('agent-actions')).toHaveCount(0);
  });

  test('rejected material shows truthful failed-action availability rather than a fabricated trace', async ({page}) => {
    await registerAgentUser(page);
    await openTaskComposer(page);
    await page.getByLabel('研究主题 / 任务要求').fill('目标：[stats]\n材料：1e6');
    await page.getByRole('button', {name:'提交报告任务', exact:true}).click();
    await expect(page).toHaveURL(/task=/);
    await expect(page.getByTestId('task-events')).toContainText('failed');
    await expect(page.getByTestId('agent-not-committed')).toContainText('不代表没有调用工具');
    await expect(page.getByTestId('agent-step')).toHaveCount(0);
    await expect(page.getByTestId('report-content')).toHaveCount(0);
    const response = await page.request.get(`/api/v1/tasks/${idFromUrl(page.url())}/agent-steps`);
    expect(response.status()).toBe(200);
    expect(await response.json()).toEqual({items:[], availability:'not_committed', execution_kind:null, controller_mode:null});
    await noPageOverflow(page);
  });

  test('late real Agent actions cannot overwrite a different selected task', async ({page}) => {
    await registerAgentUser(page);
    const firstUrl = await submitTopic(page, demo);
    await expect(page.getByTestId('agent-step')).toHaveCount(7);
    const firstId = idFromUrl(firstUrl);
    const secondUrl = await submitTopic(page, '目标：[search:库存]\n材料：库存 40 50');
    const secondId = idFromUrl(secondUrl);
    await expect(page.getByTestId('agent-step')).toHaveCount(5);
    let release!: () => void;
    let seen!: () => void;
    const gate = new Promise<void>(resolve => {release=resolve;});
    const observed = new Promise<void>(resolve => {seen=resolve;});
    const routePattern = `**/api/v1/tasks/${firstId}/agent-steps`;
    await page.route(routePattern, async route => {
      const actualResponse = await route.fetch();
      seen();
      await gate;
      try {await route.fulfill({response:actualResponse});} catch { /* aborted old selection is expected */ }
    });
    await page.evaluate(url => {location.hash=new URL(url).hash;}, firstUrl);
    await observed;
    await page.evaluate(url => {location.hash=new URL(url).hash;}, secondUrl);
    await expect(page.getByTestId('agent-step')).toHaveCount(5);
    release();
    await page.waitForTimeout(300);
    await expect(page.getByTestId('agent-actions')).toContainText(secondId);
    await expect(page.getByTestId('agent-actions')).not.toContainText(firstId);
    await expect(page.getByTestId('agent-step')).toHaveCount(5);
    await noPageOverflow(page);
    await page.unroute(routePattern);
  });
});
