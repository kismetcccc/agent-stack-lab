/** Real same-origin Compose journeys. No fabricated store responses or progress. */
import {test, expect, type Page} from '@playwright/test';
import {noPageOverflow, password, requireRealBackend, screenshot} from './helpers';

const api = '/api/v1/lab';
const unique = () => `${Date.now()}_${Math.floor(Math.random() * 100000)}`;

async function workbenchGeometry(page: Page, component: string) {
  const panel = page.getByTestId(`component-${component}`);
  const grid = panel.locator('.lab-workbench-grid');
  await expect(grid).toBeVisible();
  const section = (await panel.boundingBox())!;
  const workspace = (await grid.boundingBox())!;
  const editor = (await grid.locator('.lab-editor').boundingBox())!;
  const results = (await grid.locator('.lab-results').boundingBox())!;
  // Overflow alone misses a legacy grid rule squeezing controls into half a page.
  expect(Math.abs(workspace.width - section.width), 'workbench fills available component width').toBeLessThanOrEqual(2);
  expect(Math.abs(editor.x - workspace.x), 'editor starts at workbench left edge').toBeLessThanOrEqual(2);
  expect(Math.abs(results.x + results.width - workspace.x - workspace.width), 'results reach workbench right edge').toBeLessThanOrEqual(2);
  if (page.viewportSize()!.width <= 900) {
    expect(Math.abs(editor.width - workspace.width), 'mobile editor has full width').toBeLessThanOrEqual(2);
    expect(Math.abs(results.width - workspace.width), 'mobile results have full width').toBeLessThanOrEqual(2);
    expect(Math.abs(results.x - editor.x), 'mobile panels align').toBeLessThanOrEqual(2);
    expect(results.y, 'mobile results stack below editor without overlap').toBeGreaterThanOrEqual(editor.y + editor.height);
  } else {
    expect(results.x, 'desktop panels use two separate tracks').toBeGreaterThan(editor.x + editor.width);
    expect(Math.abs(results.y - editor.y), 'desktop panels align at top').toBeLessThanOrEqual(2);
  }
}

async function register(page: Page, component: string) {
  await page.goto(`/#${component}`);
  await page.getByRole('button', {name: '没有帐号？创建帐号'}).click();
  await page.getByLabel('用户名', {exact: true}).fill(`components_${unique()}`);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '注册并登录', exact: true}).click();
  await expect(page.getByRole('button', {name: '退出登录'})).toBeVisible();
  await expect(page.getByTestId(`component-${component}`)).toBeVisible();
  await workbenchGeometry(page, component);
}

async function noTaskPrerequisite(page: Page) {
  const response = await page.request.get('/api/v1/tasks');
  expect(response.status()).toBe(200);
  expect((await response.json()).total, 'component operations must not create hidden Agent tasks').toBe(0);
}

function responseFor(page: Page, path: string, method: string, status: number) {
  return page.waitForResponse(response => new URL(response.url()).pathname === path &&
    response.request().method() === method && response.status() === status);
}

test.describe('independent personal component playground against real stores', () => {
  test.beforeEach(async ({request}) => { await requireRealBackend(request); });

  test('MySQL direct CRUD persists, guards double submit and cancel, and recovers CSRF rotation', async ({page}, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.goto('/');
    await expect(page.getByRole('heading', {level: 1, name: '选一个组件，动手试一次。'})).toBeVisible();
    await expect(page.locator('.playground-card')).toHaveCount(4);
    await noPageOverflow(page);
    await screenshot(page, info, 'component-home');
    await register(page, 'mysql');
    const panel = page.getByTestId('component-mysql');
    const name = `browser-mysql-${unique()}`;
    const value = '<img src=x onerror="window.__labXss=1"> MySQL 保存的真实文本';
    await panel.getByLabel('名称', {exact: true}).fill(name);
    await panel.getByLabel('内容', {exact: true}).fill(value);
    let creates = 0, deletes = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === `${api}/mysql/records`) creates++;
      if (request.method() === 'DELETE' && request.url().includes(`${api}/mysql/records/`)) deletes++;
    });
    const createdResponse = responseFor(page, `${api}/mysql/records`, 'POST', 201);
    await panel.getByLabel('名称', {exact: true}).evaluate(el => {
      const form = el.closest('form')!; form.requestSubmit(); form.requestSubmit();
    });
    const created = await (await createdResponse).json();
    const row = panel.locator('tbody tr').filter({hasText: created.id});
    await expect(row).toContainText(value);
    expect(creates).toBe(1);
    await expect(row.locator('img,script')).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__labXss)).toBeUndefined();
    await panel.getByRole('button', {name: `编辑 ${name}`, exact: true}).click();
    await expect(panel.getByLabel('内容', {exact: true})).toHaveValue(value);
    await panel.getByLabel('内容', {exact: true}).fill('取消编辑不应保存');
    await panel.getByRole('button', {name: '取消编辑', exact: true}).click();
    expect((await (await page.request.get(`${api}/mysql/records/${created.id}`)).json()).value).toBe(value);
    await panel.getByRole('button', {name: `编辑 ${name}`, exact: true}).click();
    await panel.getByLabel('内容', {exact: true}).fill('真实更新后的 MySQL 内容');
    expect((await page.request.get('/api/v1/auth/me')).status()).toBe(200); // another tab rotates CSRF
    const updates: number[] = [];
    page.on('response', response => {
      if (response.request().method() === 'PUT' && response.url().endsWith(`${api}/mysql/records/${created.id}`)) updates.push(response.status());
    });
    await panel.getByRole('button', {name: '保存修改', exact: true}).click();
    await expect(row).toContainText('真实更新后的 MySQL 内容');
    expect(updates).toEqual([403, 200]);
    await page.reload();
    await expect(row).toContainText('真实更新后的 MySQL 内容');
    await panel.getByRole('button', {name: `删除 ${name}`, exact: true}).click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog).toContainText(name);
    await expect(dialog.getByRole('button', {name: '取消', exact: true})).toBeFocused();
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    expect(deletes).toBe(0);
    await expect(row).toBeVisible();
    await noPageOverflow(page);
    await screenshot(page, info, 'mysql-real-record');
    await panel.getByRole('button', {name: `删除 ${name}`, exact: true}).click();
    const deletedResponse = responseFor(page, `${api}/mysql/records/${created.id}`, 'DELETE', 204);
    await dialog.getByRole('button', {name: '确认删除', exact: true}).click();
    await deletedResponse;
    await expect(row).toHaveCount(0);
    expect(deletes).toBe(1);
    expect((await page.request.get(`${api}/mysql/records/${created.id}`)).status()).toBe(404);
    await noTaskPrerequisite(page);
    expect(errors).toEqual([]);
  });

  test('Redis writes actual TTL, confirms expiry by HTTP, overwrites and deletes only a named key', async ({page}, info) => {
    await register(page, 'redis');
    const panel = page.getByTestId('component-redis');
    const key = `browser_${unique()}`;
    await panel.getByLabel('键名', {exact: true}).fill(key);
    await panel.getByLabel('值', {exact: true}).fill('Redis 中的真实临时值');
    await panel.getByLabel('过期时间（秒）', {exact: true}).fill('3');
    const put = responseFor(page, `${api}/redis/keys/${key}`, 'PUT', 200);
    await panel.getByRole('button', {name: '写入并设置 TTL', exact: true}).click();
    const written = await (await put).json();
    expect(written.exists).toBe(true);
    expect(written.value).toBe('Redis 中的真实临时值');
    expect(written.ttl_ms).toBeGreaterThan(0);
    expect(written.ttl_ms).toBeLessThanOrEqual(3000);
    await expect(panel.getByTestId('redis-ttl')).toContainText(`${written.ttl_ms}`);
    await expect(panel.getByText('服务端确认：键存在', {exact: true})).toBeVisible();
    await noPageOverflow(page);
    await screenshot(page, info, 'redis-real-ttl');
    await expect.poll(async () => {
      const response = await page.request.get(`${api}/redis/keys/${key}`);
      expect(response.status()).toBe(200);
      return (await response.json()).exists;
    }, {timeout: 12000, intervals: [500]}).toBe(false);
    const expired = responseFor(page, `${api}/redis/keys/${key}`, 'GET', 200);
    await panel.getByRole('button', {name: '再次读取', exact: true}).click();
    const missing = await (await expired).json();
    expect(missing).toMatchObject({key, exists: false, value: null, ttl_ms: -2});
    await expect(panel.getByText('服务端确认：键不存在', {exact: true})).toBeVisible();
    await panel.getByLabel('值', {exact: true}).fill('覆盖为新值');
    await panel.getByLabel('过期时间（秒）', {exact: true}).fill('60');
    await panel.getByRole('button', {name: '写入并设置 TTL', exact: true}).click();
    await expect(panel.getByText('覆盖为新值', {exact: true})).toBeVisible();
    await panel.getByRole('button', {name: '删除键', exact: true}).click();
    await page.getByRole('alertdialog').getByRole('button', {name: '取消', exact: true}).click();
    expect((await (await page.request.get(`${api}/redis/keys/${key}`)).json()).exists).toBe(true);
    await panel.getByRole('button', {name: '删除键', exact: true}).click();
    const deleted = responseFor(page, `${api}/redis/keys/${key}`, 'DELETE', 204);
    await page.getByRole('alertdialog').getByRole('button', {name: '确认删除', exact: true}).click();
    await deleted;
    await panel.getByRole('button', {name: '读取键值', exact: true}).click();
    await expect(panel.getByText('服务端确认：键不存在', {exact: true})).toBeVisible();
    await noTaskPrerequisite(page);
  });

  test('Mongo JSON create/read/replace/delete, invalid JSON and late real response navigation', async ({page}, info) => {
    await register(page, 'mongo');
    const panel = page.getByTestId('component-mongo');
    let posts = 0, deletes = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === `${api}/mongo/documents`) posts++;
      if (request.method() === 'DELETE' && request.url().includes(`${api}/mongo/documents/`)) deletes++;
    });
    await panel.getByLabel('JSON 文档', {exact: true}).fill('{not JSON');
    await panel.getByRole('button', {name: '保存文档', exact: true}).click();
    await expect(panel.getByRole('alert')).toContainText('JSON 格式不正确');
    expect(posts).toBe(0);
    const document = {title: `browser-mongo-${unique()}`, nested: {items: [1, true, null]}, literal: '<img src=x onerror="window.__labXss=2">', long: '无空格的长 JSON 字符串'.repeat(40)};
    await panel.getByLabel('JSON 文档', {exact: true}).fill(JSON.stringify(document, null, 2));
    const post = responseFor(page, `${api}/mongo/documents`, 'POST', 201);
    await panel.getByRole('button', {name: '保存文档', exact: true}).click();
    const created = await (await post).json();
    expect(created.document).toEqual(document);
    const item = panel.locator('article.document-item').filter({hasText: created.id});
    await expect(item).toContainText(JSON.stringify(document.literal));
    expect(JSON.parse(await item.locator('pre').innerText())).toEqual(document);
    expect(await page.evaluate(() => (window as any).__labXss)).toBeUndefined();
    await expect(item.locator('img,script')).toHaveCount(0);
    await noPageOverflow(page);
    await screenshot(page, info, 'mongo-real-json');
    await panel.getByRole('button', {name: `编辑文档 ${created.id}`, exact: true}).click();
    await expect(panel.getByLabel('JSON 文档', {exact: true})).toHaveValue(JSON.stringify(document, null, 2));
    const changed = {title: document.title, replacement: {count: 42}};
    await panel.getByLabel('JSON 文档', {exact: true}).fill(JSON.stringify(changed));
    await panel.getByRole('button', {name: '保存修改', exact: true}).click();
    await expect(item).toContainText('replacement');
    await page.reload();
    await expect(item).toContainText('replacement');
    expect(JSON.parse(await item.locator('pre').innerText())).toEqual(changed);
    // Delay a real detail response only; the fixture never invents backend JSON.
    let release!: () => void, seen!: () => void;
    const gate = new Promise<void>(resolve => {release = resolve;});
    const observed = new Promise<void>(resolve => {seen = resolve;});
    const pattern = `**${api}/mongo/documents/${created.id}`;
    await page.route(pattern, async route => {
      const actual = await route.fetch(); seen(); await gate;
      try {await route.fulfill({response: actual});} catch { /* old navigation was aborted */ }
    });
    await panel.getByRole('button', {name: `编辑文档 ${created.id}`, exact: true}).click();
    await observed;
    await page.getByRole('link', {name: 'Redis', exact: true}).click();
    await expect(page.getByTestId('component-redis')).toBeVisible();
    release();
    await page.unroute(pattern);
    await expect(page.getByLabel('JSON 文档', {exact: true})).toHaveCount(0);
    await page.goBack();
    await expect(item).toContainText('replacement');
    await expect(panel.getByLabel('JSON 文档', {exact: true})).toHaveValue('');
    await panel.getByRole('button', {name: `删除文档 ${created.id}`, exact: true}).click();
    await page.getByRole('alertdialog').getByRole('button', {name: '取消', exact: true}).click();
    expect(deletes).toBe(0);
    await expect(item).toBeVisible();
    await panel.getByRole('button', {name: `删除文档 ${created.id}`, exact: true}).click();
    const deleted = responseFor(page, `${api}/mongo/documents/${created.id}`, 'DELETE', 204);
    await page.getByRole('alertdialog').getByRole('button', {name: '确认删除', exact: true}).click();
    await deleted;
    await expect(item).toHaveCount(0);
    expect((await page.request.get(`${api}/mongo/documents/${created.id}`)).status()).toBe(404);
    await noTaskPrerequisite(page);
    await noPageOverflow(page);
  });

  test('Kafka real producer acknowledgment and consumer receipt remain distinct and survive refresh/logout', async ({page}, info) => {
    await register(page, 'kafka');
    const panel = page.getByTestId('component-kafka');
    const key = `browser_${unique()}`, value = '来自浏览器的真实 Kafka 消息';
    await panel.getByLabel('消息键', {exact: true}).fill(key);
    await panel.getByLabel('消息内容', {exact: true}).fill(value);
    let sends = 0;
    page.on('request', request => {
      if (request.method() === 'POST' && new URL(request.url()).pathname === `${api}/kafka/messages`) sends++;
    });
    const sentResponse = responseFor(page, `${api}/kafka/messages`, 'POST', 202);
    await panel.getByLabel('消息键', {exact: true}).evaluate(el => {
      const form = el.closest('form')!; form.requestSubmit(); form.requestSubmit();
    });
    const sent = await (await sentResponse).json();
    expect(sent.producer.status).toBe('acknowledged');
    expect(sent.producer.offset).toBeGreaterThanOrEqual(0);
    expect(sends).toBe(1);
    let received: any;
    await expect.poll(async () => {
      const response = await page.request.get(`${api}/kafka/messages/${sent.id}`);
      expect(response.status()).toBe(200); received = await response.json();
      return received.consumer.status;
    }, {timeout: 45000, intervals: [500, 1000]}).toBe('received');
    expect(received.consumer).toMatchObject({group: 'agent-lab-observer-v1', key, value, partition: sent.producer.partition, offset: sent.producer.offset});
    await panel.getByRole('button', {name: '手动刷新', exact: true}).click();
    const detail = panel.getByTestId('kafka-detail');
    await expect(detail).toHaveAttribute('data-message-id', sent.id);
    await expect(detail.getByTestId('kafka-producer-status')).toHaveText('已获生产确认');
    await expect(detail.getByTestId('kafka-consumer-status')).toHaveText('已观察到消费者收取');
    await expect(detail.getByTestId('kafka-consumer-value')).toHaveText(value);
    await noPageOverflow(page);
    await screenshot(page, info, 'kafka-real-ack-and-receipt');
    await page.reload();
    await expect(panel).toContainText(sent.id);
    await noTaskPrerequisite(page);
    await page.getByRole('button', {name: '退出登录'}).click();
    await expect(page).toHaveURL(/#playground$/);
    await expect(page.getByTestId('kafka-detail')).toHaveCount(0);
    await expect(page.getByLabel('消息内容', {exact: true})).toHaveCount(0);
    expect((await page.request.get(`${api}/kafka/messages/${sent.id}`)).status()).toBe(401);
    await page.goBack();
    await expect(page.getByRole('button', {name: '登录', exact: true})).toBeVisible();
    await expect(page.getByTestId('kafka-detail')).toHaveCount(0);
    await expect(page.getByLabel('消息内容', {exact: true})).toHaveCount(0);
  });
});
