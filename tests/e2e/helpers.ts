import {expect, type Page, type APIRequestContext, type TestInfo} from '@playwright/test';

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
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.screenshot({path: info.outputPath(`${info.project.name}-${name}.png`), fullPage: true});
}

export async function submitTopic(page: Page, prompt: string) {
  await page.getByLabel('研究主题 / 任务要求').fill(prompt);
  await page.getByRole('button', {name: '提交报告任务', exact: true}).click();
  await expect(page).toHaveURL(/task=/);
  await expect(page.getByTestId('report-content')).toContainText(prompt);
  return page.url();
}
