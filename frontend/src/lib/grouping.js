import { placementEdges } from "./mapViews.js";

const WHITESPACE_RE = /\s+/g;

export function identityKey(value) {
  if (value == null) return "";
  return String(value).trim().replace(WHITESPACE_RE, " ").toLowerCase();
}

export function groupNodeId(groupId, hostKey) {
  return `group-${groupId}@${hostKey}`;
}

export function ungroupedNodeId(hostKey) {
  return `ungrouped@${hostKey}`;
}

// Graph saved layouts and Grouped saved layouts are intentionally separate.
export function layoutStorageKey(mode, viewKey) {
  const prefix = mode === "grouped" ? "hlh.mapLayoutGrouped" : "hlh.mapLayout";
  return `${prefix}.${viewKey}`;
}

// Manual Grouped anchors are stored separately from layout coordinates, so a
// saved position never implies a manual anchor on its own.
export function anchorsStorageKey(viewKey) {
  return `hlh.mapGroupAnchors.${viewKey}`;
}

export function validAnchors(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  const result = {};
  for (const [id, position] of Object.entries(value)) {
    if (position && Number.isFinite(position.x) && Number.isFinite(position.y)) {
      result[id] = { x: position.x, y: position.y };
    }
  }
  return result;
}

const CARD_WIDTH = 220;
const CARD_HEIGHT = 92;
const CARD_GAP = 40;
const MEMBER_PITCH = 170;
const MEMBER_ROW = 150;
const MAX_ROW_WIDTH = 1300;
const LANE_GAP = 80;
const OTHER_PITCH = 200;
const HOST_GAP = 280;

function memberColumns(count) {
  if (count <= 2) return Math.max(1, count);
  return Math.min(3, Math.ceil(Math.sqrt(count)));
}

function labelOf(node) {
  return node?.data?.rawName || node?.data?.label || node?.data?.id || "";
}

function hostKeyOfHardware(node) {
  return identityKey(node?.data?.rawName || node?.data?.label);
}

function sortByLabel(a, b) {
  return labelOf(a).localeCompare(labelOf(b)) || a.data.id.localeCompare(b.data.id);
}

/**
 * Build a grouped presentation graph from the already-filtered map graph and
 * the effective grouping payload. Real node ids/data are preserved; virtual
 * group nodes are added. Topology edges keep their original endpoints and are
 * flagged as placement or relationship edges.
 */
export function buildGroupedGraph(filtered, grouping) {
  const sourceNodes = filtered?.nodes || [];
  const sourceEdges = filtered?.edges || [];
  const nodes = sourceNodes.map((node) => ({ ...node, data: { ...node.data } }));
  const edges = sourceEdges.map((edge) => ({ ...edge, data: { ...edge.data } }));
  const byId = new Map(nodes.map((node) => [node.data.id, node]));

  const hardwareByHost = new Map();
  for (const node of nodes) {
    if (node.data.type === "hardware") {
      hardwareByHost.set(hostKeyOfHardware(node), node);
    }
  }

  const hostLabel = (hostKey, fallback = "") => {
    const hardware = hardwareByHost.get(hostKey);
    return (
      hardware?.data?.rawName ||
      hardware?.data?.label ||
      fallback ||
      (hostKey === "" ? "No host" : hostKey)
    );
  };

  const groupMeta = new Map(
    (grouping?.groups || []).map((group) => [`${group.id}@${group.host_key}`, group])
  );
  const groupById = new Map((grouping?.groups || []).map((group) => [group.id, group]));

  const slots = new Map();
  const ensureSlot = (key, meta) => {
    if (!slots.has(key)) {
      slots.set(key, {
        key,
        kind: meta?.kind || "group",
        groupId: meta?.id ?? null,
        name: meta?.name || "Group",
        source: meta?.source || null,
        color: meta?.color || null,
        icon: meta?.icon || null,
        sortOrder: meta?.sort_order ?? 0,
        hostKey: meta?.host_key || "",
        hostLabel: meta?.host_label || "",
        total: 0,
        unmatchedLabels: [],
        members: [],
      });
    }
    return slots.get(key);
  };

  const groupMetaFor = (key, groupId, hostKey, hostLabelValue) =>
    groupMeta.get(key) ||
    groupById.get(groupId) || {
      id: groupId,
      host_key: hostKey,
      host_label: hostLabelValue,
      name: `Group ${groupId}`,
    };

  const appSlot = new Map();
  for (const membership of grouping?.memberships || []) {
    const key = `${membership.group_id}@${membership.host_key}`;
    const slot = ensureSlot(
      key,
      groupMetaFor(key, membership.group_id, membership.host_key, membership.host_label)
    );
    // Manual groups have no host of their own; scope their cards by member host.
    slot.hostKey = slot.hostKey || membership.host_key;
    slot.hostLabel = slot.hostLabel || membership.host_label || "";
    slot.total += 1;
    if (membership.app_id != null) appSlot.set(membership.app_id, key);
  }
  for (const entry of grouping?.unmatched || []) {
    const key = `${entry.group_id}@${entry.host_key}`;
    const slot = ensureSlot(
      key,
      groupMetaFor(key, entry.group_id, entry.host_key, entry.host_label)
    );
    slot.hostKey = slot.hostKey || entry.host_key;
    slot.hostLabel = slot.hostLabel || entry.host_label || "";
    slot.total += 1;
    slot.unmatchedLabels.push(entry.container_label || entry.container_key);
  }
  for (const entry of grouping?.ungrouped_apps || []) {
    const key = ungroupedNodeId(entry.host_key);
    const slot = ensureSlot(key, {
      kind: "ungrouped",
      id: null,
      host_key: entry.host_key,
      host_label: entry.host_label,
      name: "Ungrouped",
    });
    slot.hostLabel = slot.hostLabel || entry.host_label || "";
    slot.total += 1;
    appSlot.set(entry.app_id, key);
  }

  for (const node of nodes) {
    if (node.data.type !== "apps") continue;
    const key = appSlot.get(node.data.entity_id);
    if (!key) continue;
    const slot = slots.get(key);
    slot.members.push(node);
    node.data.groupKey = key;
    node.data.groupNodeId =
      slot.kind === "ungrouped"
        ? ungroupedNodeId(slot.hostKey)
        : groupNodeId(slot.groupId, slot.hostKey);
  }

  // Flag placement (hierarchy) edges and resolve each node's placement parent.
  const placement = placementEdges({ nodes, edges });
  const placementSet = new Set(placement);
  const parentOf = new Map();
  for (const edge of placement) {
    edge.data.placement = true;
    if (!parentOf.has(edge.data.target)) parentOf.set(edge.data.target, edge.data.source);
  }
  for (const edge of edges) {
    if (!placementSet.has(edge)) edge.data.placement = false;
  }

  const hostForNode = (id, seen = new Set()) => {
    const node = byId.get(id);
    if (!node) return "";
    if (node.data.type === "hardware") return hostKeyOfHardware(node);
    if (seen.has(id)) return "";
    seen.add(id);
    const parent = parentOf.get(id);
    return parent ? hostForNode(parent, seen) : "";
  };

  for (const node of nodes) {
    node.data.placementParentId = parentOf.get(node.data.id) || null;
    if (node.data.type === "group") continue;
    if (node.data.groupKey) continue;
    node.data.hostKey =
      node.data.type === "hardware"
        ? hostKeyOfHardware(node)
        : node.data.hostKey ?? hostForNode(node.data.id);
  }

  const groupNodes = [];
  for (const slot of slots.values()) {
    // Keep groups that only have not-in-inventory members visible, but hide
    // groups whose matched members were removed by filters.
    const onlyUnmatched = slot.total > 0 && slot.unmatchedLabels.length === slot.total;
    if (!slot.members.length && !onlyUnmatched) continue;

    const members = [...slot.members].sort(sortByLabel);
    const parentIds = [
      ...new Set(
        members
          .map((member) => member.data.placementParentId)
          .filter((id) => id && byId.has(id))
      ),
    ];
    const hardware = hardwareByHost.get(slot.hostKey);
    const hostNodeId = hardware?.data.id || null;
    const id =
      slot.kind === "ungrouped"
        ? ungroupedNodeId(slot.hostKey)
        : groupNodeId(slot.groupId, slot.hostKey);
    const host = hostLabel(slot.hostKey, slot.hostLabel);

    groupNodes.push({
      data: {
        id,
        label:
          slot.kind === "ungrouped"
            ? `Ungrouped · ${host} · ${slot.total}`
            : `${slot.icon ? `${slot.icon} ` : ""}${slot.name} · ${slot.total}`,
        type: "group",
        kind: slot.kind,
        groupId: slot.groupId,
        source: slot.source,
        hostKey: slot.hostKey,
        hostLabel: host,
        hostNodeId,
        parentIds,
        color: slot.color,
        ...(slot.color ? { groupColor: slot.color } : {}),
        sortOrder: slot.sortOrder,
        totalMembers: slot.total,
        visibleMembers: members.length,
        unmatchedMembers: slot.unmatchedLabels.length,
        memberIds: members.map((member) => member.data.id),
        members: members.map((member) => ({
          id: member.data.id,
          entity_id: member.data.entity_id,
          label: labelOf(member),
          type: member.data.type,
        })),
        unmatchedLabels: [...slot.unmatchedLabels],
        expanded: false,
      },
    });
  }

  groupNodes.sort((a, b) => a.data.id.localeCompare(b.data.id));
  return { nodes: [...nodes, ...groupNodes], edges };
}

/**
 * Presentation-only edges for the current expansion state.
 *
 * - parent -> group edges are always present (Docker/VM -> category)
 * - group -> member edges exist while the group is expanded
 * - placement edges into grouped members are hidden (replaced by the chain)
 * - other topology edges stay visible or aggregate onto collapsed groups
 *
 * Returns `{ virtual, hiddenEdgeIds }`; `hiddenEdgeIds` contains real topology
 * edge ids that must not be drawn.
 */
/**
 * Node ids that are visible for a given expansion state (collapsed members are
 * hidden). Mirrors the visibility classes used by the Cytoscape component and is
 * used by tests for the visible-element Fit all behaviour.
 */
export function visibleNodeIds(grouped, expandedGroupIds = []) {
  const expanded = new Set(expandedGroupIds);
  const ids = new Set();
  for (const node of grouped?.nodes || []) {
    const groupId = node.data.groupNodeId;
    if (groupId && !expanded.has(groupId)) continue;
    ids.add(node.data.id);
  }
  return ids;
}

/**
 * True when a saved Grouped layout does not cover the currently expanded
 * members (for example, it was saved while those groups were collapsed). In
 * that case the component recomputes the grouped layout instead of mixing
 * stale card positions with newly expanded members.
 */
/**
 * True when a saved Grouped layout does not cover the currently expanded,
 * non-anchored members (for example, it was saved while those groups were
 * collapsed). Anchored groups are laid out from their anchors, so they do not
 * make the saved layout stale.
 */
export function hasStaleGroupedLayout(
  grouped,
  savedPositions = {},
  expandedGroupIds = [],
  rawAnchors = {}
) {
  const expanded = new Set(expandedGroupIds);
  const anchoredGroupIds = new Set(Object.keys(validAnchors(rawAnchors)));
  return (grouped?.nodes || []).some((node) => {
    const groupId = node.data.groupNodeId;
    return (
      Boolean(groupId) &&
      expanded.has(groupId) &&
      !anchoredGroupIds.has(groupId) &&
      !savedPositions[node.data.id]
    );
  });
}

export function presentationEdges(grouped, expandedGroupIds = []) {
  const expanded = new Set(expandedGroupIds);
  const nodes = grouped?.nodes || [];
  const byId = new Map(nodes.map((node) => [node.data.id, node]));

  const isHiddenMember = (id) => {
    const node = byId.get(id);
    const groupId = node?.data?.groupNodeId;
    return Boolean(groupId) && !expanded.has(groupId);
  };
  const representation = (id) => {
    const node = byId.get(id);
    const groupId = node?.data?.groupNodeId;
    if (groupId && !expanded.has(groupId)) return groupId;
    return id;
  };

  const hiddenEdgeIds = new Set();
  const virtual = [];
  const virtualByKey = new Map();

  const addVirtual = (key, source, target, kind) => {
    if (!source || !target || source === target) return;
    if (!byId.has(source) || !byId.has(target)) return;
    if (virtualByKey.has(key)) return;
    const edge = { data: { id: key, source, target, kind } };
    virtualByKey.set(key, edge);
    virtual.push(edge);
  };

  for (const edge of grouped?.edges || []) {
    const edgeId = edge.id ?? edge.data?.id;
    const source = edge.data.source;
    const target = edge.data.target;

    if (edge.data.placement) {
      // Placement edges into a grouped member are replaced by
      // parent -> group -> member; never draw them directly.
      if (
        byId.get(source)?.data?.groupNodeId ||
        byId.get(target)?.data?.groupNodeId
      ) {
        hiddenEdgeIds.add(edgeId);
        continue;
      }
    }

    const sourceHidden = isHiddenMember(source);
    const targetHidden = isHiddenMember(target);
    if (sourceHidden || targetHidden) {
      hiddenEdgeIds.add(edgeId);
      if (!edge.data.placement) {
        const repSource = representation(source);
        const repTarget = representation(target);
        addVirtual(`vagg-${repSource}|${repTarget}`, repSource, repTarget, "aggregate");
      }
    }
  }

  for (const node of nodes) {
    if (node.data.type !== "group") continue;
    const parents = (node.data.parentIds || []).filter((id) => byId.has(id));
    if (!parents.length && node.data.hostNodeId && byId.has(node.data.hostNodeId)) {
      parents.push(node.data.hostNodeId);
    }
    for (const parent of parents) {
      addVirtual(`vgp-${parent}-${node.data.id}`, parent, node.data.id, "group-parent");
    }
    if (expanded.has(node.data.id)) {
      for (const memberId of node.data.memberIds || []) {
        addVirtual(`vgm-${node.data.id}-${memberId}`, node.data.id, memberId, "group-member");
      }
    }
  }

  return { virtual, hiddenEdgeIds: [...hiddenEdgeIds] };
}

function buildLane(groups, expanded, byId) {
  const rows = [];
  let row = { width: 0, height: 0, items: [] };

  for (const group of groups) {
    const members = expanded.has(group.data.id)
      ? (group.data.memberIds || []).map((id) => byId.get(id)).filter(Boolean)
      : [];
    const columns = members.length ? memberColumns(members.length) : 1;
    const slotWidth = members.length
      ? Math.max(CARD_WIDTH, columns * MEMBER_PITCH)
      : CARD_WIDTH;
    const memberRows = members.length ? Math.ceil(members.length / columns) : 0;
    const slotHeight = CARD_HEIGHT + (memberRows ? 80 + memberRows * MEMBER_ROW : 0);

    if (row.items.length && row.width + CARD_GAP + slotWidth > MAX_ROW_WIDTH) {
      rows.push(row);
      row = { width: 0, height: 0, items: [] };
    }
    const x = row.items.length ? row.width + CARD_GAP : 0;
    row.items.push({ group, members, columns, slotWidth, memberRows, x });
    row.width = x + slotWidth;
    row.height = Math.max(row.height, slotHeight);
  }
  if (row.items.length) rows.push(row);

  const width = rows.length ? Math.max(...rows.map((item) => item.width)) : 0;
  const positions = {};
  let y = 0;
  for (const currentRow of rows) {
    for (const item of currentRow.items) {
      const cardX = -width / 2 + item.x + item.slotWidth / 2;
      positions[item.group.data.id] = { x: cardX, y: y + CARD_HEIGHT / 2 };
      if (item.members.length) {
        const visibleColumns = Math.min(item.columns, item.members.length);
        item.members.forEach((member, index) => {
          const column = index % item.columns;
          const rowIndex = Math.floor(index / item.columns);
          positions[member.data.id] = {
            x: cardX + (column - (visibleColumns - 1) / 2) * MEMBER_PITCH,
            y: y + CARD_HEIGHT + 80 + rowIndex * MEMBER_ROW,
          };
        });
      }
    }
    y += currentRow.height + CARD_GAP;
  }

  return {
    width,
    height: rows.length ? y - CARD_GAP : 0,
    positions,
  };
}

/**
 * Deterministic layout for Grouped mode.
 *
 * Collapsed groups are packed as a compact card grid under their Docker/VM
 * parent; expanding a group reserves a member grid beneath its card and
 * re-flows the surrounding cards. Hosts are stacked, so Betty and Blackbox
 * never share a lane.
 */
function placeMembersUnder(anchor, members) {
  const positions = new Map();
  if (!members.length) return positions;
  const columns = memberColumns(members.length);
  const visibleColumns = Math.min(columns, members.length);
  members.forEach((member, index) => {
    const column = index % columns;
    const row = Math.floor(index / columns);
    positions.set(member.data.id, {
      x: anchor.x + (column - (visibleColumns - 1) / 2) * MEMBER_PITCH,
      y: anchor.y + CARD_HEIGHT / 2 + 80 + row * MEMBER_ROW,
    });
  });
  return positions;
}

function groupRect(center, members = []) {
  let x1 = center.x - CARD_WIDTH / 2 - 20;
  let x2 = center.x + CARD_WIDTH / 2 + 20;
  let y1 = center.y - CARD_HEIGHT / 2 - 20;
  let y2 = center.y + CARD_HEIGHT / 2 + 20;
  for (const member of members) {
    x1 = Math.min(x1, member.x - 80);
    x2 = Math.max(x2, member.x + 80);
    y1 = Math.min(y1, member.y - 60);
    y2 = Math.max(y2, member.y + 60);
  }
  return { x1, x2, y1, y2 };
}

function rectsIntersect(a, b) {
  return a.x1 < b.x2 && a.x2 > b.x1 && a.y1 < b.y2 && a.y2 > b.y1;
}

/**
 * Deterministic layout for Grouped mode.
 *
 * - Manual anchors (dragged group cards) are fixed and never moved by layout.
 * - Anchored groups place their expanded members directly beneath the anchor.
 * - Collapsed groups use a compact card grid under their Docker/VM parent.
 * - Expanding a group reserves a member grid beneath its card and re-flows the
 *   remaining automatic groups, avoiding anchored cards and their members.
 * - Hosts are stacked, so Betty and Blackbox never share a lane.
 */
export function groupedLayoutPositions(
  grouped,
  expandedGroupIds = [],
  rawAnchors = {}
) {
  const expanded = new Set(expandedGroupIds);
  const anchors = validAnchors(rawAnchors);
  const nodes = grouped?.nodes || [];
  const byId = new Map(nodes.map((node) => [node.data.id, node]));
  const positions = {};

  const hosts = nodes.filter((node) => node.data.type === "hardware");
  const groups = nodes.filter((node) => node.data.type === "group");
  const loose = nodes.filter(
    (node) =>
      node.data.type !== "hardware" &&
      node.data.type !== "group" &&
      !node.data.groupNodeId
  );

  const anchoredGroups = groups
    .filter((group) => anchors[group.data.id])
    .sort((a, b) => a.data.id.localeCompare(b.data.id));
  const anchoredIds = new Set(anchoredGroups.map((group) => group.data.id));

  // Place anchored cards first. They are fixed for the whole layout pass.
  const occupied = [];
  const anchoredBottomByHost = new Map();
  for (const group of anchoredGroups) {
    const anchor = anchors[group.data.id];
    positions[group.data.id] = { x: anchor.x, y: anchor.y };
    const members = expanded.has(group.data.id)
      ? (group.data.memberIds || []).map((id) => byId.get(id)).filter(Boolean)
      : [];
    const memberPositions = placeMembersUnder(anchor, members);
    for (const [id, position] of memberPositions) positions[id] = position;
    const rect = groupRect(anchor, [...memberPositions.values()]);
    occupied.push(rect);
    const hostKey = group.data.hostKey || "";
    anchoredBottomByHost.set(
      hostKey,
      Math.max(anchoredBottomByHost.get(hostKey) ?? -Infinity, rect.y2)
    );
  }

  const hostKeys = new Set([
    ...hosts.map(hostKeyOfHardware),
    ...groups.map((group) => group.data.hostKey || ""),
    ...loose.map((node) => node.data.hostKey || ""),
  ]);

  let nextHostY = 0;
  for (const hostKey of [...hostKeys].sort((a, b) => a.localeCompare(b))) {
    const top = nextHostY;
    const hostNode = hosts.find((node) => hostKeyOfHardware(node) === hostKey) || null;
    const blockGroups = groups.filter(
      (group) =>
        (group.data.hostKey || "") === hostKey && !anchoredIds.has(group.data.id)
    );
    const blockLoose = loose.filter((node) => (node.data.hostKey || "") === hostKey);

    const lanesByParent = new Map();
    for (const group of blockGroups) {
      const primary =
        (group.data.parentIds || []).find((id) => byId.has(id)) ||
        (group.data.hostNodeId && byId.has(group.data.hostNodeId)
          ? group.data.hostNodeId
          : "__host__");
      if (!lanesByParent.has(primary)) lanesByParent.set(primary, []);
      lanesByParent.get(primary).push(group);
    }

    const lanes = [...lanesByParent.entries()]
      .map(([parentId, laneGroups]) => {
        const parent = byId.get(parentId) || null;
        return {
          parentId,
          parent,
          groups: laneGroups.sort(
            (a, b) =>
              (a.data.kind === "ungrouped" ? 1 : 0) -
                (b.data.kind === "ungrouped" ? 1 : 0) ||
              (a.data.sortOrder ?? 0) - (b.data.sortOrder ?? 0) ||
              sortByLabel(a, b)
          ),
        };
      })
      .sort((a, b) => {
        if (a.parentId === "__host__") return 1;
        if (b.parentId === "__host__") return -1;
        return (
          labelOf(a.parent).localeCompare(labelOf(b.parent)) ||
          a.parentId.localeCompare(b.parentId)
        );
      });

    const laneLayouts = lanes.map((lane) => ({
      ...lane,
      layout: buildLane(lane.groups, expanded, byId),
    }));
    const totalLaneWidth =
      laneLayouts.reduce((sum, lane) => sum + lane.layout.width, 0) +
      Math.max(0, laneLayouts.length - 1) * LANE_GAP;

    let laneLeft = -totalLaneWidth / 2;
    let blockBottom = 0;
    for (const lane of laneLayouts) {
      const laneCenter = laneLeft + lane.layout.width / 2;
      const parentIsHost =
        !lane.parent ||
        lane.parent.data.type === "hardware" ||
        lane.parentId === "__host__";
      if (!parentIsHost) {
        positions[lane.parent.data.id] = { x: laneCenter, y: top + 140 };
      }
      const laneTop = top + (parentIsHost ? 220 : 320);
      for (const [id, position] of Object.entries(lane.layout.positions)) {
        positions[id] = {
          x: laneCenter + position.x,
          y: laneTop + position.y,
        };
      }
      blockBottom = Math.max(blockBottom, laneTop + lane.layout.height);
      laneLeft += lane.layout.width + LANE_GAP;
    }

    const remainingLoose = blockLoose.filter((node) => !positions[node.data.id]);
    if (remainingLoose.length) {
      const looseY = blockBottom ? blockBottom + 120 : top + 180;
      const width = (remainingLoose.length - 1) * OTHER_PITCH;
      remainingLoose
        .sort(
          (a, b) =>
            String(a.data.type).localeCompare(String(b.data.type)) ||
            sortByLabel(a, b)
        )
        .forEach((node, index) => {
          positions[node.data.id] = {
            x: -width / 2 + index * OTHER_PITCH,
            y: looseY,
          };
        });
      blockBottom = Math.max(blockBottom, looseY - top + 40);
    }

    // Automatic groups shift down when they collide with anchored cards or
    // their expanded members. Anchored cards themselves never move.
    const autoGroups = [...blockGroups].sort((a, b) =>
      a.data.id.localeCompare(b.data.id)
    );
    for (const group of autoGroups) {
      const position = positions[group.data.id];
      if (!position) continue;
      const members = expanded.has(group.data.id)
        ? (group.data.memberIds || []).map((id) => byId.get(id)).filter(Boolean)
        : [];
      const moveMembers = (deltaY) => {
        for (const member of members) {
          const memberPosition = positions[member.data.id];
          if (memberPosition) {
            positions[member.data.id] = {
              x: memberPosition.x,
              y: memberPosition.y + deltaY,
            };
          }
        }
      };
      let rect = groupRect(
        position,
        members.map((member) => positions[member.data.id]).filter(Boolean)
      );
      let guard = 0;
      while (occupied.some((other) => rectsIntersect(rect, other)) && guard < 500) {
        const deltaY = CARD_HEIGHT + CARD_GAP;
        position.y += deltaY;
        positions[group.data.id] = { x: position.x, y: position.y };
        moveMembers(deltaY);
        rect = groupRect(
          position,
          members.map((member) => positions[member.data.id]).filter(Boolean)
        );
        guard += 1;
      }
      occupied.push(rect);
      const memberRows = members.length
        ? Math.ceil(members.length / memberColumns(members.length))
        : 0;
      blockBottom = Math.max(
        blockBottom,
        position.y -
          top +
          CARD_HEIGHT / 2 +
          (memberRows ? 80 + memberRows * MEMBER_ROW : 0) +
          40
      );
    }

    const anchoredBottom = anchoredBottomByHost.get(hostKey);
    if (anchoredBottom !== undefined) {
      blockBottom = Math.max(blockBottom, anchoredBottom - top + 40);
    }

    if (hostNode) {
      positions[hostNode.data.id] = { x: 0, y: top };
    }
    nextHostY = top + Math.max(blockBottom, 200) + HOST_GAP;
  }

  // Fallback for visible nodes that did not fit a lane.
  let fallbackY = nextHostY;
  for (const node of nodes) {
    if (positions[node.data.id]) continue;
    if (node.data.type === "apps" && node.data.groupNodeId) continue;
    positions[node.data.id] = { x: 0, y: fallbackY };
    fallbackY += 140;
  }

  return positions;
}
