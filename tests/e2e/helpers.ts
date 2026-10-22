import {expect, type Page, type APIRequestContext, type TestInfo, type Locator} from '@playwright/test';

export const password = 'Browser-only!42-password';

export async function requireRealBackend(request: APIRequestContext) {
  const response = await request.get('/readyz');
  expect(response.status(), 'real-stack readiness, no demo fallback').toBe(200);
  const health = await response.json();
  expect(health.mode).toBe('production');
  expect(health.model_mode).toBe('deterministic');
  for (const dependency of ['mysql', 'kafka', 'mongo']) {
    expect(health.dependencies[dependency], `${dependency} real readiness`).toBe('up');
  }
}

export async function noPageOverflow(page: Page) {
  const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
  const viewportWidth = page.viewportSize()!.width;
  expect(documentWidth, 'document must fit the configured viewport, not an overflow-expanded mobile innerWidth').toBeLessThanOrEqual(viewportWidth);
}

export async function screenshot(page: Page, info: TestInfo, name: string) {
  await page.evaluate(() => {
    window.scrollTo(0, 0);
    document.querySelectorAll<HTMLElement>('.console-drawer-body').forEach(el => {el.scrollTop = 0;});
  });
  await page.screenshot({path: info.outputPath(`${info.project.name}-${name}.png`), fullPage: true});
}

export async function submitTopic(page: Page, prompt: string) {
  await openTaskComposer(page);
  await page.getByLabel('研究主题 / 任务要求').fill(prompt);
  await page.getByRole('button', {name: '提交报告任务', exact: true}).click();
  await expect(page).toHaveURL(/task=/);
  await expect(page.getByTestId('report-content')).toContainText(prompt);
  return page.url();
}


/** Open the real responsive navigation, rather than clicking an off-screen link. */
export async function navigate(page: Page, label: string) {
  const labels: Record<string, string> = {MySQL: 'MySQL 记录', MongoDB: 'MongoDB 文档', Redis: 'Redis 键值', Kafka: 'Kafka 消息'};
  const link = page.getByRole('navigation').getByRole('link', {name: labels[label] || label, exact: true});
  if (page.viewportSize()!.width <= 800 && !await page.getByRole('dialog', {name: '导航菜单', exact: true}).isVisible()) {
    const menu = page.getByRole('button', {name: '打开导航', exact: true});
    await expect(menu).toBeVisible();
    await menu.click();
  }
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByRole('dialog', {name: '导航菜单', exact: true})).toHaveCount(0);
}

export async function closeTaskDetail(page: Page) {
  const detail = page.getByRole('dialog', {name: '任务详情', exact: true});
  if (await detail.count()) {
    await detail.getByRole('button', {name: '关闭任务详情', exact: true}).click();
    await expect(detail).toHaveCount(0);
  }
}

export async function openTaskComposer(page: Page) {
  await closeTaskDetail(page);
  const composer = page.getByRole('dialog', {name: '新建任务', exact: true});
  if (!await composer.count()) await page.getByRole('button', {name: '新建任务', exact: true}).click();
  await expect(composer).toBeVisible();
}

export async function closeDrawer(page: Page, title?: string) {
  const drawer = title ? page.getByRole('dialog', {name: title, exact: true}) : page.getByRole('dialog');
  await drawer.getByRole('button', {name: /^(关闭抽屉|关闭详情|关闭发送)$/}).click();
  await expect(drawer).toHaveCount(0);
}

/** Catch legacy CSS squeezing a valid, non-overflowing page into a half-width column. */
export async function primaryGeometry(page: Page, panel: Locator, primary: Locator) {
  await expect(primary).toBeVisible();
  const section = await panel.boundingBox();
  const content = await primary.boundingBox();
  expect(section).not.toBeNull();
  expect(content).not.toBeNull();
  expect(content!.width, 'primary resource fills the page, not an old editor/result track').toBeGreaterThanOrEqual(section!.width * 0.9);
  expect(content!.x, 'primary resource stays inside its panel').toBeGreaterThanOrEqual(section!.x - 2);
  expect(content!.x + content!.width, 'primary resource stays inside right panel edge').toBeLessThanOrEqual(section!.x + section!.width + 2);
  expect(content!.y, 'real data surface starts on the first screen, before help/tutorial content').toBeLessThan(page.viewportSize()!.height * 0.72);
  expect(content!.width, 'primary controls have a usable viewport width').toBeGreaterThan(page.viewportSize()!.width <= 900 ? 300 : 700);
  await noPageOverflow(page);
}
