import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEVICE_TYPE_FILTERS,
  HOST_MATCH_FILTERS,
  SERVICE_MATCH_FILTERS,
  SOURCE_FILTERS,
  UNIFI_STATE_FILTERS,
  candidateGroups,
  deviceIdentityCount,
  filterCandidates,
  filterHostRows,
  filterServiceRows,
  filterUnifiOnlyRows,
  hostSourceCategory,
  networkLabel,
  networksFromResult,
  primaryIdentity,
  scanIsTerminal,
  serviceIdentityCount,
  summarizeNetworkComparison,
  unifiState,
} from '../src/lib/networkDiscovery.js';

const app = (id, name, port = null) => ({
  type: 'apps', id, name, category: 'Application / service', port, evidence: ['parent IP'],
});
const physical = (id, name) => ({
  type: 'hardware', id, name, category: 'Physical host', evidence: ['IP address'],
});
const runtime = (id, name, parent) => ({
  type: 'vms', id, name, category: 'VM / runtime',
  parent: {type: 'hardware', id: parent.id, name: parent.name}, evidence: ['IP address'],
});

const betty = physical(1, 'Betty');
const docker = runtime(2, 'Docker', betty);
const hosts = [
  {ip: '192.168.1.16', hostname: 'pi.hole', classification: 'matched', sources: ['nmap'],
    evidence: ['IP address', 'hostname'], candidates: [physical(3, 'PiHole Main')],
    service_candidates: [app(4, 'Pi-hole Admin', 80)],
    network: {name: 'LAN', vlan_id: 1}},
  {ip: '192.168.1.80', hostname: 'traefik.smitharend.com', classification: 'shared',
    sources: ['nmap', 'unifi'], evidence: ['IP address', 'UniFi MAC'],
    candidates: [betty, docker],
    service_candidates: Array.from({length: 87}, (_, index) => app(100 + index, `Service ${index}`, 8000 + index)),
    unifi_matches: [{name: 'Betty', kind: 'client', online: true, mac: 'aa:bb:cc:dd:ee:01',
      network: {name: 'LAN', vlan_id: 1}, last_seen: null}],
    network: {name: 'LAN', vlan_id: 1}},
  {ip: '192.168.1.200', classification: 'plausible', sources: ['nmap'],
    evidence: ['application IP'], candidates: [app(8, 'Portainer', 9443)],
    service_candidates: [], network: {name: 'LAN', vlan_id: 1}},
  {ip: '192.168.1.55', classification: 'ambiguous', sources: ['nmap'],
    evidence: [], candidates: [], service_candidates: [], network: null},
  {ip: '192.168.1.99', classification: 'unverified', sources: ['nmap'],
    evidence: [], candidates: [], service_candidates: [], network: null},
];

const services = [
  {ip: '192.168.1.16', port: 80, hostname: 'pi.hole', service_name: 'http',
    classification: 'plausible', evidence: ['parent IP'], candidates: [app(4, 'Pi-hole Admin', 80)]},
  {ip: '192.168.1.200', port: 9443, service_name: 'https', classification: 'matched',
    evidence: ['application IP'], candidates: [app(8, 'Portainer', 9443)]},
  {ip: '192.168.1.55', port: 443, service_name: 'https', classification: 'ambiguous',
    evidence: [], candidates: []},
];

const unifiOnly = [
  {ip: '192.168.1.77', hostname: '', classification: 'matched', online: true,
    sources: ['unifi'], unifi_only: true, device_type: 'wireless',
    network: {name: 'LAN', vlan_id: 1}, candidates: [physical(9, 'Phone owner')],
    service_candidates: [], unifi_matches: [{name: 'My Phone', online: true, kind: 'client'}]},
  {ip: '192.168.1.88', hostname: '', classification: 'unmatched', online: false,
    sources: ['unifi'], unifi_only: true, device_type: 'wireless',
    network: {name: 'IoT', vlan_id: 20}, candidates: [], service_candidates: [],
    unifi_matches: [{name: 'Old phone', online: false, kind: 'client'}]},
];

test('host filters expose matching categories and source/state/type controls', () => {
  assert.deepEqual(HOST_MATCH_FILTERS.map(item => item.value),
    ['all', 'matched', 'plausible', 'shared', 'ambiguous', 'unmatched', 'unverified']);
  assert.deepEqual(filterHostRows(hosts, 'matched').map(row => row.ip), ['192.168.1.16']);
  assert.deepEqual(filterHostRows(hosts, 'shared').map(row => row.ip), ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', 'betty').map(row => row.ip), ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', 'portainer').map(row => row.ip), ['192.168.1.200']);
  assert.deepEqual(filterHostRows(hosts, 'all', '', {source: 'both'}).map(row => row.ip),
    ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', '', {source: 'nmap'}).map(row => row.ip),
    hosts.filter(row => !row.sources.includes('unifi')).map(row => row.ip));
  assert.deepEqual(filterHostRows(hosts, 'all', '', {network: 'LAN'}).map(row => row.ip),
    ['192.168.1.16', '192.168.1.80', '192.168.1.200']);
  assert.deepEqual(filterHostRows(hosts, 'all', '', {state: 'online'}).map(row => row.ip),
    ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', '', {type: 'application'}).map(row => row.ip),
    ['192.168.1.16', '192.168.1.80', '192.168.1.200']);
  assert.deepEqual(filterHostRows(hosts, 'all', '', {type: 'physical'}).map(row => row.ip),
    ['192.168.1.16', '192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', '', {type: 'runtime'}).map(row => row.ip),
    ['192.168.1.80']);
  assert.deepEqual(SOURCE_FILTERS.map(item => item.value), ['all', 'nmap', 'both', 'unifi']);
  assert.deepEqual(UNIFI_STATE_FILTERS.map(item => item.value), ['all', 'online', 'offline', 'unknown']);
  assert.deepEqual(DEVICE_TYPE_FILTERS.map(item => item.value),
    ['all', 'physical', 'runtime', 'application', 'unknown']);
});

test('service filtering and candidate hierarchy keep applications separate from devices', () => {
  assert.deepEqual(SERVICE_MATCH_FILTERS.map(item => item.value),
    ['all', 'matched', 'plausible', 'ambiguous', 'unmatched', 'unverified']);
  assert.deepEqual(filterServiceRows(services, 'matched').map(row => row.port), [9443]);
  assert.deepEqual(filterServiceRows(services, 'all', 'pi-hole').map(row => row.port), [80]);

  const shared = hosts[1];
  const groups = candidateGroups(shared);
  assert.deepEqual(groups.physical.map(item => item.name), ['Betty']);
  assert.deepEqual(groups.runtimes.map(item => item.name), ['Docker']);
  assert.equal(groups.services.length, 87);
  assert.equal(primaryIdentity(shared).name, 'Betty');
  assert.equal(deviceIdentityCount(shared), 2);
  assert.equal(serviceIdentityCount(shared), 87);

  const serviceOnly = hosts[2];
  assert.deepEqual(candidateGroups(serviceOnly).services.map(item => item.name), ['Portainer']);
  assert.equal(primaryIdentity(serviceOnly).name, 'Portainer');
  assert.equal(deviceIdentityCount(serviceOnly), 0);
  assert.equal(serviceIdentityCount(serviceOnly), 1);
});

test('candidate filters keep long application lists navigable', () => {
  const services = candidateGroups(hosts[1]).services;
  assert.equal(filterCandidates(services, 'Service 42').length, 1);
  assert.equal(filterCandidates(services, '80').length > 0, true);
  assert.equal(filterCandidates(services, 'no-such-service').length, 0);
  assert.equal(filterCandidates(services, '').length, 87);
});

test('source, state, network and type filters cover UniFi-only rows', () => {
  assert.equal(hostSourceCategory(hosts[1]), 'both');
  assert.equal(hostSourceCategory(hosts[0]), 'nmap');
  assert.equal(hostSourceCategory(unifiOnly[0]), 'unifi');
  assert.equal(unifiState(hosts[1]), 'online');
  assert.equal(unifiState(hosts[0]), 'unknown');
  assert.equal(networkLabel(unifiOnly[1]), 'IoT · VLAN 20');
  assert.deepEqual(networksFromResult({hosts, unifi_only: unifiOnly}), ['IoT', 'LAN']);
  assert.deepEqual(filterUnifiOnlyRows(unifiOnly, '', 'offline').map(row => row.ip),
    ['192.168.1.88']);
  assert.deepEqual(filterUnifiOnlyRows(unifiOnly, '', 'online').map(row => row.ip),
    ['192.168.1.77']);
  assert.deepEqual(filterUnifiOnlyRows(unifiOnly, 'old', 'all').map(row => row.ip),
    ['192.168.1.88']);
});

test('summary uses server counts when present and otherwise derives them', () => {
  const explicit = {hosts_discovered: 5, hosts_matched: 1, hosts_plausible: 1,
    hosts_shared: 1, hosts_ambiguous: 1, hosts_unmatched: 0, hosts_unverified: 1,
    services_discovered: 3, services_matched: 1, services_plausible: 1,
    services_ambiguous: 1, services_unmatched: 0, services_unverified: 0, unifi_only: 2};
  assert.equal(summarizeNetworkComparison({summary: explicit, hosts, services}), explicit);
  const derived = summarizeNetworkComparison({hosts, services, unifi_only: unifiOnly});
  assert.equal(derived.hosts_discovered, 5);
  assert.equal(derived.hosts_matched, 1);
  assert.equal(derived.hosts_shared, 1);
  assert.equal(derived.services_discovered, 3);
  assert.equal(derived.unifi_only, 2);
});

test('terminal status is explicit', () => {
  assert.equal(scanIsTerminal('completed'), true);
  assert.equal(scanIsTerminal('partial'), true);
  assert.equal(scanIsTerminal('failed'), true);
  assert.equal(scanIsTerminal('running'), false);
});
