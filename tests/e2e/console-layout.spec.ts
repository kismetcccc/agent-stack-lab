/** 1Panel-inspired shell acceptance. Normal journeys use the actual isolated CI stack. */
import {test, expect, type Page} from '@playwright/test';
import {closeDrawer, closeTaskDetail, navigate, noPageOverflow, openTaskComposer, password, primaryGeometry, requireRealBackend, screenshot, submitTopic} from './helpers';

const unique = () => `${Date.now()}_${Math.floor(Math.random() * 100000)}`;
const api = '/api/v1/lab';
async function register(page: Page) {
  await page.goto('/#playground');
  await navigate(page, 'MySQL');
  await page.getByRole('button', {name: '没有帐号？创建帐号', exact: true}).click();
  const username = `console_${unique()}`;
  await page.getByLabel('用户名', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '注册并登录', exact: true}).click();
  await expect(page.getByRole('button', {name: '退出登录', exact: true})).toBeVisible();
  return username;
}
async function seed(page: Page, path: string, method: string, body: unknown, status: number) {
  const me = await page.request.get('/api/v1/auth/me');
  expect(me.status()).toBe(200);
  const response = await page.request.fetch(path, {method, headers: {'X-CSRF-Token': (await me.json()).csrf_token}, data: body});
  expect(response.status()).toBe(status);
  return response.json();
}

// This test deliberately captures all six *primary* pages without an open drawer.
// The data is synthetic, but every write and read goes to the real Compose stores.
test('real six-page list-first desktop/mobile evidence, long data and no body overflow', async ({page, request}, info) => {
  await requireRealBackend(request);
  await register(page);
  const tag = unique();
  const record = await seed(page, `${api}/mysql/records`, 'POST', {name: `console-${tag}`, value: '长文本与长ID可查看完整详情。'.repeat(40)}, 201);
  const document = await seed(page, `${api}/mongo/documents`, 'POST', {document: {title: `console-${tag}`, literal: '<script>window.__consoleXss=1</script>', long: '无空格长JSON'.repeat(100)}}, 201);
  const key = `console_${tag}`;
  await seed(page, `${api}/redis/keys/${key}`, 'PUT', {value: '来自真实 Redis 的快照', ttl_seconds: 120}, 200);
  const kafka = await seed(page, `${api}/kafka/messages`, 'POST', {id: crypto.randomUUID(), key: `console-${tag}`, value: '真实 Kafka 消息列表摘要'.repeat(30)}, 202);
  await expect.poll(async () => (await (await page.request.get(`${api}/kafka/messages/${kafka.id}`)).json()).consumer.status).toBe('received');
  await navigate(page, '总览');
  const overview = page.getByRole('table', {name: '本地资源', exact: true});
  await expect(page.getByTestId('resource-mysql')).toContainText('探测通过');
  await expect(page.getByTestId('resource-redis')).toContainText('未提供总体探针');
  await primaryGeometry(page, page.locator('.console-overview'), overview.locator('..'));
  await screenshot(page, info, 'console-overview');
  for (const [label, id, required] of [['MySQL', 'mysql', record.id], ['MongoDB', 'mongo', document.id], ['Redis', 'redis', key], ['Kafka', 'kafka', kafka.id]]) {
    await navigate(page, label);
    const panel = page.getByTestId(`component-${id}`);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(panel.locator('textarea')).toHaveCount(0);
    if (id === 'redis') {
      await panel.getByLabel('查询键名', {exact: true}).fill(key);
      await panel.getByRole('button', {name: '读取键值', exact: true}).click();
      await expect(panel.getByTestId('redis-observation')).toContainText('服务端确认：键存在');
    }
    await expect(panel).toContainText(required);
    await primaryGeometry(page, panel, panel.getByTestId('resource-primary'));
    await screenshot(page, info, `console-${id}`);
  }
  await navigate(page, '任务与 Agent');
  await submitTopic(page, '控制台回归：[search:边界] 材料：边界清晰，不伪造监控状态。');
  await closeTaskDetail(page);
  await expect(page.getByLabel('研究主题 / 任务要求')).toHaveCount(0);
  await expect(page.locator('.task-row')).toHaveCount(1);
  await primaryGeometry(page, page.locator('.console-tasks'), page.locator('.console-tasks .tasks-panel'));
  await screenshot(page, info, 'console-tasks');
  expect(await page.evaluate(() => (window as any).__consoleXss)).toBeUndefined();
});

test('grouped navigation preserves legacy routes, selected state, refresh and history', async ({page, request}, info) => {
  await requireRealBackend(request);
  await register(page);
  const routes = [['总览', 'playground'], ['MySQL 记录', 'mysql'], ['MongoDB 文档', 'mongo'], ['Redis 键值', 'redis'], ['Kafka 消息', 'kafka'], ['任务与 Agent', 'lab'], ['架构说明', 'overview'], ['学习路径', 'learn'], ['故障实验', 'experiments']];
  for (const [label, route] of routes) {
    await navigate(page, label);
    await expect(page).toHaveURL(new RegExp(`#${route}$`));
    if (page.viewportSize()!.width <= 900) await page.getByRole('button', {name: '打开导航', exact: true}).click();
    const navigation = page.getByRole('navigation');
    for (const group of ['工作空间', '数据存储', '缓存', '消息', '任务', '学习中心']) {
      await expect(navigation.getByRole('heading', {name: group, exact: true})).toBeVisible();
    }
    await noPageOverflow(page);
    await expect(navigation.getByRole('link', {name: label, exact: true})).toHaveAttribute('aria-current', 'page');
    if (page.viewportSize()!.width <= 900) {
      await page.getByRole('button', {name: '关闭导航', exact: true}).click();
      await expect(page.getByRole('button', {name: '打开导航', exact: true})).toBeFocused();
    }
    await noPageOverflow(page);
    if (route === 'learn' || route === 'experiments') await screenshot(page, info, `console-${route}`);
  }
  await navigate(page, 'MySQL');
  await navigate(page, 'Redis');
  await page.goBack();
  await expect(page).toHaveURL(/#mysql$/);
  await expect(page.getByTestId('component-mysql')).toBeVisible();
  await page.goForward();
  await expect(page).toHaveURL(/#redis$/);
  await page.reload();
  await expect(page.getByTestId('component-redis')).toBeVisible();
  await page.goto('/#architecture-mysql');
  await expect(page.getByTestId('component-detail')).toContainText('记录任务的事实');
});

test('drawer keyboard containment, dirty draft cancellation and hash Back/Forward do not write', async ({page, request}) => {
  await requireRealBackend(request);
  await register(page);
  const open = page.getByRole('button', {name: '新建记录', exact: true});
  await open.click();
  const drawer = page.getByRole('dialog', {name: '新建记录', exact: true});
  await expect(drawer).toHaveAttribute('aria-modal', 'true');
  const controls = drawer.locator('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), a[href], select:not([disabled])');
  await controls.first().focus();
  await page.keyboard.press('Shift+Tab');
  await expect(controls.last()).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(controls.first()).toBeFocused();
  await page.keyboard.press('Escape');
  await expect(drawer).toHaveCount(0);
  await expect(open).toBeFocused();
  await open.click();
  let writes = 0;
  page.on('request', req => {if (['POST','PUT','DELETE'].includes(req.method()) && new URL(req.url()).pathname.startsWith(api)) writes++;});
  const name = drawer.getByLabel('名称', {exact: true});
  await name.fill('没有提交的本地草稿');
  await page.keyboard.press('Escape');
  const guard = page.getByRole('alertdialog', {name: '放弃未提交的草稿？', exact: true});
  await expect(guard.getByRole('button', {name: '继续编辑', exact: true})).toBeFocused();
  await guard.getByRole('button', {name: '继续编辑', exact: true}).click();
  await expect(name).toHaveValue('没有提交的本地草稿');
  await expect(name).toBeFocused();
  // Native history changes also go through the same guard, even while chrome is inert.
  await page.goBack();
  await expect(guard).toBeVisible();
  await guard.getByRole('button', {name: '继续编辑', exact: true}).click();
  await expect(page).toHaveURL(/#mysql$/);
  await expect(name).toHaveValue('没有提交的本地草稿');
  await page.goBack();
  await guard.getByRole('button', {name: '放弃草稿', exact: true}).click();
  await expect(page).toHaveURL(/#playground$/);
  await expect(drawer).toHaveCount(0);
  await page.goForward();
  await expect(page).toHaveURL(/#mysql$/);
  await open.click();
  await expect(drawer.getByLabel('名称', {exact: true})).toHaveValue('');
  expect(writes).toBe(0);
  await closeDrawer(page);
});

test('real session expiry clears an open private task draft instead of retaining it for a new login', async ({page, request}) => {
  await requireRealBackend(request);
  const username = await register(page);
  await navigate(page, '任务与 Agent');
  await openTaskComposer(page);
  await page.getByLabel('研究主题 / 任务要求').fill('会话失效后必须清除的合成私密草稿');
  const session = await page.request.get('/api/v1/auth/me');
  const csrf = (await session.json()).csrf_token;
  expect((await page.request.post('/api/v1/auth/logout', {headers: {'X-CSRF-Token': csrf}})).status()).toBe(204);
  // A real unauthorized submit/read discovers the other-tab logout. No fabricated 401.
  const submit = page.getByRole('button', {name: '提交报告任务', exact: true});
  if (await submit.count()) await submit.click();
  await expect(page.getByRole('button', {name: '登录', exact: true})).toBeVisible();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('会话失效后必须清除的合成私密草稿', {exact: true})).toHaveCount(0);
  await page.getByLabel('用户名', {exact: true}).fill(username);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '登录', exact: true}).click();
  await openTaskComposer(page);
  await expect(page.getByLabel('研究主题 / 任务要求')).toHaveValue('');
  expect((await (await page.request.get('/api/v1/tasks')).json()).total).toBe(0);
});

// These cases intentionally MOCK /readyz to test presentation only. They are not
// evidence that any actual dependency is down, or that a test adapter is production.
test.describe('MOCKED readiness presentation (not real dependency evidence)', () => {
  test('missing fields and adapter mode stay unknown/test-only; Redis never inherits green', async ({page}) => {
    let body: object = {};
    await page.route('**/readyz', route => route.fulfill({status: 200, json: body}));
    await page.goto('/#playground');
    await expect(page.getByTestId('resource-mysql')).toContainText('未知 / 未取得');
    await expect(page.getByTestId('resource-redis')).toContainText('未提供总体探针');
    await expect(page.getByRole('main')).not.toContainText(/Worker 在线|系统全部正常|CPU 使用率/);
    body = {mode: 'in_memory_test_adapter', model_mode: 'deterministic', dependencies: {mysql: 'in_memory_test_adapter', mongo: 'in_memory_test_adapter', kafka: 'in_memory_test_adapter'}};
    await page.getByRole('button', {name: '刷新检查', exact: true}).click();
    await expect(page.getByTestId('readiness-summary')).toContainText(/测试替身|测试 \/ 离线模式/);
    await expect(page.getByTestId('resource-mongo')).toContainText('测试替身');
    await noPageOverflow(page);
  });

  test('503 dependency evidence remains visible; failed recheck is explicitly a stale snapshot', async ({page}) => {
    let offline = false;
    await page.route('**/readyz', route => offline ? route.abort('failed') : route.fulfill({status: 503, json: {mode: 'production', model_mode: 'deterministic', dependencies: {mysql: 'up', mongo: 'down', kafka: 'up'}}}));
    await page.goto('/#playground');
    await expect(page.getByTestId('resource-mysql')).toContainText('探测通过');
    await expect(page.getByTestId('resource-mongo')).toContainText('未就绪');
    await expect(page.getByTestId('readiness-summary')).toContainText('503');
    offline = true;
    await page.getByRole('button', {name: '刷新检查', exact: true}).click();
    await expect(page.getByTestId('readiness-summary')).toContainText('上次检查，非当前状态');
    await expect(page.getByTestId('resource-mongo')).toContainText('未就绪');
    await expect(page.getByTestId('resource-redis')).toContainText('未提供总体探针');
    await navigate(page, 'MySQL');
    await expect(page).toHaveURL(/#mysql$/);
    await expect(page.getByRole('button', {name: '登录', exact: true})).toBeVisible();
    await noPageOverflow(page);
  });
});

test('real Kafka late selection, close and Back/Forward preserve one message identity without resending', async ({page, request}) => {
  await requireRealBackend(request);
  await register(page);
  const first = await seed(page, `${api}/kafka/messages`, 'POST', {id: crypto.randomUUID(), key: `history-a-${unique()}`, value: '历史消息 A'}, 202);
  const second = await seed(page, `${api}/kafka/messages`, 'POST', {id: crypto.randomUUID(), key: `history-b-${unique()}`, value: '历史消息 B'}, 202);
  await navigate(page, 'Kafka');
  let release!: () => void, seen = false, posts = 0;
  const gate = new Promise<void>(resolve => {release = resolve;});
  const pattern = `**${api}/kafka/messages/${first.id}`;
  await page.route(pattern, async route => {
    const actual = await route.fetch(); seen = true; await gate;
    try {await route.fulfill({response: actual});} catch { /* old selection was canceled */ }
  });
  page.on('request', req => {if (req.method() === 'POST' && new URL(req.url()).pathname === `${api}/kafka/messages`) posts++;});
  await page.getByRole('link', {name: `查看消息 ${first.id}`, exact: true}).click();
  await expect.poll(() => seen).toBe(true);
  try {
    await page.evaluate(id => {location.hash = `kafka?message=${id}`;}, second.id);
    await expect(page.getByTestId('kafka-detail')).toHaveAttribute('data-message-id', second.id);
    await expect(page.getByTestId('kafka-detail')).toContainText('历史消息 B');
  } finally {release();}
  await page.unroute(pattern);
  await page.waitForTimeout(300);
  await expect(page.getByTestId('kafka-detail')).not.toContainText('历史消息 A');
  await closeDrawer(page);
  await expect(page).toHaveURL(/#kafka$/);
  let closedReads = 0;
  const listen = (req: import('@playwright/test').Request) => {if (new URL(req.url()).pathname === `${api}/kafka/messages/${second.id}`) closedReads++;};
  page.on('request', listen);
  await page.waitForTimeout(2500); // More than one 2-second polling interval; close must stop it.
  page.off('request', listen);
  expect(closedReads).toBe(0);
  await page.goBack();
  await expect(page).toHaveURL(new RegExp(`message=${second.id}$`));
  await expect(page.getByTestId('kafka-detail')).toHaveAttribute('data-message-id', second.id);
  await page.goForward();
  await expect(page).toHaveURL(/#kafka$/);
  await expect(page.getByTestId('kafka-detail')).toHaveCount(0);
  expect(posts).toBe(0);
});

// Controlled network/clock case, not an assertion that the real broker is unavailable.
// The held response is fetched from the actual backend and never rewritten.
test('controlled delayed real Kafka read pauses after 20 seconds and late completion cannot invent confirmation', async ({page, request}) => {
  await requireRealBackend(request);
  await page.clock.install();
  await register(page);
  const message = await seed(page, `${api}/kafka/messages`, 'POST', {id: crypto.randomUUID(), key: `window_${unique()}`, value: '延迟读取的真实消息'}, 202);
  await navigate(page, 'Kafka');
  let release!: () => void, finished!: () => void, seen = false, posts = 0;
  const gate = new Promise<void>(resolve => {release = resolve;});
  const done = new Promise<void>(resolve => {finished = resolve;});
  const pattern = `**${api}/kafka/messages/${message.id}`;
  await page.route(pattern, async route => {
    const actual = await route.fetch(); seen = true; await gate;
    try {await route.fulfill({response: actual});} catch { /* observation window aborted the request */ }
    finally {finished();}
  });
  page.on('request', req => {if (req.method() === 'POST' && new URL(req.url()).pathname === `${api}/kafka/messages`) posts++;});
  await page.getByRole('link', {name: `查看消息 ${message.id}`, exact: true}).click();
  await expect.poll(() => seen).toBe(true);
  try {
    await page.clock.fastForward(21000);
    await expect(page.getByRole('dialog')).toContainText('自动观察已暂停，可手动刷新');
    await expect(page.getByRole('dialog')).toContainText('尚未观察到不代表发送失败');
    await expect(page.getByTestId('kafka-detail')).toHaveCount(0);
  } finally {release();}
  await done;
  await page.unroute(pattern);
  await expect(page.getByTestId('kafka-detail')).toHaveCount(0);
  await page.getByRole('button', {name: '手动刷新', exact: true}).click();
  await expect(page.getByTestId('kafka-detail')).toHaveAttribute('data-message-id', message.id);
  await expect(page.getByTestId('kafka-producer-status')).toHaveText('已获生产确认');
  expect(posts).toBe(0);
  await closeDrawer(page);
  let reads = 0;
  page.on('request', req => {if (new URL(req.url()).pathname === `${api}/kafka/messages/${message.id}`) reads++;});
  await page.clock.fastForward(25000);
  expect(reads).toBe(0);
  await expect(page.getByTestId('kafka-detail')).toHaveCount(0);
});
