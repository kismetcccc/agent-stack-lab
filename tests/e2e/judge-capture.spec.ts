/** Evidence collection, not semantic acceptance or a real-provider evaluation. */
import {writeFile} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {test, expect, type Page} from '@playwright/test';
import {noPageOverflow, password, requireRealBackend, screenshot} from './helpers';

// Reuse frozen inputs without importing their expected outcomes as assertions.
const frozen = JSON.parse(readFileSync(new URL('../judge/cases.json', import.meta.url), 'utf8'));
const journeys: {id: string; goal: string; prompt: string}[] = ['J25', 'J11', 'J28'].map(id => {
  const entry = frozen.cases.find((item: {id: string}) => item.id === id);
  if (!entry) throw new Error(`Missing frozen browser case ${id}`);
  return {id: entry.id, goal: entry.goal, prompt: entry.prompt};
});

async function register(page: Page) {
  await page.goto('/#lab');
  await page.getByRole('button', {name: '没有帐号？创建帐号'}).click();
  await page.getByLabel('用户名', {exact: true}).fill(`judge_${Date.now()}_${Math.floor(Math.random()*100000)}`);
  await page.getByLabel('密码', {exact: true}).fill(password);
  await page.getByRole('button', {name: '注册并登录', exact: true}).click();
  await expect(page.getByRole('button', {name: '退出登录'})).toBeVisible();
}

for (const journey of journeys) {
  test(`judge capture only: ${journey.id}`, async ({page, request}, info) => {
    await requireRealBackend(request);
    await register(page);
    await page.getByLabel('研究主题 / 任务要求').fill(journey.prompt);
    await page.getByRole('button', {name: '提交报告任务', exact: true}).click();
    await expect(page).toHaveURL(/task=/);
    const taskId = new URLSearchParams(page.url().split('?')[1]).get('task')!;
    let task: any;
    await expect.poll(async () => {
      const response = await page.request.get(`/api/v1/tasks/${taskId}`);
      expect(response.status()).toBe(200);
      task = await response.json();
      return task.status;
    }).toMatch(/^(succeeded|failed)$/);
    const actionsResponse = await page.request.get(`/api/v1/tasks/${taskId}/agent-steps`);
    expect(actionsResponse.status()).toBe(200);
    const actions = await actionsResponse.json();
    const resultResponse = await page.request.get(`/api/v1/tasks/${taskId}/results`);
    const anonymousStatus = (await request.get(`/api/v1/tasks/${taskId}/agent-steps`)).status();
    const panel = page.getByTestId('agent-actions');
    let finalText: string | null = null;
    if (task.status === 'succeeded') {
      expect(resultResponse.status()).toBe(200);
      const result = await resultResponse.json();
      finalText = result.content;
      await expect(page.getByTestId('report-content')).toHaveText(finalText!);
      await expect(panel.getByTestId('agent-step')).toHaveCount(actions.items.length);
      await expect(panel.getByTestId('agent-controller-mode')).toHaveText('脚本测试策略 · 无真实模型推理');
    } else {
      expect(resultResponse.status()).toBe(409);
      await expect(page.getByTestId('agent-not-committed')).toBeVisible();
      await expect(page.getByTestId('report-content')).toHaveCount(0);
    }
    // Only synthetic task material and selected public UI fields; never dump a body,
    // request, auth response, storageState, cookies, headers, or environment variables.
    const observation = {
      schema_version: 1, capture_kind: 'real_api_browser', semantic_verdict: 'not_scored',
      case_id: journey.id, goal: journey.goal, prompt: journey.prompt,
      commit: process.env.GITHUB_SHA || 'local-unpublished', viewport: info.project.name,
      status: task.status, model_mode: task.model_mode,
      controller_mode: actions.controller_mode, availability: actions.availability,
      attempt_count: task.attempt_count, safe_error_code: task.error?.code ?? null,
      anonymous_read_status: anonymousStatus, result_status: resultResponse.status(),
      final_text: finalText, ui_actions_text: await panel.innerText(),
      calls: actions.items.filter((step: any) => step.kind === 'tool_call').map((step: any) => step.tool_name),
      truncation_flags: actions.items.filter((step: any) => step.kind === 'tool_result').map((step: any) => Boolean(step.truncated)),
      byte_facts: {prompt_utf8: Buffer.byteLength(journey.prompt), final_utf8: finalText === null ? null : Buffer.byteLength(finalText)},
    };
    await writeFile(info.outputPath('judge-observations.json'), JSON.stringify(observation, null, 2));
    await screenshot(page, info, `judge-${journey.id}`);
    expect(anonymousStatus).toBe(401);
    expect(task.model_mode).toBe('deterministic');
    if (task.status === 'succeeded') expect(actions.controller_mode).toBe('scripted_test');
    await expect(panel.locator('img,script')).toHaveCount(0);
    expect(await page.evaluate(() => (window as any).__judgeXss)).toBeUndefined();
    await noPageOverflow(page);
  });
}
