import test from 'node:test';
import assert from 'node:assert/strict';

import {
  HOST_MATCH_FILTERS,
  SERVICE_MATCH_FILTERS,
  candidateCount,
  filterHostRows,
  filterServiceRows,
  primaryCandidate,
  scanIsTerminal,
  summarizeNetworkComparison,
} from '../src/lib/networkDiscovery.js';

const hosts = [
  {ip: '192.168.1.16', hostname: 'pi.hole', classification: 'matched',
    evidence: ['IP address', 'hostname'],
    candidates: [{type: 'hardware', id: 3, name: 'PiHole Main', category: 'Physical host',
      evidence: ['IP address', 'hostname']}],
    service_candidates: []},
  {ip: '192.168.1.80', hostname: 'traefik.smitharend.com', classification: 'shared',
    evidence: ['IP address'],
    candidates: [
      {type: 'hardware', id: 1, name: 'Betty', category: 'Physical host', evidence: ['IP address']},
      {type: 'vms', id: 2, name: 'Docker', category: 'VM / runtime', evidence: ['IP address']},
    ],
    service_candidates: [{type: 'apps', id: 7, name: 'Traefik', category: 'Application / service',
      port: 443, evidence: ['parent IP']}]},
  {ip: '192.168.1.200', classification: 'plausible', evidence: ['application IP'],
    candidates: [{type: 'apps', id: 8, name: 'Portainer', category: 'Application / service',
      evidence: ['application IP']}], service_candidates: []},
  {ip: '192.168.1.55', classification: 'ambiguous', evidence: [],
    candidates: [{type: 'misc', id: 9, name: 'Shared endpoint', category: 'Other device',
      evidence: []}], service_candidates: []},
  {ip: '192.168.1.99', classification: 'unverified', evidence: ['IP address'],
    candidates: [], service_candidates: []},
];

const services = [
  {ip: '192.168.1.16', port: 80, hostname: 'pi.hole', service_name: 'http',
    classification: 'plausible', evidence: ['parent IP'],
    candidates: [{type: 'apps', id: 4, name: 'Pi-hole Admin', category: 'Application / service',
      evidence: ['parent IP']}]},
  {ip: '192.168.1.200', port: 9443, service_name: 'https', classification: 'matched',
    evidence: ['application IP'],
    candidates: [{type: 'apps', id: 8, name: 'Portainer', category: 'Application / service',
      evidence: ['application IP']}]},
  {ip: '192.168.1.55', port: 443, service_name: 'https', classification: 'ambiguous',
    evidence: [], candidates: []},
];

test('host filters expose all matching categories and apply search to candidate names', () => {
  assert.deepEqual(HOST_MATCH_FILTERS.map(item => item.value),
    ['all', 'matched', 'plausible', 'shared', 'ambiguous', 'unmatched', 'unverified']);
  assert.deepEqual(filterHostRows(hosts, 'matched').map(row => row.ip), ['192.168.1.16']);
  assert.deepEqual(filterHostRows(hosts, 'shared').map(row => row.ip), ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', 'betty').map(row => row.ip), ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', 'traefik').map(row => row.ip), ['192.168.1.80']);
  assert.deepEqual(filterHostRows(hosts, 'all', 'portainer').map(row => row.ip), ['192.168.1.200']);
  assert.deepEqual(filterHostRows(hosts, 'matched', 'portainer'), []);
  assert.deepEqual(filterHostRows(hosts, 'all', '192.168.1.200').map(row => row.ip),
    ['192.168.1.200']);
});

test('service filters separate endpoint matches and support search', () => {
  assert.deepEqual(SERVICE_MATCH_FILTERS.map(item => item.value),
    ['all', 'matched', 'plausible', 'ambiguous', 'unmatched', 'unverified']);
  assert.deepEqual(filterServiceRows(services, 'matched').map(row => row.port), [9443]);
  assert.deepEqual(filterServiceRows(services, 'plausible').map(row => row.port), [80]);
  assert.deepEqual(filterServiceRows(services, 'all', 'pi-hole').map(row => row.port), [80]);
  assert.deepEqual(filterServiceRows(services, 'all', 'https').map(row => row.port), [9443, 443]);
  assert.deepEqual(filterServiceRows(services, 'ambiguous', 'https').map(row => row.port), [443]);
});

test('primary candidate and candidate count include services on a host address', () => {
  assert.equal(primaryCandidate(hosts[0]).name, 'PiHole Main');
  assert.equal(primaryCandidate(hosts[4]), null);
  assert.equal(candidateCount(hosts[0]), 1);
  assert.equal(candidateCount(hosts[1]), 3);
});

test('summary uses server counts when present and otherwise derives them', () => {
  const explicit = {hosts_discovered: 55, hosts_matched: 2, hosts_plausible: 1,
    hosts_shared: 1, hosts_ambiguous: 1, hosts_unmatched: 50, hosts_unverified: 0,
    services_discovered: 5, services_matched: 1, services_plausible: 2,
    services_ambiguous: 1, services_unmatched: 1, services_unverified: 0};
  assert.equal(summarizeNetworkComparison({summary: explicit, hosts, services}), explicit);
  const derived = summarizeNetworkComparison({hosts, services});
  assert.equal(derived.hosts_discovered, 5);
  assert.equal(derived.hosts_matched, 1);
  assert.equal(derived.hosts_shared, 1);
  assert.equal(derived.hosts_unverified, 1);
  assert.equal(derived.services_discovered, 3);
  assert.equal(derived.services_matched, 1);
  assert.equal(derived.services_plausible, 1);
  assert.equal(derived.hosts_unmatched, 0);
});

test('terminal status is explicit', () => {
  assert.equal(scanIsTerminal('completed'), true);
  assert.equal(scanIsTerminal('partial'), true);
  assert.equal(scanIsTerminal('failed'), true);
  assert.equal(scanIsTerminal('running'), false);
});
