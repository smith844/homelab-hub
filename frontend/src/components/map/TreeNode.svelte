<script>
  import { createEventDispatcher } from 'svelte';
  
  export let node;
  export let expandedNodes;
  export let level = 0;
  export let selectedNode = null;
  
  const dispatch = createEventDispatcher();
  
  const TYPE_SHAPES = {
    hardware: "⬡",
    vms: "○",
    apps: "▭",
    storage: "⬬",
    misc: "◇"
  };

  const TYPE_COLORS = {
    hardware: "#C5E1F5",
    vms: "#C8E6C9",
    apps: "#FFE0B2",
    storage: "#E1BEE7",
    misc: "#E0E0E0"
  };
  
  function toggle() {
    dispatch('toggle', node.id);
  }
  
  function handleClick() {
    dispatch('nodeclick', node);
  }
  
  $: isExpanded = expandedNodes.has(node.id);
  $: hasChildren = node.children && node.children.length > 0;
  $: borderColor = node.networkColor || (node.networkName ? (TYPE_COLORS[node.type] || '#999') : '#ffffff');
</script>

<div class="tree-node" style="margin-left: {level * 1.5}rem;">
  <div class="node-header">
    {#if hasChildren}
      <button 
        class="expand-button" 
        on:click={toggle}
      >
        {isExpanded ? '▼' : '▶'}
      </button>
    {:else}
      <span class="expand-spacer"></span>
    {/if}
    
    <div 
      class="node-content" 
      style="border-color: {borderColor}" 
      title="{node.label}"
      on:click={handleClick}
      role="button"
      tabindex="0"
      on:keydown={(e) => e.key === 'Enter' && handleClick()}
    >
      {#if node.imageIcon}
        <img src={node.imageIcon} class="node-icon-img" alt="" />
      {:else if node.icon}
        <span class="node-icon-emoji">{node.icon}</span>
      {:else}
        <span class="node-shape" style="color: {TYPE_COLORS[node.type] || '#999'}">
          {TYPE_SHAPES[node.type] || '○'}
        </span>
      {/if}
      <span class="node-label">{node.label}</span>
      <span class="node-type">{node.type}</span>
      {#if node.networkName}
        <span class="node-network">{node.networkName}</span>
      {/if}
    </div>
  </div>
  
  {#if hasChildren && isExpanded}
    {#each node.children as child}
      <svelte:self 
        node={child} 
        {expandedNodes}
        {selectedNode}
        on:toggle 
        on:nodeclick
        level={level + 1} 
      />
    {/each}
  {/if}
</div>

<style>
  .tree-node {
    margin-bottom: 0.25rem;
  }
  
  .node-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }
  
  .expand-button {
    background: none;
    border: none;
    color: var(--pico-muted-color, #999);
    cursor: pointer;
    padding: 0.25rem;
    font-size: 0.7rem;
    width: 1.5rem;
    height: 1.5rem;
    display: flex;
    align-items: center;
    justify-content: center;
    margin: 0;
  }
  
  .expand-button:hover {
    color: var(--pico-primary, #6366f1);
  }
  
  .expand-spacer {
    width: 1.5rem;
    display: inline-block;
  }
  
  .node-content {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 1rem;
    background: var(--pico-card-background-color, #1e1e2e);
    border: 2px solid;
    border-radius: 6px;
    flex: 1;
    max-width: fit-content;
    cursor: pointer;
    transition: transform 0.1s ease;
  }
  
  .node-content:hover {
    transform: translateX(2px);
  }
  
  .node-icon-img {
    width: 32px;
    height: 32px;
    object-fit: contain;
  }
  
  .node-icon-emoji {
    font-size: 24px;
  }
  
  .node-shape {
    font-size: 28px;
  }
  
  .node-label {
    font-weight: 500;
    color: var(--pico-color, #25384a);
    font-size: 1rem;
  }
  
  .node-type {
    font-size: 0.85rem;
    color: var(--pico-muted-color, #999);
    font-style: italic;
  }
  
  .node-network {
    font-size: 0.8rem;
    color: var(--pico-muted-color, #aaa);
    padding: 0.2rem 0.5rem;
    background: rgba(255, 255, 255, 0.05);
    border-radius: 4px;
    margin-left: auto;
  }
</style>
