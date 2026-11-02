<script>
  import { groupIcon } from '../lib/groupIcons.js';
  export let value = null;
  let failedSource = '';
  $: icon = groupIcon(value);
</script>

<span class="group-icon" aria-hidden="true">
  {#if icon.image && failedSource !== icon.image}
    <img src={icon.image} alt="" referrerpolicy="no-referrer" on:error={() => failedSource = icon.image} />
  {:else}
    {icon.text || '📁'}
  {/if}
</span>

<style>
  .group-icon { display: inline-flex; align-items: center; justify-content: center; width: 1.5rem; height: 1.5rem; vertical-align: middle; margin-right: .3rem; }
  img { width: 100%; height: 100%; object-fit: contain; }
</style>
