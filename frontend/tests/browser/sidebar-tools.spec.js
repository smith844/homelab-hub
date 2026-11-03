import {test, expect} from '@playwright/test';

test('Tools is a separated, collapsible group that remembers its state', async ({page}) => {
  await page.goto('/#/settings');
  const nav = page.getByRole('navigation', {name: 'Main navigation'});
  const toggle = nav.getByRole('button', {name: /tools/i});
  const tools = page.locator('#sidebar-tools');

  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(tools).toBeVisible();
  await expect(tools.getByRole('link', {name: 'Network discovery'})).toBeVisible();
  await expect(tools.getByRole('link', {name: 'Reconciliation'})).toBeVisible();

  const order = await nav.innerText();
  expect(order.indexOf('INVENTORY')).toBeLessThan(order.indexOf('TOOLS'));
  expect(order.indexOf('TOOLS')).toBeLessThan(order.indexOf('PREFERENCES'));
  expect(await page.locator('.tools-group').evaluate(el => getComputedStyle(el).borderTopWidth)).toBe('1px');

  for (const name of ['Overview', 'Maps', 'Documentation', 'Hosts', 'VMs & runtimes',
    'Applications', 'Container groups', 'Networks', 'Storage & shares', 'Other devices',
    'Settings']) {
    await expect(nav.getByRole('link', {name, exact: true})).toBeVisible();
  }

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(tools).toBeHidden();
  expect(await page.evaluate(() => localStorage.getItem('hlh.sidebarToolsOpen'))).toBe('false');

  await page.reload();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(tools).toBeHidden();

  await toggle.click();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(tools).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem('hlh.sidebarToolsOpen'))).toBe('true');

  await page.reload();
  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(tools).toBeVisible();
});

test('Tools expands on an active tools page without overwriting the saved preference', async ({page}) => {
  await page.addInitScript(() => localStorage.setItem('hlh.sidebarToolsOpen', 'false'));
  await page.route('**/api/reconciliation', route => route.fulfill({json: {hosts: []}}));

  await page.goto('/#/reconciliation');
  const nav = page.getByRole('navigation', {name: 'Main navigation'});
  const toggle = nav.getByRole('button', {name: /tools/i});
  const tools = page.locator('#sidebar-tools');

  await expect(toggle).toHaveAttribute('aria-expanded', 'true');
  await expect(tools).toBeVisible();
  const reconciliation = tools.getByRole('link', {name: 'Reconciliation'});
  await expect(reconciliation).toHaveAttribute('aria-current', 'page');
  await expect(toggle).toHaveClass(/active/);
  expect(await page.evaluate(() => localStorage.getItem('hlh.sidebarToolsOpen'))).toBe('false');

  await nav.getByRole('link', {name: 'Settings', exact: true}).click();
  await expect(page.getByRole('heading', {name: /Settings/})).toBeVisible();
  await expect(toggle).toHaveAttribute('aria-expanded', 'false');
  await expect(tools).toBeHidden();
});
