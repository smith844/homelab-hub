export const TYPES = ["hardware", "vms", "apps", "storage", "shares", "misc"];
export const TYPE_LABELS = { hardware: "Hosts", vms: "VMs / LXCs / runtimes", apps: "Applications", storage: "Storage", shares: "Shares", misc: "Other devices" };
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
  const levels = new Map();
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
  }
  const search = query.trim().toLowerCase();
  const matches = nodes.filter(n => scope.has(n.data.id) && types.includes(n.data.type) &&
    (!search || `${n.data.rawName || n.data.label || ""} ${n.data.networkName || ""}`.toLowerCase().includes(search)) &&
    (depth === "all" || !root || members.length || levels.get(n.data.id) <= Number(depth)));
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
// Layered grid wraps large layers instead of forcing all containers into a row.
export function layoutPositions(graph, columns = 8) {
  const placement = placementEdges(graph), nodes = graph.nodes;
  const level = new Map(nodes.map(n => [n.data.id, 0]));
  for (let i = 0; i < 4; i++) for (const e of placement)
    level.set(e.data.target, Math.max(level.get(e.data.target), level.get(e.data.source) + 1));
  const groups = new Map();
  for (const n of nodes) { const l = level.get(n.data.id); if (!groups.has(l)) groups.set(l, []); groups.get(l).push(n); }
  const positions = {}; let y = 0;
  for (const l of [...groups.keys()].sort((a,b) => a-b)) {
    const items = groups.get(l).sort((a,b) => (a.data.rawName || a.data.label || "").localeCompare(b.data.rawName || b.data.label || ""));
    for (let i=0;i<items.length;i++) {
      const rowStart = Math.floor(i/columns)*columns, rowLength = Math.min(columns, items.length-rowStart);
      positions[items[i].data.id] = { x: ((i%columns)-(rowLength-1)/2)*160, y: y+Math.floor(i/columns)*130 };
    }
    y += Math.ceil(items.length/columns)*130+80;
  }
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
