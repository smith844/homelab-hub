import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

for (const theme of ['light', 'dark']) {
  test(`${theme}: reconciliation stays read-only until a reviewed manual match is applied`, async ({page}) => {
    let applied = false, writes = 0, action;
    const snapshot = {schema_version: 1, host_key: 'betty', status: 'success', complete: true,
      coverage: 'all_containers', completed_at: new Date().toISOString(), containers: [{container_name: 'open-webui'}]};
    const report = loaded => ({
      host: {key: 'betty', name: 'Betty'},
      scan: {source: loaded ? 'container fixture' : 'none', status: loaded ? 'success' : 'missing',
        fresh: loaded, coverage: loaded ? 'all_containers' : 'unknown', completed_at: loaded ? snapshot.completed_at : null,
        reason: loaded ? 'Successful complete all-container snapshot within 24 hours.' : 'No scan supplied. Missing discovery data does not prove absence.'},
      network: null,
      containers: loaded ? [{container_name: 'open-webui', container_key: 'open-webui', classification: applied ? 'matched' : 'missing_inventory',
        reason: 'No application matches the discovered Docker name.', app_id: applied ? 2 : null, app_name: applied ? 'Friendly UI' : null, changes: []}] : [],
      inventory: [{app_id: 2, name: 'Friendly UI', container_key: 'friendly ui', classification: 'unknown', reason: 'No recorded Docker identity; this may be a non-container service.'}],
      duplicates: [], applications: [{id: 2, name: 'Friendly UI', container_key: 'friendly ui'}],
      folderview_unmatched: Array.from({length: 7}, (_, i) => ({container_key: `folderview-${i}`, group_name: 'Tools', group_active: true, reason: 'No inventory identity on this host.'})),
      ungrouped: Array.from({length: 11}, (_, i) => ({app_id: 20 + i, name: `Service ${i}`, reason: i === 0 ? 'Explicit manual Ungrouped choice.' : 'No active assignment; this can be intentional.'})),
    });
    await page.addInitScript(theme => localStorage.setItem('hlh.theme', JSON.stringify(theme)), theme);
    await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({contentType: 'text/css', body: readFileSync('node_modules/@picocss/pico/css/pico.min.css')}));
    await page.route('**/api/reconciliation**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (route.request().method() === 'GET') return route.fulfill({json: {hosts: [{key: 'betty', name: 'Betty'}]}});
      const body = route.request().postDataJSON();
      if (path.endsWith('/compare')) return route.fulfill({json: report(Boolean(body.snapshot))});
      if (path.endsWith('/preview')) {
        action = body.action;
        return route.fulfill({json: {token: 'synthetic-preview', expires_in: 600, plan: {
          kind: 'match', name: 'Friendly UI', group_override: 'Existing manual override follows the logical identity.',
          fields: [{field: 'logical identity', before: 'friendly ui', after: 'open-webui'}],
        }}});
      }
      if (path.endsWith('/apply')) {
        writes++;
        expect(route.request().headers()['x-admin-token']).toBe('browser-fixture-only');
        expect(body.token).toBe('synthetic-preview');
        applied = true;
        return route.fulfill({json: {app_id: 2, message: 'applied'}});
      }
      return route.fulfill({status: 404});
    });
    await page.goto('/#/reconciliation');
    await expect(page.getByRole('heading', {name: 'FolderView without inventory (7)', exact: true})).toBeVisible();
    await expect(page.getByRole('heading', {name: 'Ungrouped applications (11)', exact: true})).toBeVisible();
    await expect(page.getByText('No scan supplied. Missing discovery data does not prove absence.', {exact: true})).toBeVisible();
    expect(writes).toBe(0);
    await page.getByLabel('JSON snapshot file').setInputFiles({name: 'snapshot.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(snapshot))});
    await expect(page.getByRole('cell', {name: /^Missing from inventory/})).toBeVisible();
    await page.getByLabel('Match open-webui to inventory').selectOption('2');
    await page.getByRole('button', {name: 'Preview manual match', exact: true}).click();
    expect(action).toEqual({kind: 'match', container_key: 'open-webui', app_id: 2});
    expect(writes).toBe(0);
    const preview = page.getByRole('article', {name: 'Reconciliation preview'});
    await expect(preview.getByRole('cell', {name: 'friendly ui', exact: true})).toBeVisible();
    await expect(preview.getByRole('cell', {name: 'open-webui', exact: true})).toBeVisible();
    await expect(preview.getByRole('button', {name: 'Apply reviewed change'})).toBeDisabled();
    await preview.screenshot({path: `/tmp/hlh-reconciliation-preview-${theme}.png`});
    await page.getByLabel('Reconciliation admin token').fill('browser-fixture-only');
    await page.getByRole('button', {name: 'Save session token'}).click();
    await expect(page.getByText('Admin token saved for this browser session')).toBeVisible();
    page.on('dialog', dialog => dialog.accept());
    await preview.getByRole('button', {name: 'Apply reviewed change'}).click();
    await expect(page.getByRole('cell', {name: /^Matched /})).toBeVisible();
    expect(writes).toBe(1);
    await page.getByRole('button', {name: 'Preview metadata update'}).click();
    await page.getByText('Paste snapshot JSON', {exact: true}).click();
    await page.getByLabel('Snapshot JSON').fill('{invalid');
    await expect(page.getByRole('article', {name: 'Reconciliation preview'})).toHaveCount(0);
    await page.getByRole('button', {name: 'Compare snapshot'}).click();
    await expect(page.getByRole('alert')).toContainText('Invalid JSON');
    expect(writes).toBe(1);
  });
}
