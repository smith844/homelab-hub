export const TYPES = ["hardware", "vms", "apps", "storage", "shares", "misc"];
export const TYPE_LABELS = { hardware: "Hosts", vms: "VMs / LXCs / runtimes", apps: "Applications", storage: "Storage", shares: "Shares", misc: "Other devices" };
// Spacing tuned for the 64px node cards and their wrapped 14px labels.
export const COLUMN_GAP = 190;
export const ROW_GAP = 150;
export const LAYER_GAP = 100;
// Only placement edges define ancestry. Custom dependency links must not pull a
// different host into a scoped host view (or recurse forever through cycles).
export function placementEdges(graph) {
  const nodes = new Map(graph.nodes.map(n => [n.data.id, n.data]));
  return graph.edges.filter(e => {
    const a = nodes.get(e.data.source), b = nodes.get(e.data.target);
    if (!a || !b || e.data.manual) return false;
    return (a.type === "hardware" && ["vms", "apps", "storage"].includes(b.type)) ||
      (a.type === "vms" && ["apps", "storage"].includes(b.type)) ||
      (a.type === "storage" && b.type === "shares");
  });
}
export function filterGraph(graph, { root = "", types = TYPES, query = "", members = [], depth = "all" } = {}) {
  const nodes = graph.nodes || [], edges = graph.edges || [];
  const placement = placementEdges({ nodes, edges });
  const all = new Set(nodes.map(n => n.data.id));
  let scope = new Set(all);
  let levels = new Map();
  if (members.length) scope = new Set(members.filter(id => all.has(id)));
  else if (root) {
    scope = new Set(all.has(root) ? [root] : []); levels.set(root, 0);
    const queue = [...scope];
    for (let i = 0; i < queue.length; i++) {
      for (const e of placement.filter(e => e.data.source === queue[i])) {
        const id = e.data.target;
        if (!scope.has(id)) { scope.add(id); levels.set(id, levels.get(queue[i]) + 1); queue.push(id); }
      }
    }
  } else if (depth !== "all") {
    // With no selected host, depth still follows the placement forest:
    // top-level records are level 0 and each child adds one level.
    levels = layoutLevels({ nodes, edges }, placement);
  }
  const search = query.trim().toLowerCase();
  const matches = nodes.filter(n => scope.has(n.data.id) && types.includes(n.data.type) &&
    (!search || `${n.data.rawName || n.data.label || ""} ${n.data.networkName || ""}`.toLowerCase().includes(search)) &&
    (depth === "all" || members.length || (levels.get(n.data.id) ?? 0) <= Number(depth)));
  const keep = new Set(matches.map(n => n.data.id));
  // Keep ancestors for orientation, even when their type is unchecked.
  for (const n of matches) {
    const queue = [n.data.id], seen = new Set(queue);
    for (let i = 0; i < queue.length; i++) for (const e of placement.filter(e => e.data.target === queue[i])) {
      const id = e.data.source;
      if (scope.has(id) && !seen.has(id)) { seen.add(id); keep.add(id); queue.push(id); }
    }
  }
  const matchIds = new Set(matches.map(n => n.data.id));
  return { nodes: nodes.filter(n => keep.has(n.data.id)).map(n => ({ ...n, data: { ...n.data, context: !matchIds.has(n.data.id) } })),
    edges: edges.filter(e => keep.has(e.data.source) && keep.has(e.data.target)), matches: matches.length };
}
// Longest placement path per node. Cycles are broken at DFS back edges so
// circular placement data cannot inflate levels; acyclic hierarchies keep
// their exact ordering. The edges parameter defaults to the placement edges.
export function layoutLevels(graph, edges = placementEdges(graph)) {
  const nodes = graph.nodes || [];
  const outgoing = new Map();
  for (const e of edges) {
    if (!outgoing.has(e.data.source)) outgoing.set(e.data.source, []);
    outgoing.get(e.data.source).push(e.data.target);
  }
  // Depth-first pass keeps only edges that do not close a cycle.
  const state = new Map();
  const acyclic = [];
  for (const n of nodes) {
    if (state.has(n.data.id)) continue;
    state.set(n.data.id, 1);
    const stack = [{ id: n.data.id, index: 0 }];
    while (stack.length) {
      const frame = stack[stack.length - 1];
      const targets = outgoing.get(frame.id) || [];
      if (frame.index >= targets.length) {
        state.set(frame.id, 2);
        stack.pop();
        continue;
      }
      const target = targets[frame.index++];
      const targetState = state.get(target);
      if (targetState === 1) continue; // back edge: would close a cycle
      acyclic.push({ data: { source: frame.id, target } });
      if (targetState === undefined) {
        state.set(target, 1);
        stack.push({ id: target, index: 0 });
      }
    }
  }
  const level = new Map(nodes.map(n => [n.data.id, 0]));
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false;
    for (const e of acyclic) {
      const next = (level.get(e.data.source) ?? 0) + 1;
      if (next > (level.get(e.data.target) ?? 0)) { level.set(e.data.target, next); changed = true; }
    }
    if (!changed) break;
  }
  return level;
}
// Layered grid wraps large layers instead of forcing all containers into a row.
export function layoutPositions(graph, columns = 8) {
  const nodes = graph.nodes || [];
  const level = layoutLevels(graph);
  const groups = new Map();
  for (const n of nodes) { const l = level.get(n.data.id); if (!groups.has(l)) groups.set(l, []); groups.get(l).push(n); }
  const positions = {}; let y = 0;
  for (const l of [...groups.keys()].sort((a,b) => a-b)) {
    const items = groups.get(l).sort((a,b) => (a.data.rawName || a.data.label || "").localeCompare(b.data.rawName || b.data.label || ""));
    for (let i=0;i<items.length;i++) {
      const rowStart = Math.floor(i/columns)*columns, rowLength = Math.min(columns, items.length-rowStart);
      positions[items[i].data.id] = { x: ((i%columns)-(rowLength-1)/2)*COLUMN_GAP, y: y+Math.floor(i/columns)*ROW_GAP };
    }
    y += Math.ceil(items.length/columns)*ROW_GAP+LAYER_GAP;
  }
  return positions;
}
// Saved positions are only usable when both coordinates are finite numbers.
export function isValidSavedPosition(pos) {
  return !!pos && Number.isFinite(pos.x) && Number.isFinite(pos.y);
}
export function validSavedPositions(positions = {}) {
  return Object.fromEntries(Object.entries(positions || {}).filter(([, p]) => isValidSavedPosition(p)));
}
// Place only nodes that have no saved position, in free space below the saved
// layout. Saved positions are never moved and the new rows cannot overlap them.
export function layoutMissingPositions(graph, savedPositions = {}, columns = 8) {
  const nodes = graph.nodes || [];
  const nodeIds = new Set(nodes.map(n => n.data.id));
  const validSaved = Object.entries(validSavedPositions(savedPositions))
    .filter(([id]) => nodeIds.has(id));
  if (!validSaved.length) return {};
  const savedIds = new Set(validSaved.map(([id]) => id));
  const missing = nodes.filter(n => !savedIds.has(n.data.id));
  if (!missing.length) return {};
  const minX = Math.min(...validSaved.map(([, p]) => p.x));
  const maxX = Math.max(...validSaved.map(([, p]) => p.x));
  const maxY = Math.max(...validSaved.map(([, p]) => p.y));
  const centreX = (minX + maxX) / 2;
  const sorted = missing.slice().sort((a,b) => (a.data.rawName || a.data.label || "").localeCompare(b.data.rawName || b.data.label || ""));
  const positions = {};
  sorted.forEach((n, i) => {
    const row = Math.floor(i / columns), rowStart = row * columns;
    const rowLength = Math.min(columns, sorted.length - rowStart);
    positions[n.data.id] = { x: centreX + ((i % columns) - (rowLength - 1) / 2) * COLUMN_GAP, y: maxY + ROW_GAP + row * ROW_GAP };
  });
  return positions;
}
export function buildForest(graph) {
  const nodes = new Map(graph.nodes.map(n => [n.data.id, n.data]));
  const parents = new Map(), children = new Map();
  // One placement parent per tree node; dependency edges remain in graph view.
  for (const e of placementEdges(graph)) if (!parents.has(e.data.target)) {
    parents.set(e.data.target,e.data.source);
    if (!children.has(e.data.source)) children.set(e.data.source,[]);
    children.get(e.data.source).push(e.data.target);
  }
  const visited = new Set();
  function build(id, path = new Set()) {
    if (!nodes.has(id) || path.has(id) || visited.has(id)) return null;
    visited.add(id); const data = nodes.get(id), next = new Set([...path,id]);
    return { ...data, label: data.rawName || data.label, children: (children.get(id)||[]).map(x => build(x,next)).filter(Boolean) };
  }
  const roots = graph.nodes.filter(n => !parents.has(n.data.id)).map(n => build(n.data.id)).filter(Boolean);
  for (const n of graph.nodes) if (!visited.has(n.data.id)) { const row = build(n.data.id); if (row) roots.push(row); }
  return roots;
}
