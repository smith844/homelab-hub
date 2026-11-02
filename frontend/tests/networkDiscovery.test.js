import test from 'node:test';
import assert from 'node:assert/strict';

import {
  COMPARISON_FILTERS,
  comparisonCategory,
  discoveryCategories,
  filterComparisonRows,
  filterScanRows,
  scanIsTerminal,
  summarizeScan,
} from '../src/lib/networkDiscovery.js';

const comparisonRows = [
  {ip: '192.168.1.20', port: 443, name: 'Admin UI', classification: 'matched',
    matches: [{name: 'Admin UI'}]},
  {ip: '192.168.1.21', port: 80, name: 'Unknown web', classification: 'unmatched', matches: []},
  {ip: '192.168.1.22', port: 22, name: 'Duplicate host', classification: 'duplicate', matches: []},
  {ip: '192.168.1.23', port: 443, name: 'Partial probe', classification: 'unverified', matches: []},
];

test('comparison filters distinguish matched, unmatched and uncertain results', () => {
  assert.deepEqual(COMPARISON_FILTERS.map(item => item.value),
    ['all', 'matched', 'unmatched', 'uncertain', 'unknown']);
  assert.equal(comparisonCategory('matched'), 'matched');
  assert.equal(comparisonCategory('unmatched'), 'unmatched');
  assert.equal(comparisonCategory('duplicate'), 'uncertain');
  assert.equal(comparisonCategory('unverified'), 'uncertain');
  assert.equal(comparisonCategory('new-classification'), 'other');
  assert.deepEqual(filterComparisonRows(comparisonRows, 'matched').map(row => row.ip),
    ['192.168.1.20']);
  assert.deepEqual(filterComparisonRows(comparisonRows, 'uncertain').map(row => row.ip),
    ['192.168.1.22', '192.168.1.23']);
  assert.deepEqual(filterComparisonRows(comparisonRows, 'unknown'),
    filterComparisonRows(comparisonRows, 'all').filter(row =>
      comparisonCategory(row.classification) === 'other'));
});

test('comparison search covers endpoint, service name and inventory candidates', () => {
  assert.deepEqual(filterComparisonRows(comparisonRows, 'all', '443').map(row => row.ip),
    ['192.168.1.20', '192.168.1.23']);
  assert.deepEqual(filterComparisonRows(comparisonRows, 'all', 'admin').map(row => row.ip),
    ['192.168.1.20']);
  assert.deepEqual(filterComparisonRows(comparisonRows, 'matched', 'unknown'), []);
});

test('raw scan filtering covers host identity and service metadata', () => {
  const rows = [
    {ip: '192.168.1.20', hostname: 'nas.lan', mac: 'AA:BB:CC:DD:EE:FF', vendor: 'Acme',
      port: 445, service_name: 'microsoft-ds', service_version: 'Windows'},
    {ip: '192.168.1.30', hostname: 'camera.lan', mac: '', vendor: 'Hikvision',
      port: 443, service_name: 'https', service_version: ''},
  ];
  assert.deepEqual(filterScanRows(rows, 'nas').map(row => row.ip), ['192.168.1.20']);
  assert.deepEqual(filterScanRows(rows, 'AA:BB').map(row => row.ip), ['192.168.1.20']);
  assert.deepEqual(filterScanRows(rows, 'hikvision').map(row => row.ip), ['192.168.1.30']);
  assert.deepEqual(filterScanRows(rows, '443').map(row => row.ip), ['192.168.1.30']);
  assert.deepEqual(filterScanRows(rows, ''), rows);
});

test('scan summary reports counts without treating partial output as complete', () => {
  assert.deepEqual(summarizeScan(null), {
    status: 'idle', hosts: 0, services: 0, hosts_up: 0, hosts_down: 0, warnings: 0, complete: false,
  });
  const summary = summarizeScan({
    status: 'partial', complete: false, hosts_up: 2, hosts_down: 254,
    hosts: [{ip: '192.168.1.20'}, {ip: '192.168.1.21'}],
    results: [{ip: '192.168.1.20', port: 443}, {ip: '192.168.1.20', port: 80}],
    warnings: ['timeout'],
  });
  assert.deepEqual(summary, {
    status: 'partial', hosts: 2, services: 2, hosts_up: 2, hosts_down: 254,
    warnings: 1, complete: false,
  });
  assert.equal(scanIsTerminal('completed'), true);
  assert.equal(scanIsTerminal('partial'), true);
  assert.equal(scanIsTerminal('failed'), true);
  assert.equal(scanIsTerminal('running'), false);
});

test('discovery category counts power compact comparison summaries', () => {
  assert.deepEqual(discoveryCategories(comparisonRows), {
    matched: 1, unmatched: 1, uncertain: 2, other: 0,
  });
});
