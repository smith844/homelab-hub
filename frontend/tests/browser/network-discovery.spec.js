import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('network discovery starts an approved scan, then compares results read-only', async ({page}) => {
  let starts = 0, comparisonRequests = 0, scanRequest, compareRequest;
  const scanId = '12345678-1234-1234-1234-123456789abc';
  const completedScan = {
    scan_id: scanId, type: 'portscan', scan_type: 'services', status: 'completed',
    progress: 100, target: '192.168.1.0/24',
    params: {target: '192.168.1.0/24', ports: '443,80'},
    started_at: '2026-11-02T18:00:00Z', completed_at: '2026-11-02T18:00:05Z',
    hosts_up: 2, hosts_down: 252, result_count: 2, complete: true, error: null,
    warnings: ['A fixture warning'],
    hosts: [
      {ip: '192.168.1.20', hostname: 'admin.lan', mac: 'AA:BB:CC:DD:EE:FF',
        vendor: 'Acme', os: 'Linux', open_ports: 1},
      {ip: '192.168.1.21', hostname: 'camera.lan', mac: '', vendor: 'Hikvision',
        os: '', open_ports: 1},
    ],
    results: [
      {ip: '192.168.1.20', hostname: 'admin.lan', mac: 'AA:BB:CC:DD:EE:FF',
        vendor: 'Acme', port: 443, protocol: 'tcp', state: 'open',
        service_name: 'https', service_version: ''},
      {ip: '192.168.1.21', hostname: 'camera.lan', mac: '', vendor: 'Hikvision',
        port: 80, protocol: 'tcp', state: 'open', service_name: 'http',
        service_version: 'nginx'},
    ],
  };
  const comparison = {
    network: {type: 'portscan', status: 'completed', reason: 'Imported status response only.',
      rows: [
        {kind: 'service', ip: '192.168.1.20', port: 443, name: 'admin.lan',
          classification: 'matched', matches: [{id: 1, name: 'Admin UI', type: 'apps'}],
          reason: 'Matched IP+port in the selected host scope.'},
        {kind: 'service', ip: '192.168.1.21', port: 80, name: 'camera.lan',
          classification: 'unmatched', matches: [],
          reason: 'No matching IP+port in inventory.'},
        {kind: 'service', ip: '192.168.1.20', port: 8443, name: 'admin-alt',
          classification: 'unverified', matches: [],
          reason: 'Job is not completed or HTTP probing failed.'},
      ]},
    scan: {status: 'unknown', containers: []},
  };

  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({contentType: 'text/css', body: readFileSync('node_modules/@picocss/pico/css/pico.min.css')}));
  await page.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (request.method() === 'GET' && path === '/api/network-discovery/config') {
      return route.fulfill({json: {
        configured: true, approved_ranges: ['192.168.1.0/24'], default_ports: '443,80',
        max_hosts: 256, max_ports: 256, error: null,
        scan_types: [{value: 'discover', label: 'Host discovery'},
          {value: 'services', label: 'Hosts and TCP services'}],
      }});
    }
    if (request.method() === 'GET' && path === '/api/reconciliation') {
      return route.fulfill({json: {hosts: [{key: 'betty', name: 'Betty'}]}});
    }
    if (request.method() === 'POST' && path === '/api/network-discovery/scan') {
      starts++;
      scanRequest = {body: request.postDataJSON(), token: request.headers()['x-admin-token']};
      return route.fulfill({status: 202, json: {scan: {...completedScan, status: 'running', complete: false}}});
    }
    if (request.method() === 'GET' && path === `/api/network-discovery/scan/${scanId}`) {
      return route.fulfill({json: {scan: completedScan}});
    }
    if (request.method() === 'POST' && path === '/api/reconciliation/compare') {
      comparisonRequests++;
      compareRequest = request.postDataJSON();
      return route.fulfill({json: comparison});
    }
    return route.fulfill({status: 404, json: {error: 'not mocked'}});
  });

  await page.goto('/#/network-discovery');
  await expect(page.getByRole('heading', {name: 'Network discovery'})).toBeVisible();
  await expect(page.getByLabel('Approved target range')).toHaveValue('192.168.1.0/24');
  await expect(page.getByRole('button', {name: /Start host discovery scan/})).toBeDisabled();

  await page.getByLabel('Network discovery admin token').fill('browser-fixture-only');
  await page.getByRole('button', {name: 'Save session token'}).click();
  await expect(page.getByText('Admin token saved for this browser session')).toBeVisible();
  await page.getByLabel('Scan type').selectOption('services');
  await page.getByLabel('TCP ports').fill('443,80');
  await page.getByRole('button', {name: 'Start discovery + service scan'}).click();

  await expect(page.getByRole('heading', {name: 'Scan status: completed'})).toBeVisible();
  await expect(page.getByText('2 hosts up')).toBeVisible();
  await expect(page.getByText('camera.lan').first()).toBeVisible();
  await expect(page.getByText('192.168.1.20:443')).toBeVisible();
  expect(starts).toBe(1);
  expect(scanRequest.token).toBe('browser-fixture-only');
  expect(scanRequest.body).toEqual({target: '192.168.1.0/24', scan_type: 'services', ports: '443,80'});
  expect(comparisonRequests).toBe(1);
  expect(compareRequest.host_key).toBe('betty');
  expect(compareRequest.snapshot.data.scan_id).toBe(scanId);

  const summary = page.getByRole('region', {name: 'Network comparison summary'});
  await expect(summary).toContainText('1 Matched');
  await expect(summary).toContainText('1 Unmatched');
  await expect(summary).toContainText('1 Uncertain');
  await expect(summary).toContainText('0 Unknown');

  await page.getByLabel('Network comparison filter').selectOption('unmatched');
  await expect(page.getByText('192.168.1.21:80')).toBeVisible();
  await expect(page.getByText('192.168.1.20:443')).toHaveCount(0);
  await page.getByLabel('Network comparison filter').selectOption('all');
  await page.getByLabel('Search network comparison').fill('admin');
  await expect(page.getByText('192.168.1.20:443')).toBeVisible();
  await expect(page.getByText('192.168.1.21:80')).toHaveCount(0);

  await page.getByLabel('Search discoveries').fill('hikvision');
  const hostTable = page.locator('.table-scroll').first();
  await expect(hostTable.getByText('camera.lan')).toBeVisible();
  await expect(hostTable.getByText('admin.lan')).toHaveCount(0);
  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/hlh-network-discovery.png`, fullPage: true});
});
