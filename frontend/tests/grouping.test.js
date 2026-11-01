import test from 'node:test';
import assert from 'node:assert/strict';
import {
  aggregateEdges,
  buildGroupedGraph,
  groupNodeId,
  groupedLayoutPositions,
  identityKey,
  layoutStorageKey,
  ungroupedNodeId,
} from '../src/lib/grouping.js';

const node = (id, type, name, extra = {}) => ({
  data: { id, type, rawName: name, label: name, entity_id: Number(String(id).split('-').pop()), ...extra },
});
const edge = (id, source, target) => ({ data: { id, source, target } });

function fixture() {
  const filtered = {
    nodes: [
      node('hardware-1', 'hardware', 'Betty'),
      node('hardware-2', 'hardware', 'Blackbox'),
      node('vms-1', 'vms', 'Docker'),
      node('vms-2', 'vms', 'Docker'),
      node('apps-10', 'apps', 'Open-webui'),
      node('apps-11', 'apps', 'Plex'),
      node('apps-12', 'apps', 'Extra App'),
      node('apps-13', 'apps', 'Ollama'),
      node('apps-14', 'apps', 'ComfyUI'),
      node('apps-20', 'apps', 'EmonCMS'),
    ],
    edges: [
      edge('e1', 'hardware-1', 'vms-1'),
      edge('e2', 'hardware-2', 'vms-2'),
      edge('e3', 'vms-1', 'apps-10'),
      edge('e4', 'vms-1', 'apps-11'),
      edge('e5', 'vms-1', 'apps-12'),
      edge('e6', 'vms-1', 'apps-13'),
      edge('e7', 'vms-1', 'apps-14'),
      edge('e8', 'vms-2', 'apps-20'),
      edge('e9', 'apps-10', 'apps-13'),
    ],
  };
  const grouping = {
    groups: [
      { id: 1, name: 'AI', source: 'folderview', host_key: 'betty', color: null, icon: null, sort_order: 0 },
      { id: 2, name: 'Media', source: 'folderview', host_key: 'betty', color: null, icon: null, sort_order: 1 },
      { id: 3, name: 'Monitoring', source: 'folderview', host_key: 'blackbox', color: null, icon: null, sort_order: 0 },
    ],
    memberships: [
      { group_id: 1, host_key: 'betty', host_label: 'Betty', container_key: 'open-webui', container_label: 'open-webui', app_id: 10, match: 'assignment' },
      { group_id: 1, host_key: 'betty', host_label: 'Betty', container_key: 'ollama', container_label: 'ollama', app_id: 13, match: 'assignment' },
      { group_id: 1, host_key: 'betty', host_label: 'Betty', container_key: 'comfyui', container_label: 'comfyui', app_id: 14, match: 'assignment' },
      { group_id: 2, host_key: 'betty', host_label: 'Betty', container_key: 'plex', container_label: 'plex', app_id: 11, match: 'assignment' },
      { group_id: 3, host_key: 'blackbox', host_label: 'Blackbox', container_key: 'emoncms', container_label: 'emoncms', app_id: 20, match: 'assignment' },
    ],
    unmatched: [
      { group_id: 1, host_key: 'betty', host_label: 'Betty', container_key: 'missing-one', container_label: 'missing-one', app_id: null, match: 'assignment' },
    ],
    ungrouped_apps: [
      { app_id: 12, host_key: 'betty', host_label: 'Betty' },
    ],
    unmatched_count: 1,
  };
  return { filtered, grouping };
}

function byId(nodeList, id) {
  return nodeList.find((item) => item.data.id === id);
}

test('identityKey normalises case and whitespace', () => {
  assert.equal(identityKey('  Betty  '), 'betty');
  assert.equal(identityKey('Docker   VM'), 'docker vm');
  assert.equal(identityKey(null), '');
});

test('layout storage keys are independent for Graph and Grouped', () => {
  assert.equal(layoutStorageKey('graph', 'sig'), 'hlh.mapLayout.sig');
  assert.equal(layoutStorageKey('grouped', 'sig'), 'hlh.mapLayoutGrouped.sig');
});

test('grouped graph preserves real ids and adds virtual group nodes', () => {
  const { filtered, grouping } = fixture();
  const before = JSON.stringify(filtered);
  const grouped = buildGroupedGraph(filtered, grouping);

  // Real nodes are preserved, original input is untouched.
  for (const original of filtered.nodes) {
    const copy = byId(grouped.nodes, original.data.id);
    assert.ok(copy, `missing real node ${original.data.id}`);
    assert.equal(copy.data.id, original.data.id);
    assert.equal(copy.data.entity_id, original.data.entity_id);
  }
  assert.equal(JSON.stringify(filtered), before);

  const ai = byId(grouped.nodes, groupNodeId(1, 'betty'));
  assert.equal(ai.data.type, 'group');
  assert.equal(ai.data.kind, 'group');
  assert.equal(ai.data.totalMembers, 4);       // 3 matched + 1 unmatched
  assert.equal(ai.data.visibleMembers, 3);
  assert.equal(ai.data.unmatchedMembers, 1);
  assert.deepEqual(ai.data.unmatchedLabels, ['missing-one']);
  assert.deepEqual(ai.data.memberIds.sort(), ['apps-10', 'apps-13', 'apps-14']);
  assert.equal(ai.data.hostLabel, 'Betty');

  const ungrouped = byId(grouped.nodes, ungroupedNodeId('betty'));
  assert.equal(ungrouped.data.kind, 'ungrouped');
  assert.equal(ungrouped.data.totalMembers, 1);
  assert.deepEqual(ungrouped.data.memberIds, ['apps-12']);

  // Host scoping: Betty and Blackbox groups contain only their own members.
  assert.deepEqual(byId(grouped.nodes, groupNodeId(3, 'blackbox')).data.memberIds, ['apps-20']);
  assert.ok(!byId(grouped.nodes, groupNodeId(3, 'blackbox')).data.memberIds.includes('apps-10'));
});

test('collapse aggregates boundary edges and hides internal ones', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);

  const aggregates = aggregateEdges(grouped, []);
  const keys = aggregates.map((e) => `${e.data.source}->${e.data.target}`).sort();

  assert.deepEqual(keys, [
    `vms-1->ungrouped@betty`,
    `vms-1->${groupNodeId(1, 'betty')}`,
    `vms-1->${groupNodeId(2, 'betty')}`,
    `vms-2->${groupNodeId(3, 'blackbox')}`,
  ].sort());
  // Duplicate member->same outside node connections collapse to one edge.
  assert.equal(
    aggregates.filter((e) => e.data.target === groupNodeId(1, 'betty')).length,
    1
  );
  // Internal edges within one collapsed group are not re-created as aggregates.
  assert.ok(!aggregates.some((e) => e.data.source.includes('group-1') && e.data.target.includes('group-1')));
});

test('expanding a group restores its real edges and leaves other aggregates', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);

  const aggregates = aggregateEdges(grouped, [groupNodeId(1, 'betty')]);
  const keys = aggregates.map((e) => `${e.data.source}->${e.data.target}`);

  assert.ok(!keys.some((key) => key.includes(groupNodeId(1, 'betty'))));
  assert.deepEqual(keys.sort(), [
    `vms-1->ungrouped@betty`,
    `vms-1->${groupNodeId(2, 'betty')}`,
    `vms-2->${groupNodeId(3, 'blackbox')}`,
  ].sort());
});

test('grouped layout is deterministic and places groups beneath their hosts', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);

  const first = groupedLayoutPositions(grouped);
  const second = groupedLayoutPositions(grouped);
  assert.deepEqual(first, second);

  const betty = first['hardware-1'];
  const blackbox = first['hardware-2'];
  const ai = first[groupNodeId(1, 'betty')];
  const media = first[groupNodeId(2, 'betty')];
  const monitoring = first[groupNodeId(3, 'blackbox')];

  // Category cards sit below their host.
  assert.ok(ai.y > betty.y);
  assert.ok(media.y > betty.y);
  assert.ok(monitoring.y > blackbox.y);
  // Hosts are stacked deterministically.
  assert.ok(blackbox.y > betty.y);
  // Members sit near and below their category.
  for (const memberId of ['apps-10', 'apps-13', 'apps-14']) {
    const member = first[memberId];
    assert.ok(member.y > ai.y);
    assert.ok(Math.abs(member.x - ai.x) <= 400);
  }
  // Group cards and labels do not overlap (cards are 220x92).
  const cards = [ai, media, monitoring];
  for (let i = 0; i < cards.length; i += 1) {
    for (let j = i + 1; j < cards.length; j += 1) {
      const dx = Math.abs(cards[i].x - cards[j].x);
      const dy = Math.abs(cards[i].y - cards[j].y);
      assert.ok(dx >= 220 || dy >= 92, `cards ${i}/${j} overlap`);
    }
  }
});

test('layout never mutates the input graph', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const before = JSON.stringify(grouped);
  groupedLayoutPositions(grouped);
  assert.equal(JSON.stringify(grouped), before);
});

test('groups with no visible members are omitted', () => {
  const { filtered, grouping } = fixture();
  const onlyBlackbox = {
    nodes: filtered.nodes.filter((n) => ['hardware-2', 'vms-2', 'apps-20'].includes(n.data.id)),
    edges: filtered.edges.filter((e) => ['hardware-2', 'vms-2', 'apps-20'].includes(e.data.source)),
  };
  const grouped = buildGroupedGraph(onlyBlackbox, grouping);

  assert.ok(byId(grouped.nodes, groupNodeId(3, 'blackbox')));
  assert.equal(byId(grouped.nodes, groupNodeId(1, 'betty')), undefined);
  assert.equal(byId(grouped.nodes, ungroupedNodeId('betty')), undefined);
});

test('groups with only not-in-inventory members remain visible', () => {
  const { filtered, grouping } = fixture();
  const ghostGrouping = {
    ...grouping,
    groups: [
      ...grouping.groups,
      { id: 4, name: 'Ghost', source: 'folderview', host_key: 'betty', color: null, icon: null, sort_order: 9 },
    ],
    unmatched: [
      ...grouping.unmatched,
      {
        group_id: 4,
        host_key: 'betty',
        host_label: 'Betty',
        container_key: 'ghost-app',
        container_label: 'ghost-app',
        app_id: null,
        match: 'assignment',
      },
    ],
  };
  const grouped = buildGroupedGraph(filtered, ghostGrouping);
  const ghost = byId(grouped.nodes, groupNodeId(4, 'betty'));

  assert.ok(ghost);
  assert.equal(ghost.data.visibleMembers, 0);
  assert.equal(ghost.data.unmatchedMembers, 1);
  assert.equal(ghost.data.totalMembers, 1);
  assert.ok(groupedLayoutPositions(grouped)[groupNodeId(4, 'betty')]);
});

test('large grouped layouts position every node without card overlap', () => {
  const nodes = [node('hardware-1', 'hardware', 'Betty'), node('vms-1', 'vms', 'Docker')];
  const edges = [edge('e0', 'hardware-1', 'vms-1')];
  const groups = [];
  const memberships = [];
  const ungroupedApps = [];
  for (let groupIndex = 0; groupIndex < 14; groupIndex += 1) {
    groups.push({
      id: groupIndex + 1,
      name: `Group ${groupIndex + 1}`,
      source: 'folderview',
      host_key: 'betty',
      sort_order: groupIndex,
    });
    for (let memberIndex = 0; memberIndex < 6; memberIndex += 1) {
      const appId = 100 + groupIndex * 6 + memberIndex;
      nodes.push(node(`apps-${appId}`, 'apps', `App ${appId}`));
      edges.push(edge(`e-${appId}`, 'vms-1', `apps-${appId}`));
      memberships.push({
        group_id: groupIndex + 1,
        host_key: 'betty',
        host_label: 'Betty',
        container_key: `app-${appId}`,
        container_label: `App ${appId}`,
        app_id: appId,
        match: 'assignment',
      });
    }
  }
  for (let index = 0; index < 11; index += 1) {
    const appId = 500 + index;
    nodes.push(node(`apps-${appId}`, 'apps', `Extra ${appId}`));
    edges.push(edge(`e-${appId}`, 'vms-1', `apps-${appId}`));
    ungroupedApps.push({ app_id: appId, host_key: 'betty', host_label: 'Betty' });
  }

  const filtered = { nodes, edges };
  const grouping = {
    groups,
    memberships,
    unmatched: [],
    ungrouped_apps: ungroupedApps,
    unmatched_count: 0,
  };
  const grouped = buildGroupedGraph(filtered, grouping);
  const positions = groupedLayoutPositions(grouped);

  assert.equal(Object.keys(positions).length, grouped.nodes.length);
  const cards = grouped.nodes.filter((item) => item.data.type === 'group');
  assert.equal(cards.length, 15); // 14 groups + ungrouped
  for (let i = 0; i < cards.length; i += 1) {
    for (let j = i + 1; j < cards.length; j += 1) {
      const a = positions[cards[i].data.id];
      const b = positions[cards[j].data.id];
      const dx = Math.abs(a.x - b.x);
      const dy = Math.abs(a.y - b.y);
      assert.ok(dx >= 220 || dy >= 92, `cards ${cards[i].data.id}/${cards[j].data.id} overlap`);
    }
  }
  // Every app member is positioned below its category card.
  for (const group of cards) {
    const card = positions[group.data.id];
    for (const memberId of group.data.memberIds) {
      assert.ok(positions[memberId].y > card.y);
    }
  }
});

test('manual groups without a host are scoped by their members', () => {
  const { filtered } = fixture();
  const grouping = {
    groups: [
      { id: 9, name: 'Shared', source: 'manual', host_key: null, color: null, icon: null, sort_order: 0 },
    ],
    memberships: [
      { group_id: 9, host_key: 'betty', host_label: 'Betty', container_key: 'open-webui', container_label: 'open-webui', app_id: 10, match: 'override' },
      { group_id: 9, host_key: 'blackbox', host_label: 'Blackbox', container_key: 'emoncms', container_label: 'emoncms', app_id: 20, match: 'override' },
    ],
    unmatched: [],
    ungrouped_apps: [],
    unmatched_count: 0,
  };

  const grouped = buildGroupedGraph(filtered, grouping);
  const bettyGroup = byId(grouped.nodes, groupNodeId(9, 'betty'));
  const blackboxGroup = byId(grouped.nodes, groupNodeId(9, 'blackbox'));

  assert.ok(bettyGroup);
  assert.ok(blackboxGroup);
  assert.equal(bettyGroup.data.label, 'Shared · 1');
  assert.deepEqual(bettyGroup.data.memberIds, ['apps-10']);
  assert.deepEqual(blackboxGroup.data.memberIds, ['apps-20']);
  assert.equal(bettyGroup.data.hostLabel, 'Betty');
  assert.equal(blackboxGroup.data.hostLabel, 'Blackbox');
});

test('non-app inventory keeps its host association for layout', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const vm = byId(grouped.nodes, 'vms-1');
  const positions = groupedLayoutPositions(grouped);

  assert.equal(vm.data.hostKey, 'betty');
  assert.ok(positions['vms-1'].y > positions['hardware-1'].y);
});
