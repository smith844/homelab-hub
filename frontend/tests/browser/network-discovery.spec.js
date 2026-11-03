import {test, expect} from '@playwright/test';
import {readFileSync} from 'node:fs';

test('network discovery reconciles across the whole inventory and stays read-only', async ({page}) => {
  let starts = 0, reconciliations = 0, refreshes = 0, scanRequest, reconcileRequest;
  const scanId = '12345678-1234-1234-1234-123456789abc';
  const completedScan = {
    scan_id: scanId, type: 'portscan', scan_type: 'services', status: 'completed',
    progress: 100, target: '192.168.1.0/24',
    params: {target: '192.168.1.0/24', ports: '443,80'},
    started_at: '2026-11-02T18:00:00Z', completed_at: '2026-11-02T18:00:05Z',
    hosts_up: 4, hosts_down: 252, result_count: 2, complete: true, error: null,
    warnings: ['A fixture warning'],
    hosts: [
      {ip: '192.168.1.16', hostname: 'pi.hole', mac: '', vendor: '', os: '', open_ports: 1},
      {ip: '192.168.1.80', hostname: 'traefik.smitharend.com', mac: '', vendor: '',
        os: '', open_ports: 1},
      {ip: '192.168.1.200', hostname: '', mac: '', vendor: '', os: '', open_ports: 1},
      {ip: '192.168.1.70', hostname: '', mac: '', vendor: '', os: '', open_ports: 0},
    ],
    results: [
      {ip: '192.168.1.16', port: 80, protocol: 'tcp', state: 'open',
        service_name: 'http', service_version: '', hostname: 'pi.hole', mac: '', vendor: ''},
      {ip: '192.168.1.200', port: 9443, protocol: 'tcp', state: 'open',
        service_name: 'https', service_version: '', hostname: '', mac: '', vendor: ''},
    ],
  };
  const candidates = {
    pihole: {type: 'hardware', id: 3, name: 'PiHole Main', category: 'Physical host',
      parent: null, ip: '192.168.1.16', port: null, evidence: ['IP address', 'hostname']},
    betty: {type: 'hardware', id: 1, name: 'Betty', category: 'Physical host',
      parent: null, ip: '192.168.1.80', port: null, evidence: ['IP address']},
    docker: {type: 'vms', id: 2, name: 'Docker', category: 'VM / runtime',
      parent: {type: 'hardware', id: 1, name: 'Betty'}, ip: '192.168.1.80', port: null,
      evidence: ['IP address']},
    portainer: {type: 'apps', id: 8, name: 'Portainer', category: 'Application / service',
      parent: null, ip: '192.168.1.200', port: 9443, evidence: ['application IP']},
    piholeAdmin: {type: 'apps', id: 4, name: 'Pi-hole Admin', category: 'Application / service',
      parent: {type: 'hardware', id: 3, name: 'PiHole Main'}, ip: '192.168.1.16', port: 80,
      evidence: ['parent IP']},
    phone: {type: 'apps', id: 30, name: 'Phone service', category: 'Application / service',
      parent: null, ip: '192.168.1.77', port: 443, evidence: ['application IP']},
  };
  const bettyServices = Array.from({length: 12}, (_, index) => ({
    type: 'apps', id: 100 + index, name: `Betty Service ${index}`,
    category: 'Application / service',
    parent: {type: 'vms', id: 2, name: 'Docker'}, ip: '192.168.1.80',
    port: 8000 + index, evidence: ['parent IP'],
  }));
  const unifiStatus = {
    configured: true, has_data: true, last_success: '2026-11-03T10:00:00Z',
    last_attempt: '2026-11-03T10:00:00Z', stale: false, error: null,
    version: '9.1.120', site: {id: 'site-1', name: 'Default'},
    infrastructure_devices: 2, clients: 3, current_clients: 2, historical_clients: 1,
    online_devices: 2, offline_devices: 0,
  };
  const comparison = {
    source: 'nmap',
    sources: ['nmap', 'unifi'],
    scan: {type: 'portscan', status: 'completed', target: '192.168.1.0/24',
      completed_at: '2026-11-02T18:00:05Z', uncertain: false, warnings: []},
    hosts: [
      {ip: '192.168.1.16', hostname: 'pi.hole', mac: '', vendor: '', os: '', open_ports: 1,
        classification: 'matched', sources: ['nmap'],
        reason: 'Exact IP/MAC evidence in inventory.',
        evidence: ['IP address', 'hostname'], candidates: [candidates.pihole],
        service_candidates: [candidates.piholeAdmin],
        network: {id: 1, name: 'LAN', vlan_id: 1}},
      {ip: '192.168.1.80', hostname: 'traefik.smitharend.com', mac: '', vendor: '', os: '',
        open_ports: 1, classification: 'shared',
        sources: ['nmap', 'unifi'],
        reason: 'Host and its VM/runtime share this address; treated as one endpoint, not duplicate physical devices.',
        evidence: ['IP address', 'UniFi MAC'],
        candidates: [candidates.betty, candidates.docker],
        service_candidates: bettyServices,
        unifi_matches: [{name: 'Betty', kind: 'client', online: true,
          mac: 'aa:bb:cc:dd:ee:01', ip: '192.168.1.80',
          network: {name: 'LAN', vlan_id: 1}, last_seen: null,
          hostname: '', device_type: 'wired', state: 'ONLINE'}],
        network: {id: 1, name: 'LAN', vlan_id: 1}},
      {ip: '192.168.1.200', hostname: '', mac: '', vendor: '', os: '', open_ports: 1,
        classification: 'plausible', sources: ['nmap'],
        reason: 'Only application/service endpoints match this address; no physical device record.',
        evidence: ['application IP'], candidates: [candidates.portainer],
        service_candidates: [],
        network: {id: 1, name: 'LAN', vlan_id: 1}},
      {ip: '192.168.1.70', hostname: '', mac: '', vendor: '', os: '', open_ports: 0,
        classification: 'unmatched', sources: ['nmap'],
        reason: 'No reliable inventory match; this does not establish that a device is absent.',
        evidence: [], candidates: [], service_candidates: [], network: null},
    ],
    services: [
      {ip: '192.168.1.16', port: 80, hostname: 'pi.hole', service_name: 'http',
        service_version: '', classification: 'plausible',
        reason: 'Application has no explicit IP; it inherits the parent address for this port.',
        evidence: ['parent IP'], candidates: [candidates.piholeAdmin]},
      {ip: '192.168.1.200', port: 9443, hostname: '', service_name: 'https',
        service_version: '', classification: 'matched',
        reason: 'Explicit application IP and TCP port match.',
        evidence: ['application IP'], candidates: [candidates.portainer]},
    ],
    unifi_only: [
      {ip: '192.168.1.77', hostname: '', classification: 'matched', sources: ['unifi'],
        unifi_only: true, device_type: 'wireless', online: true,
        last_seen: '2026-11-03T09:58:00Z', network: {name: 'LAN', vlan_id: 1},
        evidence: ['application IP', 'UniFi MAC'],
        candidates: [candidates.phone], service_candidates: [],
        unifi_matches: [{name: 'My phone', kind: 'client', online: true,
          mac: 'aa:bb:cc:dd:ee:77', ip: '192.168.1.77', network: null,
          hostname: '', device_type: 'wireless', state: 'ONLINE'}],
        reason: 'UniFi-only known device; it was not observed in the current Nmap scan.'},
    ],
    unifi: unifiStatus,
    summary: {
      hosts_discovered: 4, hosts_matched: 1, hosts_plausible: 1, hosts_shared: 1,
      hosts_ambiguous: 0, hosts_unmatched: 1, hosts_unverified: 0,
      services_discovered: 2, services_matched: 1, services_plausible: 1,
      services_ambiguous: 0, services_unmatched: 0, services_unverified: 0,
      inventory_devices: 4, inventory_services: 3,
      unifi_infrastructure_devices: 2, unifi_clients: 3, unifi_current_clients: 2,
      unifi_historical_clients: 1, unifi_only: 1, nmap_hosts_with_unifi: 1,
      unifi_source_conflicts: 0,
    },
    reason: 'Read-only network-wide comparison across hardware, VMs, other devices, application endpoints and network memberships.',
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
    if (request.method() === 'GET' && path === '/api/network-discovery/unifi/status') {
      return route.fulfill({json: {unifi: unifiStatus}});
    }
    if (request.method() === 'POST' && path === '/api/network-discovery/unifi/refresh') {
      refreshes++;
      expect(request.headers()['x-admin-token']).toBe('browser-fixture-only');
      return route.fulfill({json: {unifi: {...unifiStatus, last_success: '2026-11-03T10:05:00Z'}}});
    }
    if (request.method() === 'POST' && path === '/api/network-discovery/scan') {
      starts++;
      scanRequest = {body: request.postDataJSON(), token: request.headers()['x-admin-token']};
      return route.fulfill({status: 202, json: {scan: {...completedScan, status: 'running', complete: false}}});
    }
    if (request.method() === 'GET' && path === `/api/network-discovery/scan/${scanId}`) {
      return route.fulfill({json: {scan: completedScan}});
    }
    if (request.method() === 'POST' && path === '/api/network-discovery/reconcile') {
      reconciliations++;
      expect(request.headers()['x-admin-token']).toBe('browser-fixture-only');
      reconcileRequest = request.postDataJSON();
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
  await expect(page.getByRole('heading', {name: 'Network-wide inventory matching'})).toBeVisible();
  await expect(page.getByRole('heading', {name: 'UniFi integration'})).toBeVisible();
  await expect(page.getByText('2 infrastructure devices')).toBeVisible();
  await expect(page.getByText('1 Nmap hosts with UniFi evidence')).toBeVisible();
  await expect(page.getByRole('heading', {name: /UniFi-only known devices/})).toBeVisible();
  await expect(page.getByText('Last successful refresh: 2026-11-03T10:00:00Z')).toBeVisible();
  expect(starts).toBe(1);
  expect(scanRequest.token).toBe('browser-fixture-only');
  expect(scanRequest.body).toEqual({target: '192.168.1.0/24', scan_type: 'services', ports: '443,80'});
  expect(reconciliations).toBe(1);
  expect(reconcileRequest.scan.scan_id).toBe(scanId);

  const hostSummary = page.getByRole('region', {name: 'Host match summary'});
  await expect(hostSummary).toContainText('1 Matched');
  await expect(hostSummary).toContainText('1 Plausible');
  await expect(hostSummary).toContainText('1 Shared');
  await expect(hostSummary).toContainText('1 Unmatched');
  const serviceSummary = page.getByRole('region', {name: 'Service match summary'});
  await expect(serviceSummary).toContainText('1 Matched');
  await expect(serviceSummary).toContainText('1 Plausible');

  await expect(page.getByText('PiHole Main', {exact: true}).first()).toBeVisible();
  await expect(page.getByText('Portainer', {exact: true}).first()).toBeVisible();
  await expect(page.getByRole('cell', {name: /^Shared endpoint/})).toBeVisible();
  await expect(page.getByText(/No reliable inventory match/).first()).toBeVisible();

  const hostTable = page.locator('.matching-table').first();
  await page.getByLabel('Host match filter').selectOption('shared');
  await expect(hostTable.getByText('traefik.smitharend.com')).toBeVisible();
  await expect(hostTable.getByText('pi.hole', {exact: true})).toHaveCount(0);
  await page.getByLabel('Host match filter').selectOption('all');

  const sharedCandidates = page.locator('details.candidates').filter({hasText: 'Betty'}).first();
  await sharedCandidates.locator('summary').click();
  await expect(sharedCandidates.getByText('Docker', {exact: true})).toBeVisible();
  await expect(sharedCandidates.getByText('Applications / services (12)', {exact: true})).toBeVisible();
  const appFilter = sharedCandidates.getByLabel('Filter services for 192.168.1.80');
  await appFilter.fill('Betty Service 0');
  await expect(sharedCandidates.getByText('Betty Service 0', {exact: true})).toBeVisible();
  await expect(sharedCandidates.getByText('Betty Service 1', {exact: true})).toHaveCount(0);
  await appFilter.fill('');

  await page.getByLabel('Observation source filter').selectOption('both');
  await expect(hostTable.getByText('traefik.smitharend.com')).toBeVisible();
  await expect(hostTable.getByText('pi.hole', {exact: true})).toHaveCount(0);
  await page.getByLabel('Observation source filter').selectOption('all');

  await page.getByLabel('Network filter').selectOption('LAN');
  await expect(hostTable.getByText('traefik.smitharend.com')).toBeVisible();
  await expect(hostTable.getByText('192.168.1.70')).toHaveCount(0);
  await page.getByLabel('Network filter').selectOption('');

  await page.getByLabel('UniFi state filter').selectOption('online');
  await expect(page.getByText('My phone', {exact: true})).toBeVisible();
  await page.getByLabel('UniFi state filter').selectOption('all');

  await page.getByLabel('Search network matching').fill('Portainer');
  await expect(page.getByText('192.168.1.200:9443')).toBeVisible();
  await expect(page.getByText('192.168.1.16:80')).toHaveCount(0);
  await page.getByLabel('Service match filter').selectOption('matched');
  await expect(page.getByText('192.168.1.200:9443')).toBeVisible();
  await page.getByLabel('Search network matching').fill('');
  await page.getByLabel('Service match filter').selectOption('all');
  await page.getByRole('button', {name: 'Refresh UniFi observations'}).click();
  expect(refreshes).toBe(1);
  expect(starts).toBe(1);
  await expect.poll(() => reconciliations).toBe(2);
  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/hlh-network-wide-matching.png`, fullPage: true});
  await page.setViewportSize({width: 700, height: 900});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
  await page.screenshot({path: `${process.env.TEMP || '/tmp'}/hlh-network-wide-matching-narrow.png`, fullPage: true});
});

for (const theme of ['light', 'dark']) {
  test(`${theme}: UniFi unconfigured and stale/error states stay explicit`, async ({page}) => {
    let unifiStatus = {configured: false, has_data: false, last_success: null,
      stale: true, error: null};

    await page.addInitScript(value => localStorage.setItem('hlh.theme', JSON.stringify(value)), theme);
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
      if (request.method() === 'GET' && path === '/api/network-discovery/unifi/status') {
        return route.fulfill({json: {unifi: unifiStatus}});
      }
      return route.fulfill({status: 404, json: {error: 'must not be called'}});
    });

    await page.goto('/#/network-discovery');
    await expect(page.getByRole('heading', {name: 'Network discovery'})).toBeVisible();
    await expect(page.getByText('UniFi is not configured.')).toBeVisible();
    await expect(page.getByRole('button', {name: 'Refresh UniFi observations'})).toBeDisabled();

    unifiStatus = {configured: true, has_data: true,
      last_success: '2026-11-02T10:00:00Z', stale: true,
      error: 'UniFi controller is unreachable or TLS verification failed',
      infrastructure_devices: 1, clients: 0, current_clients: 0, historical_clients: 0};
    await page.reload();
    await expect(page.getByText(/UniFi controller is unreachable/)).toBeVisible();
    await expect(page.getByText('Stale')).toBeVisible();
    await expect(page.getByRole('button', {name: 'Refresh UniFi observations'})).toBeDisabled();
    await page.screenshot({path: `${process.env.TEMP || '/tmp'}/hlh-unifi-${theme}.png`, fullPage: true});
  });
}
