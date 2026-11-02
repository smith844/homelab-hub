import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('bulk reconciliation, summary filters and persistent exclusions stay reviewed', async ({page}) => {
  let loaded = false, applied = false, excluded = false, writes = 0;
  let bulkPlanReviewed = null, exclusionPosted = null;
  const containers = () => [
    {container_name: 'plex', container_key: 'plex', classification: 'matched', excluded: false,
      app_id: 1, app_name: 'Media Server', changes: [], reason: 'Root host and stable container name match.'},
    {container_name: 'open-webui', container_key: 'open-webui', classification: 'matched', excluded: false,
      app_id: 2, app_name: 'Open WebUI', changes: [], reason: 'Root host and stable container name match.'},
    {container_name: 'old-backup', container_key: 'old-backup',
      classification: excluded ? 'excluded' : 'missing_inventory', excluded,
      app_id: null, app_name: null, changes: [],
      reason: excluded ? 'Excluded from ordinary missing-inventory warnings: retained rollback.' : 'No application on this host has this recorded container name.'},
    {container_name: 'legacy-duplicate', container_key: 'legacy-duplicate', classification: 'duplicate',
      excluded: false, app_id: null, app_name: null, changes: [],
      reason: 'Ambiguous host-scoped identity; resolve duplicates before applying.'},
  ];
  const report = () => ({
    host: {key: 'betty', name: 'Betty'},
    scan: {source: loaded ? 'container fixture' : 'none', status: loaded ? 'success' : 'missing',
      fresh: loaded, coverage: loaded ? 'all_containers' : 'unknown', authoritative: loaded,
      completed_at: loaded ? new Date().toISOString() : null,
      reason: loaded ? 'Successful complete all-container snapshot within 24 hours.' : 'No scan supplied. Missing discovery data does not prove absence.'},
    network: null,
    containers: loaded ? containers() : [],
    inventory: [{app_id: 3, name: 'Router admin', container_key: 'router admin', classification: 'unknown',
      reason: 'No recorded Docker identity; this may be a non-container service.'}],
    duplicates: loaded ? [{container_key: 'legacy-duplicate', inventory_ids: [], discovered_count: 1}] : [],
    applications: [{id: 1, name: 'Media Server', container_key: 'plex'},
      {id: 2, name: 'Open WebUI', container_key: 'open-webui'}],
    folderview_unmatched: [], ungrouped: [],
    summary: loaded ? {matched: 2, unmatched: excluded ? 0 : 1, excluded: excluded ? 1 : 0,
      uncertain: 1, not_seen: 1} : {matched: 0, unmatched: 0, excluded: 0, uncertain: 0, not_seen: 1},
    exclusions: excluded ? [{id: 9, container_key: 'old-backup', container_name: 'old-backup',
      reason: 'retained rollback', observed: true, created_at: new Date().toISOString()}] : [],
  });

  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({contentType: 'text/css', body: readFileSync('node_modules/@picocss/pico/css/pico.min.css')}));
  await page.route('**/api/reconciliation**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET') return route.fulfill({json: {hosts: [{key: 'betty', name: 'Betty'}]}});
    const body = request.postDataJSON();
    if (path.endsWith('/compare')) {
      loaded = Boolean(body.snapshot);
      return route.fulfill({json: report()});
    }
    if (path.endsWith('/preview-bulk')) {
      bulkPlanReviewed = body;
      return route.fulfill({json: {token: 'bulk-token', expires_in: 600, plan: {
        kind: 'bulk_update', app_count: 2, source: 'container fixture',
        completed_at: new Date().toISOString(), coverage: 'all_containers',
        applications: [
          {app_id: 1, name: 'Media Server', container_name: 'plex', container_key: 'plex', fields: [
            {field: 'container_id', before: 'old', after: 'new-plex'},
            {field: 'image_id', before: 'old-image', after: 'sha256:new-plex'},
            {field: 'image', before: 'plex:old', after: 'plex:new'},
            {field: 'observed_at', before: 'old-time', after: 'new-time'},
          ]},
          {app_id: 2, name: 'Open WebUI', container_name: 'open-webui', container_key: 'open-webui', fields: [
            {field: 'container_id', before: 'old-webui', after: 'new-webui'},
            {field: 'image_id', before: 'old-webui-image', after: 'sha256:new-webui'},
            {field: 'image', before: 'open-webui:1', after: 'open-webui:2'},
            {field: 'observed_at', before: 'old-time', after: 'new-time'},
          ]},
        ],
        skipped: [{container_name: 'old-backup', container_key: 'old-backup',
          classification: excluded ? 'excluded' : 'missing_inventory', reason: 'No inventory match.'}],
      }}});
    }
    if (path.endsWith('/apply-bulk')) {
      writes++;
      expect(request.headers()['x-admin-token']).toBe('browser-fixture-only');
      expect(body.token).toBe('bulk-token');
      applied = true;
      return route.fulfill({json: {updated: 2, message: 'applied atomically'}});
    }
    if (path.endsWith('/exclusions') && request.method() === 'POST') {
      writes++;
      expect(request.headers()['x-admin-token']).toBe('browser-fixture-only');
      exclusionPosted = body;
      excluded = true;
      return route.fulfill({status: 201, json: {exclusion: {id: 9, container_key: 'old-backup',
        container_name: 'old-backup', reason: body.reason}}});
    }
    if (path.includes('/exclusions/') && request.method() === 'DELETE') {
      writes++;
      expect(request.headers()['x-admin-token']).toBe('browser-fixture-only');
      excluded = false;
      return route.fulfill({json: {message: 'Exclusion removed'}});
    }
    return route.fulfill({status: 404});
  });

  await page.goto('/#/reconciliation');
  const summary = page.getByRole('region', {name: 'Reconciliation summary'});
  await expect(summary).toContainText('0 Matched');
  await page.getByLabel('JSON snapshot file').setInputFiles({name: 'snapshot.json', mimeType: 'application/json',
    buffer: Buffer.from(JSON.stringify({schema_version: 1, host_key: 'betty', status: 'success', complete: true,
      coverage: 'all_containers', completed_at: new Date().toISOString(), containers: []}))});
  await expect(summary).toContainText('2 Matched');
  await expect(summary).toContainText('1 Unmatched');
  await expect(summary).toContainText('0 Excluded');
  await expect(summary).toContainText('1 Uncertain');

  await page.getByLabel('Container filter').selectOption('unmatched');
  await expect(page.getByRole('cell', {name: /^Missing from inventory/})).toBeVisible();
  await expect(page.getByRole('cell', {name: /^Matched/})).toHaveCount(0);
  await page.getByLabel('Container filter').selectOption('all');
  await page.getByLabel('Container search').fill('plex');
  await expect(page.getByText('1 shown')).toBeVisible();
  await page.getByLabel('Container search').fill('');

  await page.getByRole('button', {name: 'Preview bulk metadata update for 2 matched containers'}).click();
  expect(bulkPlanReviewed.host_key).toBe('betty');
  expect(bulkPlanReviewed.snapshot.host_key).toBe('betty');
  expect(writes).toBe(0);
  const bulkPreview = page.getByLabel('Bulk reconciliation preview');
  await expect(bulkPreview.getByText('Bulk preview for 2 applications')).toBeVisible();
  await page.setViewportSize({width: 700, height: 900});
  expect(await bulkPreview.evaluate(element => element.scrollWidth <= element.clientWidth + 1)).toBe(true);
  await bulkPreview.screenshot({path: `${process.env.TEMP || '/tmp'}/hlh-reconciliation-bulk-narrow.png`});
  await page.setViewportSize({width: 1280, height: 900});
  await expect(bulkPreview.getByRole('button', {name: 'Apply bulk update'})).toBeDisabled();
  await page.getByLabel('Reconciliation admin token').fill('browser-fixture-only');
  await page.getByRole('button', {name: 'Save session token'}).click();
  page.on('dialog', dialog => dialog.accept());
  await bulkPreview.getByRole('button', {name: 'Apply bulk update'}).click();
  expect(applied).toBe(true);
  expect(writes).toBe(1);

  await page.getByLabel('Exclusion container name').fill('old-backup');
  await page.getByLabel('Exclusion reason').fill('retained rollback');
  await page.getByRole('button', {name: 'Add exclusion'}).click();
  expect(exclusionPosted).toEqual({host_key: 'betty', container_name: 'old-backup', reason: 'retained rollback'});
  expect(writes).toBe(2);
  await expect(page.getByRole('heading', {name: 'Excluded containers (1)', exact: true})).toBeVisible();
  await expect(page.getByText('Observed in this snapshot')).toBeVisible();
  await expect(summary).toContainText('1 Excluded');
  await expect(summary).toContainText('0 Unmatched');

  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/hlh-reconciliation-bulk.png`, fullPage: true});

  await page.getByRole('button', {name: 'Remove exclusion'}).click();
  expect(writes).toBe(3);
  await expect(page.getByRole('heading', {name: 'Excluded containers (0)', exact: true})).toBeVisible();
  await expect(summary).toContainText('1 Unmatched');
});
