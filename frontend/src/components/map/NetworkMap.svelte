<script>
  import { onMount, onDestroy } from "svelte";
  import cytoscape from "cytoscape";
  import { get } from "../../lib/api.js";
  import { addToast } from "../../lib/stores.js";
  import { theme, readPreference, savePreference } from "../../lib/preferences.js";

  import { layoutPositions, layoutMissingPositions, validSavedPositions, ROW_GAP } from "../../lib/mapViews.js";
  import { groupedLayoutPositions, hasStaleGroupedLayout, anchorsStorageKey, layoutStorageKey, presentationEdges, validAnchors } from "../../lib/grouping.js";
  export let graphData = null;
  export let viewKey = "all";
  export let mode = "graph";
  const READABLE_ZOOM = 0.8;
  const VIEW_MARGIN = 60;
  const GROUP_STATE_KEY = "hlh.mapGroupExpanded";
  let disposed = false;
  let resizeObserver;
  let expandedGroups = new Set();
  let groupAnchors = {};

  let container;
  let cy;
  let saveTimeout;
  let networks = [];
  let selectedNode = null;
  let selectedNodeDetails = null;
  let loadingDetails = false;
  let tooltip = { visible: false, text: "", x: 0, y: 0 };
  
  $: if (cy) {
    const dark = $theme === "dark";
    const textColor = dark ? "#e3ecf4" : "#25384a";
    const mutedColor = dark ? "#a5b6c7" : "#637487";
    cy.nodes().forEach((n) => n.style("color", textColor));
    cy.edges().forEach((e) => e.style("color", mutedColor));
    cy.nodes('[type="group"]').style("background-color", dark ? "#1f3a4d" : "#eef4f8");
    cy.nodes('[type="group"]:not([groupColor])').style("border-color", dark ? "#74d2cb" : "#126e77");
  }

  async function loadNodeDetails(node) {
    if (!node) return;
    loadingDetails = true;
    try {
      const response = await get(`/${node.type}/${node.entity_id}`);
      selectedNodeDetails = response.data;
    } catch (e) {
      console.error('Failed to load node details:', e);
      selectedNodeDetails = null;
    }
    loadingDetails = false;
  }

  $: if (selectedNode) {
    if (selectedNode.type === "group") {
      selectedNodeDetails = null;
      loadingDetails = false;
    } else {
      loadNodeDetails(selectedNode);
    }
  } else {
    selectedNodeDetails = null;
    loadingDetails = false;
  }

  const NODE_STYLES = {
    hardware:  { shape: "hexagon",          color: "#C5E1F5" },  // Pastel blue
    vms:       { shape: "ellipse",          color: "#C8E6C9" },  // Pastel green
    apps:      { shape: "round-rectangle", color: "#FFE0B2", width: 64, height: 64 },  // Pastel orange
    storage:   { shape: "barrel",           color: "#E1BEE7" },  // Pastel purple
    shares:    { shape: "round-tag",        color: "#FFF9C4" },  // Pastel yellow
    misc:      { shape: "diamond",          color: "#E0E0E0" },  // Light gray
  };

  onMount(async () => {
    try {
      const [graphRes, layoutRes, networksRes] = await Promise.all([
        graphData ? Promise.resolve(graphData) : get("/map/graph"),
        Promise.resolve({data: readPreference(layoutStorageKey(mode, viewKey), {})}),
        get("/map/networks"),
      ]);

      if (disposed) return;
      const storedExpanded = readPreference(GROUP_STATE_KEY, []);
      expandedGroups = new Set(
        Array.isArray(storedExpanded) ? storedExpanded.filter((id) => typeof id === "string") : []
      );
      // Only finite saved coordinates are applied or counted as saved.
      const savedPositions = validSavedPositions(layoutRes.data);
      groupAnchors = mode === "grouped"
        ? validAnchors(readPreference(anchorsStorageKey(viewKey), {}))
        : {};
      const anchoredMemberIds = new Set();
      for (const node of graphRes.nodes) {
        if (node.data.type === "group" && groupAnchors[node.data.id]) {
          (node.data.memberIds || []).forEach((id) => anchoredMemberIds.add(id));
        }
      }
      const staleGroupedLayout = mode === "grouped" &&
        hasStaleGroupedLayout(graphRes, savedPositions, [...expandedGroups], groupAnchors);
      const missingPositions = mode === "grouped" ? {} : layoutMissingPositions(graphRes, savedPositions);
      const groupedPositions = mode === "grouped"
        ? groupedLayoutPositions(graphRes, [...expandedGroups], groupAnchors)
        : {};
      networks = networksRes.networks || [];

      // Manual group anchors and the layout are applied first; saved positions
      // fill in everything else.
      const nodes = graphRes.nodes.map((n) => {
        const anchor = groupAnchors[n.data.id];
        if (anchor) {
          n.position = { x: anchor.x, y: anchor.y };
          return n;
        }
        if (mode === "grouped" && anchoredMemberIds.has(n.data.id) && groupedPositions[n.data.id]) {
          n.position = groupedPositions[n.data.id];
          return n;
        }
        const saved = staleGroupedLayout ? null : savedPositions[n.data.id];
        if (saved) {
          n.position = { x: saved.x, y: saved.y };
          // Don't lock nodes - they should always be draggable
        } else if (groupedPositions[n.data.id]) {
          n.position = groupedPositions[n.data.id];
        } else if (missingPositions[n.data.id]) {
          n.position = missingPositions[n.data.id];
        }
        return n;
      });

      cy = cytoscape({
        container,
        elements: { nodes, edges: graphRes.edges },
        style: [
          {
            selector: "node",
            style: {
              label: node => node.data("rawName") || node.data("label"),
              "text-margin-y": 10,
              "text-valign": "bottom",
              "text-halign": "center",
              "font-size": "14px",
              "font-weight": "400",
              "font-family": "system-ui, -apple-system, Roboto, sans-serif",
              "font-style": "normal",
              "text-outline-width": 0,
              width: 48,
              height: 48,
              "text-wrap": "wrap",
              "text-max-width": "160px",
              "background-color": "#FFFFFF",
              "border-width": 2,
              "border-color": "#999",
              "border-style": "solid",
            },
          },
          // Nodes with emoji icons - larger emoji only, no text, no italic
          {
            selector: "node[icon]",
            style: {
              "font-size": "14px",
              "font-style": "normal",
              width: 64,
              height: 64,
            },
          },
          // Nodes with image icons - use background image
          {
            selector: "node[imageIcon]",
            style: {
              "background-image": "data(imageIcon)",
              "background-fit": "contain",
              "background-clip": "none",
              "background-width": "70%",
              "background-height": "70%",
              width: 64,
              height: 64,
              label: node => node.data("rawName") || node.data("label"),
            },
          },
          // Per-type styles
          ...Object.entries(NODE_STYLES).map(([type, s]) => ({
            selector: `node[type="${type}"]`,
            style: {
              shape: s.shape,
              "background-color": s.color,
            },
          })),
          // Override color for nodes with network color
          {
            selector: "node[networkColor]",
            style: {
              "border-width": 3,
              "border-color": "data(networkColor)",
              "border-style": "solid",
            },
          },
          {
            selector: "edge",
            style: {
              width: 2,
              "line-color": "#666",
              "target-arrow-color": "#666",
              "target-arrow-shape": "triangle",
              "curve-style": "bezier",
              label: "data(label)",
              "font-size": "9px",
              color: "#999",
              "text-rotation": "autorotate",
            },
          },
          {
            selector: "edge[?manual]",
            style: {
              "line-style": "dashed",
              "line-color": "#888",
            },
          },
          {
            selector: ".constraint-edge",
            style: {
              opacity: 0,  // Make invisible
              "z-index": -1,
            },
          },
          {
            selector: 'node[type="group"]',
            style: {
              shape: "round-rectangle",
              width: 220,
              height: 92,
              "background-color": "#eef4f8",
              "border-width": 2,
              "border-color": "#126e77",
              "font-size": "14px",
              "font-weight": "600",
              "text-valign": "center",
              "text-halign": "center",
              "text-wrap": "wrap",
              "text-max-width": "190px",
              "text-margin-y": 0,
            },
          },
          {
            selector: "node[groupImage]",
            style: {
              "background-image": "data(groupImage)",
              "background-image-crossorigin": "anonymous",
              "background-fit": "contain",
              "background-width": "28px",
              "background-height": "28px",
              "background-position-y": "12px",
              "text-margin-y": 18,
            },
          },
          {
            selector: "node[groupColor]",
            style: {
              "border-width": 3,
              "border-color": "data(groupColor)",
            },
          },
          {
            selector: ".group-hidden",
            style: {
              display: "none",
            },
          },
          {
            selector: "edge.aggregate-edge",
            style: {
              width: 2,
              "line-style": "dashed",
              "line-color": "#9aa7b4",
              "target-arrow-shape": "triangle",
              "target-arrow-color": "#9aa7b4",
              "curve-style": "bezier",
              opacity: 0.75,
              label: "",
            },
          },
          {
            selector: "edge.group-parent-edge",
            style: {
              width: 2,
              "line-color": "#9aa7b4",
              "target-arrow-shape": "triangle",
              "target-arrow-color": "#9aa7b4",
              "curve-style": "bezier",
              label: "",
            },
          },
          {
            selector: "edge.group-member-edge",
            style: {
              width: 2,
              "line-style": "dashed",
              "line-color": "#b6c2cf",
              "target-arrow-shape": "triangle",
              "target-arrow-color": "#b6c2cf",
              "curve-style": "bezier",
              opacity: 0.9,
              label: "",
            },
          },
          {
            selector: ".group-hidden-edge",
            style: {
              display: "none",
            },
          },
        ],
        layout: { name: "preset" }, // Use saved positions first
        minZoom: 0.1,
        maxZoom: 3,
      });

      // Keep the canvas dimensions in sync without touching the user's view.
      if (typeof ResizeObserver !== "undefined") {
        resizeObserver = new ResizeObserver(() => {
          if (cy) cy.resize();
        });
        resizeObserver.observe(container);
      }

      // Only auto-layout when no node has a saved position.
      const hasSavedPositions = nodes.some((n) => savedPositions[n.data.id]);
      if (mode === "grouped") {
        applyGroupState();
        refreshGroupEdges();
        readableView();
      } else if (!hasSavedPositions && nodes.length > 0) {
        runDagreLayout();
      } else if (hasSavedPositions) {
        readableView();
      }

      // Persist positions on drag end. Dragging a group card promotes it to a
      // manual anchor that survives expansion/collapse and reloads.
      cy.on("dragfree", "node", (evt) => {
        const node = evt.target;
        if (mode === "grouped" && node.data("type") === "group") {
          groupAnchors = {
            ...groupAnchors,
            [node.id()]: { x: node.position().x, y: node.position().y },
          };
          savePreference(anchorsStorageKey(viewKey), groupAnchors);
          reapplyGroupedLayout();
          refreshGroupEdges();
          applyEdgeHighlight(selectedNode ? selectedNode.id : null);
        }
        debounceSaveLayout();
      });

      // Show details on tap. Group cards also toggle expansion directly.
      cy.on("tap", "node", (evt) => {
        const node = evt.target;
        selectedNode = node.data();
        if (node.data("type") === "group") {
          toggleGroup(node);
          selectedNode = { ...node.data() };
          applyEdgeHighlight(node.id());
        } else {
          applyEdgeHighlight(selectedNode.id);
        }
      });

      // Deselect when clicking background
      cy.on("tap", (evt) => {
        if (evt.target === cy) {
          selectedNode = null;
          applyEdgeHighlight(null);
        }
      });

      // Show tooltip on hover
      cy.on("mouseover", "node", (evt) => {
        const node = evt.target;
        const renderedPosition = node.renderedPosition();
        tooltip = {
          visible: true,
          text: node.data("rawName") || node.data("label"),
          x: renderedPosition.x + 45,
          y: renderedPosition.y
        };
      });

      cy.on("mouseout", "node", () => {
        tooltip.visible = false;
      });
    } catch (e) {
      addToast("Failed to load map: " + e.message, "error");
    }
  });

  onDestroy(() => {
    disposed = true;
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    if (cy) cy.destroy();
    clearTimeout(saveTimeout);
  });

  function runDagreLayout() {
    if (!cy) return;
    if (mode === "grouped") {
      const positions = groupedLayoutPositions({
        nodes: cy.nodes().map((n) => ({ id: n.id(), data: n.data() })),
        edges: cy.edges()
          .filter((e) => !e.hasClass("virtual-edge"))
          .map((e) => ({ id: e.id(), data: e.data() })),
      }, [...expandedGroups], groupAnchors);
      cy.batch(() => cy.nodes().forEach((node) => {
        const position = positions[node.id()];
        if (position) node.position(position);
      }));
    } else {
      const positions = layoutPositions({nodes: cy.nodes().map(n => ({data:n.data()})), edges: cy.edges().map(e => ({data:e.data()}))});
      cy.batch(() => cy.nodes().forEach(node => node.position(positions[node.id()])));
    }
    readableView();
  }

  function visibleElements() {
    if (!cy) return [];
    return cy.elements().filter((element) => element.style("display") !== "none");
  }

  export function fitView() {
    if (!cy) return;
    const visible = visibleElements();
    if (visible.length) cy.fit(visible, 50);
  }
  export function readableView() {
    if (!cy) return;
    const visible = visibleElements();
    const nodes = visible.filter((element) => element.isNode());
    if (!nodes.length) return;

    if (mode === "grouped") {
      // Prioritise the host + category cards for the initial readable overview.
      const focus = nodes.filter(
        (node) => node.data("type") === "hardware" || node.data("type") === "group"
      );
      const target = focus.length ? focus : nodes;
      cy.fit(target, 60);
      if (cy.zoom() >= READABLE_ZOOM) return;
      cy.zoom(READABLE_ZOOM);
      const zoom = cy.zoom();
      const bb = target.boundingBox();
      const w = cy.width(), h = cy.height();
      const minPanX = w - zoom * bb.x2 - VIEW_MARGIN, maxPanX = -zoom * bb.x1 + VIEW_MARGIN;
      const minPanY = h - zoom * bb.y2 - VIEW_MARGIN, maxPanY = -zoom * bb.y1 + VIEW_MARGIN;
      let panX = w / 2 - zoom * (bb.x1 + bb.x2) / 2;
      let panY = VIEW_MARGIN - zoom * bb.y1;
      panX = minPanX > maxPanX ? (w - zoom * (bb.x1 + bb.x2)) / 2 : Math.min(Math.max(panX, minPanX), maxPanX);
      panY = minPanY > maxPanY ? (h - zoom * (bb.y1 + bb.y2)) / 2 : Math.min(Math.max(panY, minPanY), maxPanY);
      cy.pan({ x: panX, y: panY });
      return;
    }

    cy.fit(visible, 40);
    if (cy.zoom() >= READABLE_ZOOM) return;
    cy.zoom(READABLE_ZOOM);
    const zoom = cy.zoom();
    const bb = nodes.boundingBox();
    // Focus the whole root/top layer rather than a single arbitrary node.
    const minY = Math.min(...nodes.map((n) => n.position().y));
    const topLayer = nodes.filter((n) => n.position().y <= minY + ROW_GAP).boundingBox();
    const w = cy.width(), h = cy.height();
    const minPanX = w - zoom * bb.x2 - VIEW_MARGIN, maxPanX = -zoom * bb.x1 + VIEW_MARGIN;
    const minPanY = h - zoom * bb.y2 - VIEW_MARGIN, maxPanY = -zoom * bb.y1 + VIEW_MARGIN;
    let panX = w / 2 - zoom * (topLayer.x1 + topLayer.x2) / 2;
    let panY = VIEW_MARGIN - zoom * topLayer.y1;
    panX = minPanX > maxPanX ? (w - zoom * (bb.x1 + bb.x2)) / 2 : Math.min(Math.max(panX, minPanX), maxPanX);
    panY = minPanY > maxPanY ? (h - zoom * (bb.y1 + bb.y2)) / 2 : Math.min(Math.max(panY, minPanY), maxPanY);
    cy.pan({ x: panX, y: panY });
  }

  function applyGroupState() {
    if (!cy || mode !== "grouped") return;
    cy.nodes('[type="group"]').forEach((group) => {
      const expanded = expandedGroups.has(group.id());
      group.data("expanded", expanded);
      (group.data("memberIds") || []).forEach((memberId) => {
        const member = cy.getElementById(memberId);
        if (member.length) member.toggleClass("group-hidden", !expanded);
      });
    });
  }

  function reapplyGroupedLayout() {
    if (!cy || mode !== "grouped") return;
    const positions = groupedLayoutPositions(
      {
        nodes: cy.nodes().map((node) => ({ id: node.id(), data: node.data() })),
        edges: cy.edges()
          .filter((edge) => !edge.hasClass("virtual-edge"))
          .map((edge) => ({ id: edge.id(), data: edge.data() })),
      },
      [...expandedGroups],
      groupAnchors
    );
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const position = positions[node.id()];
        if (position) node.position(position);
      });
    });
  }

  function refreshGroupEdges() {
    if (!cy || mode !== "grouped") return;
    const grouped = {
      nodes: cy.nodes().map((node) => ({ id: node.id(), data: node.data() })),
      edges: cy.edges()
        .filter((edge) => !edge.hasClass("virtual-edge"))
        .map((edge) => ({ id: edge.id(), data: edge.data() })),
    };
    const { virtual, hiddenEdgeIds } = presentationEdges(grouped, [...expandedGroups]);
    const hidden = new Set(hiddenEdgeIds);

    cy.edges()
      .filter((edge) => !edge.hasClass("virtual-edge"))
      .forEach((edge) => {
        edge.toggleClass("group-hidden-edge", hidden.has(edge.id()));
      });

    cy.remove(cy.edges(".virtual-edge"));
    if (virtual.length) {
      const classes = {
        "group-parent": "group-parent-edge",
        "group-member": "group-member-edge",
        aggregate: "aggregate-edge",
      };
      cy.batch(() => {
        virtual.forEach((element) => {
          const edge = cy.add({ group: "edges", data: element.data });
          edge
            .addClass("virtual-edge")
            .addClass(classes[element.data.kind] || "aggregate-edge");
        });
      });
    }
  }

  function ensureGroupVisible(group) {
    if (!cy || !group) return;
    const position = group.renderedPosition();
    const margin = 80;
    const w = cy.width(), h = cy.height();
    let dx = 0, dy = 0;
    if (position.x < margin) dx = margin - position.x;
    else if (position.x > w - margin) dx = (w - margin) - position.x;
    if (position.y < margin) dy = margin - position.y;
    else if (position.y > h - margin) dy = (h - margin) - position.y;
    if (dx || dy) cy.pan({ x: cy.pan().x + dx, y: cy.pan().y + dy });
  }

  function toggleGroup(group) {
    if (!cy || !group) return;
    const id = group.id();
    if (expandedGroups.has(id)) expandedGroups.delete(id);
    else expandedGroups.add(id);
    savePreference(GROUP_STATE_KEY, [...expandedGroups]);
    applyGroupState();
    reapplyGroupedLayout();
    refreshGroupEdges();
    if (selectedNode && selectedNode.type === "group" && selectedNode.id === id) {
      selectedNode = { ...group.data() };
    }
    if (selectedNode && selectedNode.type !== "group") {
      const selected = cy.getElementById(selectedNode.id);
      if (!selected.length || selected.hasClass("group-hidden")) {
        selectedNode = null;
      }
    }
    ensureGroupVisible(group);
    applyEdgeHighlight(selectedNode ? selectedNode.id : null);
  }

  function toggleSelectedGroup() {
    if (!cy || !selectedNode || selectedNode.type !== "group") return;
    toggleGroup(cy.getElementById(selectedNode.id));
  }

  function applyEdgeHighlight(nodeId) {
    if (!cy) return;
    const edges = cy.edges();
    const colorOf = (edge) => {
      if (edge.hasClass("group-parent-edge")) return "#9aa7b4";
      if (edge.hasClass("group-member-edge")) return "#b6c2cf";
      if (edge.hasClass("aggregate-edge")) return "#9aa7b4";
      return "#666";
    };
    const isVirtual = (edge) => edge.hasClass("virtual-edge");
    const reset = (edge) => {
      edge.style("width", 2);
      edge.style("line-color", colorOf(edge));
      edge.style("opacity", isVirtual(edge) ? 0.75 : 1);
    };
    if (!nodeId) {
      edges.forEach(reset);
      return;
    }
    const connected = new Set();
    const node = cy.getElementById(nodeId);
    if (node) {
      node.connectedEdges().forEach((e) => connected.add(e.id()));
    }
    edges.forEach((e) => {
      const active = connected.has(e.id());
      const virtual = isVirtual(e);
      e.style("width", active ? 3 : virtual ? 2 : 1);
      e.style("line-color", active ? colorOf(e) : virtual ? colorOf(e) : "#999");
      e.style("opacity", active ? 1 : virtual ? 0.65 : 0.25);
    });
  }

  function debounceSaveLayout() {
    clearTimeout(saveTimeout);
    saveTimeout = setTimeout(saveLayout, 500);
  }

  async function saveLayout() {
    if (!cy) return;
    const positions = {};
    cy.nodes().forEach((node) => {
      // Do not persist hidden (collapsed member) positions: they are laid out
      // again when the group is expanded.
      if (mode === "grouped" && node.hasClass("group-hidden")) return;
      const pos = node.position();
      positions[node.id()] = { x: pos.x, y: pos.y, pinned: true };
    });
    try {
      if (!savePreference(layoutStorageKey(mode, viewKey), positions)) addToast("Could not save map layout in this browser", "error");
    } catch (e) {
      // silent fail on layout save
    }
  }

  export function relayout() {
    if (mode === "grouped") {
      // Explicit Auto layout resets manual group anchors.
      groupAnchors = {};
      savePreference(anchorsStorageKey(viewKey), {});
    }
    runDagreLayout();
    debounceSaveLayout();
  }
</script>

<div class="cy-container" bind:this={container}></div>

{#if tooltip.visible}
  <div class="node-tooltip" style="left: {tooltip.x}px; top: {tooltip.y}px;">
    {tooltip.text}
  </div>
{/if}

{#if selectedNode}
  {#if selectedNode.type === "group"}
    <div class="info-panel">
      <div class="info-header">
        <h3>{selectedNode.kind === "ungrouped" ? "Ungrouped" : selectedNode.label}</h3>
        <button class="close-btn" on:click={() => { selectedNode = null; applyEdgeHighlight(null); }}>×</button>
      </div>
      <div class="info-content">
        <div class="info-item">
          <span class="info-label">Host:</span>
          <span class="info-value">{selectedNode.hostLabel}</span>
        </div>
        <div class="info-item">
          <span class="info-label">Members:</span>
          <span class="info-value">{selectedNode.visibleMembers} in inventory · {selectedNode.unmatchedMembers} not in inventory</span>
        </div>
        {#if selectedNode.members && selectedNode.members.length}
          <div class="info-item notes">
            <span class="info-label">Containers:</span>
            <span class="info-value group-member-list">
              {#each selectedNode.members as member}
                <a href={`#/inventory/${member.type}/${member.entity_id}`}>{member.label}</a>
              {/each}
            </span>
          </div>
        {/if}
        {#if selectedNode.unmatchedLabels && selectedNode.unmatchedLabels.length}
          <div class="info-item notes">
            <span class="info-label">Not in inventory:</span>
            <span class="info-value">{selectedNode.unmatchedLabels.join(", ")}</span>
          </div>
        {/if}
      </div>
      <div class="info-footer">
        <button class="secondary outline small" on:click={toggleSelectedGroup}>{selectedNode.expanded ? "Collapse group" : "Expand group"}</button>
      </div>
    </div>
  {:else}
  <div class="info-panel">
    <div class="info-header">
      <h3>
        {#if selectedNode.icon}
          <span class="node-icon">{selectedNode.icon}</span>
        {/if}
        {selectedNode.rawName || selectedNode.label}
      </h3>
      <button class="close-btn" on:click={() => { selectedNode = null; applyEdgeHighlight(null); }}>×</button>
    </div>
    <div class="info-content">
      <div class="info-item">
        <span class="info-label">Type:</span>
        <span class="info-value">{selectedNode.type}</span>
      </div>
      {#if loadingDetails}
        <div class="info-item">
          <span class="info-label">Loading...</span>
        </div>
      {:else if selectedNodeDetails}
        {#if selectedNodeDetails.hostname}
          <div class="info-item">
            <span class="info-label">Hostname:</span>
            <span class="info-value">{selectedNodeDetails.hostname}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.ip_address || selectedNodeDetails.ip}
          <div class="info-item">
            <span class="info-label">IP Address:</span>
            <span class="info-value">{selectedNodeDetails.ip_address || selectedNodeDetails.ip}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.mac_address}
          <div class="info-item">
            <span class="info-label">MAC Address:</span>
            <span class="info-value">{selectedNodeDetails.mac_address}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.os}
          <div class="info-item">
            <span class="info-label">OS:</span>
            <span class="info-value">{selectedNodeDetails.os}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.cpu}
          <div class="info-item">
            <span class="info-label">CPU:</span>
            <span class="info-value">{selectedNodeDetails.cpu}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.cpu_cores}
          <div class="info-item">
            <span class="info-label">CPU Cores:</span>
            <span class="info-value">{selectedNodeDetails.cpu_cores}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.ram_gb}
          <div class="info-item">
            <span class="info-label">RAM:</span>
            <span class="info-value">{selectedNodeDetails.ram_gb} GB</span>
          </div>
        {/if}
        {#if selectedNodeDetails.port}
          <div class="info-item">
            <span class="info-label">Port:</span>
            <span class="info-value">{selectedNodeDetails.port}</span>
          </div>
        {/if}
        {#if selectedNode.type === 'apps' && selectedNodeDetails.port && (selectedNodeDetails.hostname || selectedNodeDetails.ip_address)}
          <div class="info-item">
            <span class="info-label">Link:</span>
            <span class="info-value">
              <a href="{selectedNodeDetails.https ? 'https' : 'http'}://{selectedNodeDetails.hostname || selectedNodeDetails.ip_address}:{selectedNodeDetails.port}" target="_blank" rel="noopener noreferrer">
                {selectedNodeDetails.hostname || selectedNodeDetails.ip_address}:{selectedNodeDetails.port}
              </a>
            </span>
          </div>
        {/if}
        {#if selectedNodeDetails.external_hostname}
          <div class="info-item">
            <span class="info-label">External Host:</span>
            <span class="info-value">{selectedNodeDetails.external_hostname}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.storage_type}
          <div class="info-item">
            <span class="info-label">Storage Type:</span>
            <span class="info-value">{selectedNodeDetails.storage_type}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.raid_type}
          <div class="info-item">
            <span class="info-label">RAID:</span>
            <span class="info-value">{selectedNodeDetails.raid_type}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.raw_space_tb}
          <div class="info-item">
            <span class="info-label">Raw Space:</span>
            <span class="info-value">{selectedNodeDetails.raw_space_tb} TB</span>
          </div>
        {/if}
        {#if selectedNodeDetails.usable_space_tb}
          <div class="info-item">
            <span class="info-label">Usable Space:</span>
            <span class="info-value">{selectedNodeDetails.usable_space_tb} TB</span>
          </div>
        {/if}
        {#if selectedNodeDetails.filesystem}
          <div class="info-item">
            <span class="info-label">Filesystem:</span>
            <span class="info-value">{selectedNodeDetails.filesystem}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.category}
          <div class="info-item">
            <span class="info-label">Category:</span>
            <span class="info-value">{selectedNodeDetails.category}</span>
          </div>
        {/if}
        {#if selectedNodeDetails.description}
          <div class="info-item">
            <span class="info-label">Description:</span>
            <span class="info-value">{selectedNodeDetails.description}</span>
          </div>
        {/if}
      {/if}
      {#if selectedNode.networkName}
        <div class="info-item">
          <span class="info-label">Network:</span>
          <span class="info-value">
            <span class="network-indicator" style="background-color: {selectedNode.networkColor}"></span>
            {selectedNode.networkName}
          </span>
        </div>
      {/if}
      {#if selectedNodeDetails && selectedNodeDetails.share_type}
        <div class="info-item">
          <span class="info-label">Share Type:</span>
          <span class="info-value">{selectedNodeDetails.share_type}</span>
        </div>
      {/if}
      {#if selectedNodeDetails && selectedNodeDetails.notes}
        <div class="info-item notes">
          <span class="info-label">Notes:</span>
          <span class="info-value">{selectedNodeDetails.notes}</span>
        </div>
      {/if}
    </div>
    <div class="info-footer">
      <a href="#/inventory/{selectedNode.type}/{selectedNode.entity_id}" class="view-link">View in Inventory →</a>
    </div>
  </div>
  {/if}
{/if}

<div class="networks-panel">
  <h3>Networks</h3>
  {#if networks.length > 0}
    <div class="network-list">
      {#each networks as network}
        <div class="network-item">
          <span class="network-color" style="background-color: {network.color}"></span>
          <span class="network-name">{network.name}</span>
          {#if network.vlan_id}
            <span class="network-vlan">VLAN {network.vlan_id}</span>
          {/if}
        </div>
      {/each}
    </div>
  {:else}
    <p class="empty-state">No networks configured</p>
  {/if}
  

</div>

<div class="legend">
  <div class="legend-item">
    <svg width="24" height="24" viewBox="0 0 16 16">
      <polygon points="8,1 15,5 15,11 8,15 1,11 1,5" fill="#C5E1F5" stroke="#999" stroke-width="1"/>
    </svg>
    <span>hardware</span>
  </div>
  <div class="legend-item">
    <svg width="24" height="24" viewBox="0 0 16 16">
      <circle cx="8" cy="8" r="7" fill="#C8E6C9" stroke="#999" stroke-width="1"/>
    </svg>
    <span>vms</span>
  </div>
  <div class="legend-item">
    <svg width="24" height="24" viewBox="0 0 16 16">
      <rect x="2" y="2" width="12" height="12" rx="2" fill="#FFE0B2" stroke="#999" stroke-width="1"/>
    </svg>
    <span>apps</span>
  </div>
  <div class="legend-item">
    <svg width="24" height="24" viewBox="0 0 16 16">
      <ellipse cx="8" cy="3" rx="6" ry="2" fill="#E1BEE7" stroke="#999" stroke-width="1"/>
      <rect x="2" y="3" width="12" height="10" fill="#E1BEE7" stroke="none"/>
      <ellipse cx="8" cy="13" rx="6" ry="2" fill="#E1BEE7" stroke="#999" stroke-width="1"/>
      <line x1="2" y1="3" x2="2" y2="13" stroke="#999" stroke-width="1"/>
      <line x1="14" y1="3" x2="14" y2="13" stroke="#999" stroke-width="1"/>
    </svg>
    <span>storage</span>
  </div>
  <div class="legend-item">
    <svg width="24" height="24" viewBox="0 0 16 16">
      <polygon points="8,1 15,8 8,15 1,8" fill="#E0E0E0" stroke="#999" stroke-width="1"/>
    </svg>
    <span>misc</span>
  </div>
</div>

<style>
  .cy-container {
    width: 100%;
    height: 100%;
    min-height: 400px;
  }
  .info-panel {
    position: absolute;
    top: 0.75rem;
    left: 0.75rem;
    background: var(--pico-card-background-color);
    max-height: calc(100% - 1.5rem);
    overflow-y: auto;
    z-index: 10;
    padding: 0;
    border-radius: 6px;
    min-width: 280px;
    max-width: 350px;
    color: var(--pico-color);
    border: 1px solid var(--pico-muted-border-color);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.5);
  }
  .info-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--pico-muted-border-color, #333);
  }
  .info-header h3 {
    color: var(--pico-color);
    margin: 0;
    font-size: 1rem;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .node-icon {
    font-size: 1.5rem;
  }
  .close-btn {
    background: transparent;
    border: none;
    color: var(--pico-muted-color, #999);
    font-size: 1.5rem;
    cursor: pointer;
    padding: 0;
    width: 24px;
    height: 24px;
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 3px;
    transition: all 0.2s;
  }
  .close-btn:hover {
    background: var(--pico-muted-border-color, rgba(128, 128, 128, 0.25));
    color: var(--pico-color, #fff);
  }
  .info-content {
    padding: 1rem;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }
  .info-item {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 0.9rem;
  }
  .info-item.notes {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.3rem;
  }
  .info-item.notes .info-value {
    white-space: pre-wrap;
    font-size: 0.85rem;
    color: var(--pico-color);
    font-style: italic;
  }
  .info-label {
    color: var(--pico-muted-color, #999);
    font-weight: 500;
  }
  .info-value {
    color: var(--pico-color);
    word-break: break-word;
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .group-member-list {
    flex-direction: column;
    align-items: flex-start;
    gap: 0.2rem;
    max-height: 180px;
    overflow-y: auto;
  }
  .network-indicator {
    width: 12px;
    height: 12px;
    border-radius: 2px;
    display: inline-block;
    border: 1px solid rgba(255, 255, 255, 0.3);
  }
  .info-footer {
    padding: 0.75rem 1rem;
    border-top: 1px solid var(--pico-muted-border-color, #333);
  }
  .view-link {
    color: var(--pico-primary, #6366f1);
    text-decoration: none;
    font-size: 0.9rem;
    font-weight: 500;
    transition: color 0.2s;
  }
  .view-link:hover {
    color: var(--pico-primary-hover, #818cf8);
  }
  .networks-panel {
    position: absolute;
    top: 0.75rem;
    right: 0.75rem;
    background: var(--pico-card-background-color, #1e1e2e);
    padding: 0.75rem;
    border-radius: 6px;
    min-width: 200px;
    max-width: 300px;
    color: var(--pico-color, #fff);
    border: 1px solid var(--pico-muted-border-color, #333);
  }
  .networks-panel h3 {
    margin: 0 0 0.75rem 0;
    font-size: 0.9rem;
    color: var(--pico-color, #ccc);
    border-bottom: 1px solid var(--pico-muted-border-color, #333);
    padding-bottom: 0.5rem;
  }
  .network-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  .network-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.85rem;
  }
  .network-color {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    flex-shrink: 0;
    border: 1px solid var(--pico-muted-border-color, rgba(128, 128, 128, 0.4));
  }
  .network-name {
    flex: 1;
    font-weight: 500;
  }
  .network-vlan {
    font-size: 0.75rem;
    color: var(--pico-muted-color, #999);
  }
  .empty-state {
    font-size: 0.8rem;
    color: var(--pico-muted-color, #999);
    margin: 0;
    font-style: italic;
  }
  .legend {
    position: absolute;
    bottom: 0.75rem;
    left: 0.75rem;
    display: flex;
    gap: 1rem;
    background: var(--pico-card-background-color, #1e1e2e);
    padding: 0.6rem 1rem;
    border-radius: 8px;
    font-size: 0.9rem;
    color: var(--pico-color, #ddd);
    border: 1px solid var(--pico-muted-border-color, #333);
  }
  .legend-item {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  .legend-item svg {
    flex-shrink: 0;
  }
  .node-tooltip {
    position: absolute;
    background: var(--pico-card-background-color, #1e1e2e);
    color: var(--pico-color, #fff);
    padding: 0.4rem 0.7rem;
    border-radius: 4px;
    font-size: 0.85rem;
    pointer-events: none;
    z-index: 1000;
    white-space: nowrap;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
    transform: translate(0, -50%);
    border: 1px solid var(--pico-muted-border-color, #333);
  }
</style>
