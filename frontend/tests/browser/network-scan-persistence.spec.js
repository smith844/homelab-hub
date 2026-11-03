import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

const SCAN_ID = '12345678-1234-1234-1234-123456789abc';
const TOKEN = 'browser-fixture-only';

const runningScan = {
  scan_id: SCAN_ID, type: 'portscan', scan_type: 'services', status: 'running',
  progress: 35, target: '192.168.1.0/24',
  params: {target: '192.168.1.0/24', ports: '443,80'},
  started_at: '2026-11-03T12:00:00Z', completed_at: null,
  hosts_up: 1, hosts_down: 0, result_count: 0, complete: false, error: null,
  warnings: [], hosts: [], results: [],
};

const completedScan = {
  ...runningScan, status: 'completed', progress: 100, complete: true,
  completed_at: '2026-11-03T12:00:05Z', hosts_up: 4, hosts_down: 252,
  result_count: 1,
  hosts: [
    {ip: '192.168.1.16', hostname: 'pi.hole', mac: '', vendor: '', os: '', open_ports: 1},
  ],
  results: [
    {ip: '192.168.1.16', port: 80, protocol: 'tcp', state: 'open',
      service_name: 'http', service_version: '', hostname: 'pi.hole', mac: '', vendor: ''},
  ],
};

const comparison = {
  source: 'nmap', sources: ['nmap'],
  scan: {type: 'portscan', status: 'completed', target: '192.168.1.0/24',
    completed_at: '2026-11-03T12:00:05Z', uncertain: false, warnings: []},
  hosts: [
    {ip: '192.168.1.16', hostname: 'pi.hole', mac: '', vendor: '', os: '', open_ports: 1,
      classification: 'matched', sources: ['nmap'],
      reason: 'Exact IP evidence in inventory.', evidence: ['IP address'],
      candidates: [{type: 'hardware', id: 3, name: 'PiHole Main', category: 'Physical host',
        parent: null, ip: '192.168.1.16', port: null, evidence: ['IP address']}],
      service_candidates: [], network: {id: 1, name: 'LAN', vlan_id: 1}},
  ],
  services: [],
  unifi_only: [],
  unifi: {configured: false, has_data: false},
  summary: {
    hosts_discovered: 1, hosts_matched: 1, hosts_plausible: 0, hosts_shared: 0,
    hosts_ambiguous: 0, hosts_unmatched: 0, hosts_unverified: 0,
    services_discovered: 0, services_matched: 0, services_plausible: 0,
    services_ambiguous: 0, services_unmatched: 0, services_unverified: 0,
    inventory_devices: 1, inventory_services: 0, unifi_infrastructure_devices: 0,
    unifi_clients: 0, unifi_current_clients: 0, unifi_historical_clients: 0,
    unifi_only: 0, nmap_hosts_with_unifi: 0, unifi_source_conflicts: 0,
  },
  reason: 'Read-only network-wide comparison fixture.',
};

async function mockApi(page, state) {
  await page.route('https://cdn.jsdelivr.net/**', route => route.fulfill({
    contentType: 'text/css', body: readFileSync('node_modules/@picocss/pico/css/pico.min.css'),
  }));
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
    if (request.method() === 'GET' && path === '/api/network-discovery/unifi/status') {
      return route.fulfill({json: {unifi: {configured: false, has_data: false, error: null}}});
    }
    if (request.method() === 'POST' && path === '/api/network-discovery/scan') {
      state.starts++;
      return route.fulfill({status: 202, json: {scan: runningScan}});
    }
    if (request.method() === 'GET' && path === `/api/network-discovery/scan/${SCAN_ID}`) {
      state.statusCalls++;
      if (state.status === 'expired') {
        return route.fulfill({status: 404, json: {error: 'Scan not found or expired'}});
      }
      if (state.status === 'unavailable') {
        return route.fulfill({status: 503,
          json: {error: 'The scan service is unreachable; check HLH_SCANNER_URL and the scanner process'}});
      }
      if (state.status === 'completed') {
        return route.fulfill({json: {scan: completedScan}});
      }
      return route.fulfill({json: {scan: runningScan}});
    }
    if (request.method() === 'POST' && path === '/api/network-discovery/reconcile') {
      state.reconciliations++;
      return route.fulfill({json: comparison});
    }
    return route.fulfill({status: 404, json: {error: 'not mocked'}});
  });
}

async function seedSession(page, scan) {
  await page.addInitScript(({scan, token}) => {
    sessionStorage.setItem('hlh.adminToken', token);
    if (scan) {
      sessionStorage.setItem('hlh.networkScan', JSON.stringify({
        version: 1, saved_at: new Date().toISOString(), scan,
      }));
    }
  }, {scan, token: TOKEN});
}

test('a running scan survives navigation and refresh, then resumes to completion', async ({page}) => {
  const state = {starts: 0, statusCalls: 0, reconciliations: 0, status: 'running'};
  await mockApi(page, state);

  await page.goto('/#/network-discovery');
  await page.getByLabel('Network discovery admin token').fill(TOKEN);
  await page.getByRole('button', {name: 'Save session token'}).click();
  await page.getByLabel('Scan type').selectOption('services');
  await page.getByLabel('TCP ports').fill('443,80');
  await page.getByRole('button', {name: 'Start discovery + service scan'}).click();

  await expect(page.getByRole('heading', {name: 'Scan status: running'})).toBeVisible();
  await expect(page.getByRole('progressbar', {name: 'Scan progress'})).toHaveAttribute('value', '35');
  await expect(page.getByText(/Scan in progress · target/)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Start discovery + service scan'})).toBeDisabled();
  expect(state.starts).toBe(1);

  const indicator = page.getByRole('link', {name: /Scan running/});
  await expect(indicator).toBeVisible();
  await expect(indicator).toContainText('192.168.1.0/24');

  await page.getByRole('link', {name: 'Settings'}).click();
  await expect(page.getByRole('heading', {name: /Settings/})).toBeVisible();
  await expect(page.getByRole('link', {name: /Scan running/})).toBeVisible();

  await page.reload();
  await expect(page.getByRole('link', {name: /Scan running/})).toBeVisible();

  await page.getByRole('link', {name: /Scan running/}).click();
  await expect(page.getByRole('heading', {name: 'Scan status: running'})).toBeVisible();
  await expect(page.getByRole('progressbar', {name: 'Scan progress'})).toHaveAttribute('value', '35');
  await expect(page.getByRole('button', {name: /^Start .* scan$/})).toBeDisabled();
  expect(state.starts).toBe(1);

  state.status = 'completed';
  await expect(page.getByRole('heading', {name: 'Scan status: completed'})).toBeVisible({timeout: 15000});
  await expect(page.getByRole('heading', {name: 'Network-wide inventory matching'})).toBeVisible();
  await expect(page.getByText('PiHole Main', {exact: true}).first()).toBeVisible();
  await expect.poll(() => state.reconciliations).toBe(1);
  expect(state.starts).toBe(1);
  await expect(page.getByRole('link', {name: /Scan running/})).toHaveCount(0);
});

test('a completed scan is restored for review without submitting another scan', async ({page}) => {
  const state = {starts: 0, statusCalls: 0, reconciliations: 0, status: 'completed'};
  await mockApi(page, state);
  await seedSession(page, completedScan);

  await page.goto('/#/network-discovery');
  await expect(page.getByRole('heading', {name: 'Scan status: completed'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'Network-wide inventory matching'})).toBeVisible();
  await expect(page.getByText('PiHole Main', {exact: true}).first()).toBeVisible();
  await expect(page.getByText(SCAN_ID)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Start host discovery scan'})).toBeEnabled();
  expect(state.starts).toBe(0);
  expect(state.reconciliations).toBe(1);
  await expect(page.getByRole('link', {name: /Scan running/})).toHaveCount(0);
});

test('an expired running scan is cleared with a notice and no automatic restart', async ({page}) => {
  const state = {starts: 0, statusCalls: 0, reconciliations: 0, status: 'expired'};
  await mockApi(page, state);
  await seedSession(page, runningScan);

  await page.goto('/#/network-discovery');
  await expect(page.getByRole('heading', {name: 'Saved scan unavailable'})).toBeVisible();
  await expect(page.getByText(/no longer retained by the scanner/)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Retry saved scan status'})).toHaveCount(0);
  expect(state.starts).toBe(0);
  await expect.poll(() => page.evaluate(() => sessionStorage.getItem('hlh.networkScan'))).toBeNull();
  await expect(page.getByRole('button', {name: 'Start host discovery scan'})).toBeEnabled();
});

test('an unavailable scanner keeps the saved scan and offers an explicit retry', async ({page}) => {
  const state = {starts: 0, statusCalls: 0, reconciliations: 0, status: 'unavailable'};
  await mockApi(page, state);
  await seedSession(page, runningScan);

  await page.goto('/#/network-discovery');
  await expect(page.getByRole('heading', {name: 'Scan status: running'})).toBeVisible();
  await expect(page.getByText(/Could not refresh the saved scan status/)).toBeVisible();
  await expect(page.getByRole('button', {name: 'Retry saved scan status'})).toBeVisible();
  await expect(page.getByRole('button', {name: 'Start host discovery scan'})).toBeDisabled();
  expect(state.starts).toBe(0);

  state.status = 'running';
  await page.getByRole('button', {name: 'Retry saved scan status'}).click();
  await expect(page.getByText(/Could not refresh the saved scan status/)).toHaveCount(0);
  await expect(page.getByRole('heading', {name: 'Scan status: running'})).toBeVisible();
  expect(state.starts).toBe(0);
});
