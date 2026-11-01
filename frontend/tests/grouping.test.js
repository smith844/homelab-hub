import test from 'node:test';
import assert from 'node:assert/strict';
import {
  anchorsStorageKey,
  buildGroupedGraph,
  groupNodeId,
  groupedLayoutPositions,
  hasStaleGroupedLayout,
  identityKey,
  layoutStorageKey,
  presentationEdges,
  ungroupedNodeId,
  validAnchors,
  visibleNodeIds,
} from '../src/lib/grouping.js';

const node = (id, type, name, extra = {}) => ({
  data: {
    id,
    type,
    rawName: name,
    label: name,
    entity_id: Number(String(id).split('-').pop()),
    ...extra,
  },
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
      edge('e10', 'apps-10', 'apps-11'),
      edge('e11', 'apps-20', 'apps-11'),
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
    ungrouped_apps: [{ app_id: 12, host_key: 'betty', host_label: 'Betty' }],
    unmatched_count: 1,
  };
  return { filtered, grouping };
}

function byId(nodeList, id) {
  return nodeList.find((item) => item.data.id === id);
}

function keyOf(item) {
  return `${item.data.source}->${item.data.target}:${item.data.kind}`;
}

function assertNoDangling(grouped, virtual) {
  const nodeIds = new Set(grouped.nodes.map((item) => item.data.id));
  const seen = new Set();
  for (const item of virtual) {
    assert.ok(nodeIds.has(item.data.source), `dangling source ${item.data.source}`);
    assert.ok(nodeIds.has(item.data.target), `dangling target ${item.data.target}`);
    assert.ok(!seen.has(item.data.id), `duplicate virtual edge ${item.data.id}`);
    seen.add(item.data.id);
  }
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

test('grouped graph preserves real ids and resolves placement parents', () => {
  const { filtered, grouping } = fixture();
  const before = JSON.stringify(filtered);
  const grouped = buildGroupedGraph(filtered, grouping);

  for (const original of filtered.nodes) {
    const copy = byId(grouped.nodes, original.data.id);
    assert.ok(copy, `missing real node ${original.data.id}`);
    assert.equal(copy.data.id, original.data.id);
    assert.equal(copy.data.entity_id, original.data.entity_id);
  }
  assert.equal(JSON.stringify(filtered), before);

  const ai = byId(grouped.nodes, groupNodeId(1, 'betty'));
  assert.deepEqual(ai.data.parentIds, ['vms-1']);
  assert.equal(ai.data.hostNodeId, 'hardware-1');
  assert.deepEqual(ai.data.memberIds.slice().sort(), ['apps-10', 'apps-13', 'apps-14']);
  assert.equal(ai.data.totalMembers, 4);
  assert.equal(ai.data.visibleMembers, 3);
  assert.equal(ai.data.unmatchedMembers, 1);
  assert.deepEqual(ai.data.unmatchedLabels, ['missing-one']);

  const ungrouped = byId(grouped.nodes, ungroupedNodeId('betty'));
  assert.deepEqual(ungrouped.data.memberIds, ['apps-12']);
  assert.deepEqual(ungrouped.data.parentIds, ['vms-1']);

  const placement = Object.fromEntries(
    grouped.edges.map((item) => [item.data.id, item.data.placement])
  );
  assert.equal(placement.e3, true);
  assert.equal(placement.e9, false);
});

test('collapsed groups expose Docker -> group edges and hide placement edges', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const { virtual, hiddenEdgeIds } = presentationEdges(grouped, []);

  assert.deepEqual(virtual.map(keyOf).sort(), [
    'vms-1->group-1@betty:group-parent',
    'vms-1->group-2@betty:group-parent',
    'vms-1->ungrouped@betty:group-parent',
    'vms-2->group-3@blackbox:group-parent',
    'group-1@betty->group-2@betty:aggregate',
    'group-3@blackbox->group-2@betty:aggregate',
  ].sort());

  // No virtual Docker -> member edge exists; the placement edges are hidden.
  assert.ok(!virtual.some((item) => item.data.target.startsWith('apps-')));
  for (const id of ['e3', 'e4', 'e5', 'e6', 'e7', 'e8', 'e9', 'e10', 'e11']) {
    assert.ok(hiddenEdgeIds.includes(id), `expected ${id} hidden`);
  }
  // The host -> Docker placement edge remains visible.
  assert.ok(!hiddenEdgeIds.includes('e1'));
  assertNoDangling(grouped, virtual);
});

test('expanded groups expose group -> member edges without duplicating Docker edges', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const { virtual, hiddenEdgeIds } = presentationEdges(grouped, [groupNodeId(1, 'betty')]);

  assert.deepEqual(
    virtual.filter((item) => item.data.kind === 'group-member').map(keyOf).sort(),
    [
      'group-1@betty->apps-10:group-member',
      'group-1@betty->apps-13:group-member',
      'group-1@betty->apps-14:group-member',
    ].sort()
  );
  // No group -> member edge for the still-collapsed Media group.
  assert.ok(!virtual.some((item) => item.data.source === groupNodeId(2, 'betty') && item.data.kind === 'group-member'));
  // Others remain represented through their parent edge only.
  assert.ok(virtual.some((item) => item.data.target === groupNodeId(2, 'betty') && item.data.kind === 'group-parent'));
  // Placement edges into grouped members stay hidden.
  for (const id of ['e3', 'e4', 'e5', 'e6', 'e7', 'e8']) {
    assert.ok(hiddenEdgeIds.includes(id), `expected ${id} hidden`);
  }
  // The internal relationship between two expanded members remains real.
  assert.ok(!hiddenEdgeIds.includes('e9'));
  assertNoDangling(grouped, virtual);
});

test('multiple expanded groups keep unrelated topology edges intact', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const expanded = [groupNodeId(1, 'betty'), groupNodeId(2, 'betty')];
  const { virtual, hiddenEdgeIds } = presentationEdges(grouped, expanded);

  // e10 connects apps-10 and apps-11, both now visible.
  assert.ok(!hiddenEdgeIds.includes('e10'));
  // e11 targets a hidden member of the collapsed Monitoring group.
  assert.ok(hiddenEdgeIds.includes('e11'));
  assert.ok(
    virtual.some(
      (item) => item.data.kind === 'aggregate' &&
        item.data.source === groupNodeId(3, 'blackbox') &&
        item.data.target === 'apps-11'
    )
  );
  assert.deepEqual(
    virtual.filter((item) => item.data.kind === 'group-member').map(keyOf).sort(),
    [
      'group-1@betty->apps-10:group-member',
      'group-1@betty->apps-13:group-member',
      'group-1@betty->apps-14:group-member',
      'group-2@betty->apps-11:group-member',
    ].sort()
  );
  assertNoDangling(grouped, virtual);
});

test('repeated expansion states never leave duplicate or dangling edges', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const states = [
    [],
    [groupNodeId(1, 'betty')],
    [],
    [groupNodeId(1, 'betty'), groupNodeId(2, 'betty')],
    [groupNodeId(3, 'blackbox')],
    [],
  ];

  for (const expanded of states) {
    const { virtual, hiddenEdgeIds } = presentationEdges(grouped, expanded);
    assertNoDangling(grouped, virtual);
    const edgeIds = new Set(grouped.edges.map((item) => item.data.id));
    for (const id of hiddenEdgeIds) assert.ok(edgeIds.has(id));
  }
});

test('group colour and icon propagate to the grouped presentation', () => {
  const { filtered, grouping } = fixture();
  const decorated = {
    ...grouping,
    groups: grouping.groups.map((group) =>
      group.id === 1 ? { ...group, color: '#123456', icon: '\u2605' } : group
    ),
  };
  const grouped = buildGroupedGraph(filtered, decorated);
  const ai = byId(grouped.nodes, groupNodeId(1, 'betty'));

  assert.equal(ai.data.groupColor, '#123456');
  assert.match(ai.data.label, /^\u2605 AI/);
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
  const positions = groupedLayoutPositions(grouped, []);
  assert.ok(positions[groupNodeId(4, 'betty')]);
  const { virtual } = presentationEdges(grouped, []);
  assert.ok(
    virtual.some(
      (item) => item.data.kind === 'group-parent' && item.data.target === groupNodeId(4, 'betty')
    )
  );
});

function largeFixture(groupCount = 14, membersPerGroup = 6) {
  const nodes = [node('hardware-1', 'hardware', 'Betty'), node('vms-1', 'vms', 'Docker')];
  const edges = [edge('e0', 'hardware-1', 'vms-1')];
  const groups = [];
  const memberships = [];
  const ungroupedApps = [];

  for (let groupIndex = 0; groupIndex < groupCount; groupIndex += 1) {
    groups.push({
      id: groupIndex + 1,
      name: `Group ${groupIndex + 1}`,
      source: 'folderview',
      host_key: 'betty',
      sort_order: groupIndex,
    });
    for (let memberIndex = 0; memberIndex < membersPerGroup; memberIndex += 1) {
      const appId = 100 + groupIndex * membersPerGroup + memberIndex;
      nodes.push(node(`apps-${appId}`, 'apps', `App ${appId}`));
      edges.push(edge(`edge-${appId}`, 'vms-1', `apps-${appId}`));
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
    edges.push(edge(`edge-${appId}`, 'vms-1', `apps-${appId}`));
    ungroupedApps.push({ app_id: appId, host_key: 'betty', host_label: 'Betty' });
  }

  return {
    grouped: null,
    filtered: { nodes, edges },
    grouping: { groups, memberships, unmatched: [], ungrouped_apps: ungroupedApps, unmatched_count: 0 },
  };
}

test('collapsed 14-group layout is compact and keeps cards apart', () => {
  const { filtered, grouping } = largeFixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const positions = groupedLayoutPositions(grouped, []);
  const cards = grouped.nodes.filter((item) => item.data.type === 'group');

  assert.equal(cards.length, 15); // 14 groups + Ungrouped
  for (const card of cards) assert.ok(positions[card.data.id]);
  // Members are hidden while collapsed and do not reserve rows.
  assert.equal(positions['apps-100'], undefined);

  const cardRows = new Set(cards.map((card) => positions[card.data.id].y));
  assert.ok(cardRows.size <= 4, `expected a compact grid, got ${cardRows.size} rows`);
  assert.ok(Math.max(...cards.map((card) => positions[card.data.id].y)) < 1200);

  for (let i = 0; i < cards.length; i += 1) {
    for (let j = i + 1; j < cards.length; j += 1) {
      const a = positions[cards[i].data.id];
      const b = positions[cards[j].data.id];
      const dx = Math.abs(a.x - b.x);
      const dy = Math.abs(a.y - b.y);
      assert.ok(dx >= 220 || dy >= 92, `cards ${cards[i].data.id}/${cards[j].data.id} overlap`);
    }
  }
});

test('expanded layout positions members near their group and reflows deterministically', () => {
  const { filtered, grouping } = largeFixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const expanded = [groupNodeId(1, 'betty'), groupNodeId(2, 'betty')];
  const first = groupedLayoutPositions(grouped, expanded);
  const second = groupedLayoutPositions(grouped, expanded);
  assert.deepEqual(first, second);

  for (const groupId of ['1', '2']) {
    const cardId = groupNodeId(groupId, 'betty');
    const card = grouped.nodes.find((item) => item.data.id === cardId);
    assert.ok(first[cardId]);
    for (const memberId of card.data.memberIds) {
      assert.ok(first[memberId], `missing member position ${memberId}`);
      assert.ok(first[memberId].y > first[cardId].y);
      assert.ok(Math.abs(first[memberId].x - first[cardId].x) <= 400);
    }
  }

  const cards = grouped.nodes.filter((item) => item.data.type === 'group');
  for (let i = 0; i < cards.length; i += 1) {
    for (let j = i + 1; j < cards.length; j += 1) {
      const a = first[cards[i].data.id];
      const b = first[cards[j].data.id];
      const dx = Math.abs(a.x - b.x);
      const dy = Math.abs(a.y - b.y);
      assert.ok(dx >= 220 || dy >= 92, `expanded cards ${cards[i].data.id}/${cards[j].data.id} overlap`);
    }
  }
});

test('hosts are stacked and group cards stay under their own host', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const positions = groupedLayoutPositions(grouped, []);

  const betty = positions['hardware-1'];
  const blackbox = positions['hardware-2'];
  const docker = positions['vms-1'];
  const ai = positions[groupNodeId(1, 'betty')];
  const monitoring = positions[groupNodeId(3, 'blackbox')];

  assert.ok(docker.y > betty.y);
  assert.ok(ai.y > docker.y);
  assert.ok(blackbox.y > ai.y);
  assert.ok(monitoring.y > blackbox.y);
});

test('layout never mutates the input graph', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const before = JSON.stringify(grouped);
  groupedLayoutPositions(grouped, [groupNodeId(1, 'betty')]);
  assert.equal(JSON.stringify(grouped), before);
});

test('groups with no visible members are omitted', () => {
  const { filtered, grouping } = fixture();
  const onlyBlackbox = {
    nodes: filtered.nodes.filter((item) => ['hardware-2', 'vms-2', 'apps-20'].includes(item.data.id)),
    edges: filtered.edges.filter(
      (item) =>
        ['hardware-2', 'vms-2', 'apps-20'].includes(item.data.source) &&
        ['hardware-2', 'vms-2', 'apps-20'].includes(item.data.target)
    ),
  };
  const grouped = buildGroupedGraph(onlyBlackbox, grouping);

  assert.ok(byId(grouped.nodes, groupNodeId(3, 'blackbox')));
  assert.equal(byId(grouped.nodes, groupNodeId(1, 'betty')), undefined);
  assert.equal(byId(grouped.nodes, ungroupedNodeId('betty')), undefined);
});

test('stale grouped layouts are detected when expanded members are unsaved', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const expanded = [groupNodeId(1, 'betty')];

  assert.equal(hasStaleGroupedLayout(grouped, {}, expanded), true);
  assert.equal(hasStaleGroupedLayout(grouped, {}, []), false);
  assert.equal(
    hasStaleGroupedLayout(
      grouped,
      { 'apps-10': { x: 0, y: 0 }, 'apps-13': { x: 0, y: 0 }, 'apps-14': { x: 0, y: 0 } },
      expanded
    ),
    false
  );
});

test('visible node ids reflect collapsed and expanded states', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);

  const collapsed = visibleNodeIds(grouped, []);
  assert.ok(collapsed.has('hardware-1'));
  assert.ok(collapsed.has(groupNodeId(1, 'betty')));
  assert.ok(!collapsed.has('apps-10'));
  assert.ok(!collapsed.has('apps-12'));

  const expanded = visibleNodeIds(grouped, [groupNodeId(1, 'betty')]);
  assert.ok(expanded.has('apps-10'));
  assert.ok(expanded.has('apps-13'));
  assert.ok(!expanded.has('apps-11'));
});

test('dragged group anchors stay fixed across expand and collapse', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const cardId = groupNodeId(1, 'betty');
  const anchor = { x: 420, y: 640 };
  const anchors = { [cardId]: anchor };
  const ai = byId(grouped.nodes, cardId);

  const collapsed = groupedLayoutPositions(grouped, [], anchors);
  assert.deepEqual(collapsed[cardId], anchor);

  const expanded = groupedLayoutPositions(grouped, [cardId], anchors);
  assert.deepEqual(expanded[cardId], anchor);
  for (const memberId of ai.data.memberIds) {
    assert.ok(expanded[memberId].y > anchor.y);
    assert.ok(Math.abs(expanded[memberId].x - anchor.x) <= 400);
  }

  assert.deepEqual(groupedLayoutPositions(grouped, [], anchors)[cardId], anchor);
});

test('expanding other groups does not move anchored groups', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const anchoredId = groupNodeId(1, 'betty');
  const otherId = groupNodeId(2, 'betty');
  const anchors = { [anchoredId]: { x: -360, y: 560 } };

  const before = groupedLayoutPositions(grouped, [], anchors);
  const after = groupedLayoutPositions(grouped, [otherId], anchors);
  assert.deepEqual(after[anchoredId], before[anchoredId]);
});

test('multiple anchored and expanded groups stay fixed and separated', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const firstId = groupNodeId(1, 'betty');
  const secondId = groupNodeId(2, 'betty');
  const anchors = {
    [firstId]: { x: -360, y: 620 },
    [secondId]: { x: 360, y: 620 },
  };
  const positions = groupedLayoutPositions(grouped, [firstId, secondId], anchors);

  assert.deepEqual(positions[firstId], anchors[firstId]);
  assert.deepEqual(positions[secondId], anchors[secondId]);
  for (const groupId of [firstId, secondId]) {
    const group = byId(grouped.nodes, groupId);
    for (const memberId of group.data.memberIds) {
      assert.ok(positions[memberId].y > anchors[groupId].y);
    }
  }

  const automatic = byId(grouped.nodes, groupNodeId(3, 'blackbox'));
  const autoPosition = positions[automatic.data.id];
  for (const groupId of [firstId, secondId]) {
    const anchored = anchors[groupId];
    const dx = Math.abs(autoPosition.x - anchored.x);
    const dy = Math.abs(autoPosition.y - anchored.y);
    assert.ok(dx >= 220 || dy >= 92, `automatic group overlaps ${groupId}`);
  }
});

test('anchored positions survive reload and are not inferred from saved layouts', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const cardId = groupNodeId(1, 'betty');
  const anchors = { [cardId]: { x: 100, y: 700 } };

  assert.deepEqual(groupedLayoutPositions(grouped, [], anchors)[cardId], anchors[cardId]);
  assert.notDeepEqual(groupedLayoutPositions(grouped, [], {})[cardId], anchors[cardId]);
  assert.equal(anchorsStorageKey('sig'), 'hlh.mapGroupAnchors.sig');
  assert.notEqual(anchorsStorageKey('sig'), layoutStorageKey('grouped', 'sig'));
  assert.deepEqual(
    validAnchors({ ok: { x: 1, y: 2 }, bad: { x: 'nope', y: 2 }, missing: null }),
    { ok: { x: 1, y: 2 } }
  );
});

test('auto layout ignores explicit anchors', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const cardId = groupNodeId(1, 'betty');
  const anchored = groupedLayoutPositions(grouped, [], { [cardId]: { x: 900, y: 900 } });
  const reset = groupedLayoutPositions(grouped, [], {});

  assert.deepEqual(anchored[cardId], { x: 900, y: 900 });
  assert.notDeepEqual(reset[cardId], anchored[cardId]);
});

test('stale layout ignores anchored expanded groups', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const cardId = groupNodeId(1, 'betty');

  assert.equal(hasStaleGroupedLayout(grouped, {}, [cardId], {}), true);
  assert.equal(
    hasStaleGroupedLayout(grouped, {}, [cardId], { [cardId]: { x: 0, y: 0 } }),
    false
  );
});

test('non-app inventory keeps its host association for layout', () => {
  const { filtered, grouping } = fixture();
  const grouped = buildGroupedGraph(filtered, grouping);
  const vm = byId(grouped.nodes, 'vms-1');
  const positions = groupedLayoutPositions(grouped, []);

  assert.equal(vm.data.hostKey, 'betty');
  assert.ok(positions['vms-1'].y > positions['hardware-1'].y);
});
