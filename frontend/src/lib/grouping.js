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

const CARD_WIDTH = 220;
const CARD_HEIGHT = 92;
const MEMBER_PITCH = 170;
const MEMBER_ROW = 150;
const SLOT_GAP = 40;
const MAX_ROW_WIDTH = 1600;
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

/**
 * Build a grouped presentation graph from the already-filtered map graph and
 * the effective grouping payload. Real node ids/positions are preserved;
 * virtual group nodes are added. Topology edges are not rewritten here:
 * aggregate edges are produced separately for the current expansion state.
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
    (grouping?.groups || []).map((group) => [
      `${group.id}@${group.host_key}`,
      group,
    ])
  );
  const groupById = new Map(
    (grouping?.groups || []).map((group) => [group.id, group])
  );

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

  const appSlot = new Map();
  for (const membership of grouping?.memberships || []) {
    const key = `${membership.group_id}@${membership.host_key}`;
    const slot = ensureSlot(
      key,
      groupMeta.get(key) ||
        groupById.get(membership.group_id) || {
          id: membership.group_id,
          host_key: membership.host_key,
          host_label: membership.host_label,
          name: `Group ${membership.group_id}`,
        }
    );
    // Manual groups have no host of their own; scope their virtual cards by
    // the host of their members.
    slot.hostKey = slot.hostKey || membership.host_key;
    slot.hostLabel = slot.hostLabel || membership.host_label || "";
    slot.total += 1;
    if (membership.app_id != null) appSlot.set(membership.app_id, key);
  }
  for (const entry of grouping?.unmatched || []) {
    const key = `${entry.group_id}@${entry.host_key}`;
    const slot = ensureSlot(
      key,
      groupMeta.get(key) ||
        groupById.get(entry.group_id) || {
          id: entry.group_id,
          host_key: entry.host_key,
          host_label: entry.host_label,
          name: `Group ${entry.group_id}`,
        }
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
    node.data.groupNodeId = slot.kind === "ungrouped"
      ? ungroupedNodeId(slot.hostKey)
      : groupNodeId(slot.groupId, slot.hostKey);
  }

  // Annotate non-grouped nodes with their root hardware host for layout.
  const parentOf = new Map();
  for (const edge of placementEdges({ nodes, edges })) {
    if (!parentOf.has(edge.data.target)) parentOf.set(edge.data.target, edge.data.source);
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
    if (node.data.type === "group") continue;
    if (node.data.groupKey) continue;
    node.data.hostKey = node.data.type === "hardware"
      ? hostKeyOfHardware(node)
      : node.data.hostKey ?? hostForNode(node.data.id);
  }

  const groupNodes = [];
  for (const slot of slots.values()) {
    // Keep groups that only have not-in-inventory members visible, but hide
    // groups whose matched members were removed by filters.
    const onlyUnmatched = slot.total > 0 && slot.unmatchedLabels.length === slot.total;
    if (!slot.members.length && !onlyUnmatched) continue;
    const members = [...slot.members].sort(
      (a, b) => labelOf(a).localeCompare(labelOf(b)) || a.data.id.localeCompare(b.data.id)
    );
    const id = slot.kind === "ungrouped"
      ? ungroupedNodeId(slot.hostKey)
      : groupNodeId(slot.groupId, slot.hostKey);
    const host = hostLabel(slot.hostKey, slot.hostLabel);
    groupNodes.push({
      data: {
        id,
        label: slot.kind === "ungrouped"
          ? `Ungrouped · ${host} · ${slot.total}`
          : `${slot.name} · ${slot.total}`,
        type: "group",
        kind: slot.kind,
        groupId: slot.groupId,
        source: slot.source,
        hostKey: slot.hostKey,
        hostLabel: host,
        color: slot.color,
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
 * Aggregate topology edges for the current expansion state. Edges touching a
 * hidden member are rerouted to its group node; internal edges disappear and
 * duplicate group-to-node connections are collapsed into one edge.
 */
export function aggregateEdges(grouped, expandedGroupIds = []) {
  const expanded = new Set(expandedGroupIds);
  const byId = new Map((grouped?.nodes || []).map((node) => [node.data.id, node]));

  const representation = (id) => {
    const node = byId.get(id);
    const groupId = node?.data?.groupNodeId;
    if (groupId && !expanded.has(groupId)) return groupId;
    return id;
  };

  const result = [];
  const seen = new Set();
  for (const edge of grouped?.edges || []) {
    const source = representation(edge.data.source);
    const target = representation(edge.data.target);
    if (!source || !target || source === target) continue;
    if (source === edge.data.source && target === edge.data.target) continue;
    const key = source < target ? `${source}|${target}` : `${target}|${source}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push({
      data: { id: `agg-${key}`, source, target, aggregate: true },
    });
  }
  return result;
}

/**
 * Deterministic layout for Grouped mode.
 *
 * Each hardware host gets a vertical band: the host node, followed by any
 * non-grouped inventory (VMs, storage, ...), then group cards packed into
 * shelves. Member nodes sit in a grid directly beneath their group card. Space
 * for members is reserved even while a group is collapsed so expanding never
 * moves existing nodes.
 */
export function groupedLayoutPositions(grouped) {
  const nodes = grouped?.nodes || [];
  const byId = new Map(nodes.map((node) => [node.data.id, node]));
  const positions = {};

  const blocks = new Map();
  const ensureBlock = (hostKey) => {
    if (!blocks.has(hostKey)) {
      blocks.set(hostKey, { hostKey, hardware: null, groups: [], loose: [] });
    }
    return blocks.get(hostKey);
  };

  for (const node of nodes) {
    if (node.data.type === "hardware") {
      ensureBlock(hostKeyOfHardware(node)).hardware = node;
    } else if (node.data.type === "group") {
      ensureBlock(node.data.hostKey || "").groups.push(node);
    } else if (!node.data.groupNodeId) {
      ensureBlock(node.data.hostKey || "").loose.push(node);
    }
  }

  const hostKeys = [...blocks.keys()].sort((a, b) => a.localeCompare(b));
  let nextHostY = 0;

  for (const hostKey of hostKeys) {
    const block = blocks.get(hostKey);
    block.loose.sort(
      (a, b) =>
        String(a.data.type).localeCompare(String(b.data.type)) ||
        labelOf(a).localeCompare(labelOf(b)) ||
        a.data.id.localeCompare(b.data.id)
    );
    block.groups.sort(
      (a, b) =>
        (a.data.kind === "ungrouped" ? 1 : 0) -
          (b.data.kind === "ungrouped" ? 1 : 0) ||
        (a.data.sortOrder ?? 0) - (b.data.sortOrder ?? 0) ||
        labelOf(a).localeCompare(labelOf(b)) ||
        a.data.id.localeCompare(b.data.id)
    );

    let cursorY = nextHostY;
    if (block.hardware) {
      positions[block.hardware.data.id] = { x: 0, y: cursorY };
      cursorY += 120;
    }
    if (block.loose.length) {
      const width = (block.loose.length - 1) * OTHER_PITCH;
      block.loose.forEach((node, index) => {
        positions[node.data.id] = {
          x: -width / 2 + index * OTHER_PITCH,
          y: cursorY,
        };
      });
      cursorY += 170;
    }

    let index = 0;
    while (index < block.groups.length) {
      const row = [];
      let rowWidth = 0;
      while (index < block.groups.length) {
        const group = block.groups[index];
        const members = (group.data.memberIds || [])
          .map((id) => byId.get(id))
          .filter(Boolean);
        const columns = memberColumns(members.length);
        const slotWidth = Math.max(CARD_WIDTH, columns * MEMBER_PITCH);
        if (row.length && rowWidth + slotWidth + SLOT_GAP > MAX_ROW_WIDTH) break;
        row.push({ group, members, columns, slotWidth });
        rowWidth += slotWidth + (row.length > 1 ? SLOT_GAP : 0);
        index += 1;
      }

      let maxRows = 0;
      for (const item of row) {
        const rows = Math.ceil(item.members.length / item.columns) || 0;
        maxRows = Math.max(maxRows, rows);
      }

      let x = -rowWidth / 2;
      for (const item of row) {
        const cardX = x + item.slotWidth / 2;
        positions[item.group.data.id] = { x: cardX, y: cursorY + CARD_HEIGHT / 2 };
        const visibleColumns = Math.min(item.columns, item.members.length) || 1;
        const rows = Math.ceil(item.members.length / item.columns) || 0;
        item.members.forEach((member, memberIndex) => {
          const column = memberIndex % item.columns;
          const rowIndex = Math.floor(memberIndex / item.columns);
          positions[member.data.id] = {
            x:
              cardX +
              (column - (visibleColumns - 1) / 2) * MEMBER_PITCH,
            y: cursorY + CARD_HEIGHT + 80 + rowIndex * MEMBER_ROW,
          };
        });
        if (rows) maxRows = Math.max(maxRows, rows);
        x += item.slotWidth + SLOT_GAP;
      }

      cursorY +=
        CARD_HEIGHT + (maxRows ? maxRows * MEMBER_ROW + 80 : 40) + SLOT_GAP;
    }

    nextHostY = cursorY + HOST_GAP;
  }

  // Safety net: any node that did not fit a block gets a deterministic slot.
  let fallbackY = nextHostY;
  for (const node of nodes) {
    if (positions[node.data.id]) continue;
    positions[node.data.id] = { x: 0, y: fallbackY };
    fallbackY += 140;
  }
  return positions;
}
