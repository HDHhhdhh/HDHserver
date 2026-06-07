import { test, expect } from '@playwright/test';

test('admin page loads with API stubs after row-date helper refactor', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });

  await page.route('**/api/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let body = {};
    if (path === '/api/students' || path === '/api/videos') body = [];
    if (path === '/api/tests-config') body = { categories: {} };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  await page.route('**/arrive-time/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.goto('http://127.0.0.1:8003/admin', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('#todayWrap')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('#doneWrap')).toBeVisible({ timeout: 10000 });

  expect(errors).toEqual([]);
});
