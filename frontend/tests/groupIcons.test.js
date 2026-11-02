import test from 'node:test';
import assert from 'node:assert/strict';
import { groupIcon } from '../src/lib/groupIcons.js';
import { buildGroupedGraph } from '../src/lib/grouping.js';

test('group icons accept HTTP(S) and raster data images', () => {
  for (const url of ['https://example.org/icon.png', 'http://example.org/icon.webp', 'data:image/png;base64,aGVsbG8=']) {
    assert.equal(groupIcon(url).image, url);
    assert.equal(groupIcon(url).text, '');
  }
  assert.equal(groupIcon('🔧').text, '🔧');
});

test('group icons reject active content, credentials and malformed URLs', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html;base64,aA==', 'data:image/svg+xml;base64,aA==', '<img onerror=x>', '//evil.org/a.png', 'https://user:password@example.org/x', 'https://', 'file:///tmp/x', 'x'.repeat(100)]) {
    assert.deepEqual(groupIcon(value), { image: '', text: '📁' });
  }
  assert.equal(groupIcon(null).text, '📁');
});

test('grouped image icons are image data with a readable fallback label', () => {
  const graph = { nodes: [{data: {id: 'apps-1', type: 'apps', entity_id: 1, label: 'Plex'}}], edges: [] };
  const grouping = { groups: [{id: 7, name: 'Media', icon: 'https://example.org/icon.png', host_key: 'betty'}], memberships: [{group_id: 7, app_id: 1, host_key: 'betty'}] };
  const grouped = buildGroupedGraph(graph, grouping);
  const group = grouped.nodes.find(node => node.data.type === 'group').data;
  assert.equal(group.groupImage, 'https://example.org/icon.png');
  assert.match(group.label, /Media/);
  assert.doesNotMatch(group.label, /https:/);
  grouping.groups[0].icon = 'javascript:alert(1)';
  const rejected = buildGroupedGraph(graph, grouping).nodes.find(node => node.data.type === 'group').data;
  assert.equal(rejected.groupImage, undefined);
  assert.match(rejected.label, /📁/);
});
