import {test, expect} from '@playwright/test';
import {noPageOverflow, screenshot} from './helpers';

test('anonymous architecture explains the six roles without invented runtime state', async ({page},info) => {
  await page.goto('/');
  await expect(page.getByRole('heading',{level:1,name:'把后端，看清楚。'})).toBeVisible();
  await expect(page.getByRole('main')).toBeVisible();
  await expect(page.getByRole('button',{name:'退出登录'})).toHaveCount(0);
  await expect(page.getByText('这里表示已受理，不是已完成',{exact:true})).toBeVisible();
  await noPageOverflow(page);
  await screenshot(page,info,'architecture');
  const inspector = page.getByTestId('component-detail');
  for(const [name,description] of [
    ['MySQL','权威任务状态'], ['Kafka','至少一次交付'],
    ['Worker','首版仅支持单 Worker'], ['MongoDB','跨库原子事务'],
    ['Redis','就绪接口未探测 Redis'], ['API','返回 202 不代表'],
  ]) {
    await page.getByRole('link',{name,exact:true}).click();
    await expect(inspector.getByRole('heading',{level:2,name,exact:true})).toBeVisible();
    await expect(inspector).toContainText(description);
    if ((page.viewportSize()?.width || 1440) <= 900) {
      await expect(inspector.getByRole("heading", {level:2,name,exact:true})).toBeFocused();
      await expect(inspector.getByRole("heading", {level:2,name,exact:true})).toBeInViewport();
    }
    for(const heading of ['解决什么问题','不负责什么','输入 → 输出','失败会怎样','对应源码']) {
      await expect(inspector.getByRole('heading',{name:heading,exact:true})).toBeVisible();
    }
    await noPageOverflow(page);
  }
  await page.getByRole('link',{name:'MySQL',exact:true}).click();
  await screenshot(page,info,'mysql-capabilities');
  await page.getByRole('tab',{name:/查询与结果/}).click();
  await expect(page.getByRole('tab',{name:/查询与结果/})).toHaveAttribute('aria-selected','true');
  await expect(page.getByText('先校验所有权，再读取已提交的结果引用',{exact:true})).toBeVisible();
  await expect(page.getByText(/Redis 不参与权限裁决/)).toBeVisible();
  await screenshot(page,info,'query-data-boundaries');
});

test('keyboard navigation and expandable reliability explanations are accessible', async ({page}) => {
  await page.goto('/');
  const mysql = page.getByRole('button',{name:/MySQL/}).first();
  await mysql.focus();
  await expect(mysql).toBeFocused();
  const outline = await mysql.evaluate(el => getComputedStyle(el).outlineStyle);
  expect(outline).not.toBe('none');
  await page.keyboard.press('Enter');
  await expect(page).toHaveURL(/#mysql/);
  await expect(page.getByTestId('component-detail')).toContainText('记录任务的事实');
  const toggle = page.getByRole('button',{name:/展开可靠性细节/});
  await toggle.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button',{name:/收起可靠性细节/})).toHaveAttribute('aria-expanded','true');
  await expect(page.getByText(/先用唯一事件 ID 去重并落库/)).toBeVisible();
  await page.getByRole('button',{name:/收起可靠性细节/}).click();
  await expect(page.getByRole('button',{name:/展开可靠性细节/})).toHaveAttribute('aria-expanded','false');
  // The design deliberately uses a persistent complementary inspector, not a modal.
  await expect(page.getByRole('complementary',{name:'组件详情'})).toHaveCount(1);
  await expect(page.getByRole('dialog')).toHaveCount(0);
});
