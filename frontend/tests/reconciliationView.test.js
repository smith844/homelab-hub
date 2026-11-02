import test from 'node:test';
import assert from 'node:assert/strict';

import {
  FILTERS,
  changedFieldCount,
  filterClassification,
  filterContainers,
  summarizeReport,
} from '../src/lib/reconciliationView.js';

const rows = [
  {container_name: 'plex', app_name: 'Media Server', classification: 'matched'},
  {container_name: 'old-backup', classification: 'missing_inventory'},
  {container_name: 'legacy-agent', classification: 'excluded'},
  {container_name: 'duplicate-a', classification: 'duplicate'},
  {container_name: 'older-b', app_name: 'Historical App', classification: 'older_observation'},
];

test('filter categories expose the required summary buckets', () => {
  assert.deepEqual(FILTERS.map(item => item.value),
    ['all', 'matched', 'unmatched', 'excluded', 'uncertain']);
  assert.equal(filterClassification('matched'), 'matched');
  assert.equal(filterClassification('missing_inventory'), 'unmatched');
  assert.equal(filterClassification('excluded'), 'excluded');
  assert.equal(filterClassification('duplicate'), 'uncertain');
  assert.equal(filterClassification('older_observation'), 'uncertain');
  assert.equal(filterClassification('something-new'), 'other');
});

test('containers filter by category without dropping detailed results', () => {
  assert.deepEqual(filterContainers(rows, 'all').map(row => row.container_name),
    ['plex', 'old-backup', 'legacy-agent', 'duplicate-a', 'older-b']);
  assert.deepEqual(filterContainers(rows, 'unmatched').map(row => row.container_name),
    ['old-backup']);
  assert.deepEqual(filterContainers(rows, 'excluded').map(row => row.container_name),
    ['legacy-agent']);
  assert.deepEqual(filterContainers(rows, 'uncertain').map(row => row.container_name),
    ['duplicate-a', 'older-b']);
});

test('search is case-insensitive across container and application names', () => {
  assert.deepEqual(filterContainers(rows, 'all', 'PLEX').map(row => row.container_name), ['plex']);
  assert.deepEqual(filterContainers(rows, 'all', 'media').map(row => row.container_name), ['plex']);
  assert.deepEqual(filterContainers(rows, 'uncertain', 'historical').map(row => row.container_name),
    ['older-b']);
  assert.deepEqual(filterContainers(rows, 'matched', 'backup'), []);
});

test('summary falls back to classifications when the server summary is absent', () => {
  assert.deepEqual(summarizeReport({containers: rows, inventory: [{}, {}]}), {
    matched: 1, unmatched: 1, excluded: 1, uncertain: 2, not_seen: 2,
  });
});

test('summary prefers explicit server counts, including empty inventories', () => {
  const summary = {matched: 84, unmatched: 0, excluded: 6, uncertain: 2, not_seen: 0};
  assert.equal(summarizeReport({summary, containers: rows}), summary);
  assert.deepEqual(summarizeReport(null), {
    matched: 0, unmatched: 0, excluded: 0, uncertain: 0, not_seen: 0,
  });
});

test('bulk preview counts only fields whose values change', () => {
  const plan = {applications: [
    {fields: [
      {field: 'container_id', before: 'a', after: 'b'},
      {field: 'image_id', before: 'same', after: 'same'},
      {field: 'image', before: null, after: 'plex:new'},
      {field: 'observed_at', before: 'old', after: 'new'},
    ]},
    {fields: [{field: 'container_id', before: null, after: ''}]},
  ]};
  assert.equal(changedFieldCount(plan), 3);
  assert.equal(changedFieldCount(null), 0);
});
