<script>
  import { renderDocumentMarkdown } from '../../lib/documentMarkdown.js';
  export let content = '';
</script>

<div class="document-body">{@html renderDocumentMarkdown(content)}</div>

<style>
  .document-body { line-height: 1.7; overflow-wrap: anywhere; color: var(--pico-color); }
  .document-body :global(h1) { font-size: 1.9rem; }
  .document-body :global(h2) { font-size: 1.4rem; }
  .document-body :global(h3) { font-size: 1.15rem; }
  .document-body :global(h1), .document-body :global(h2), .document-body :global(h3), .document-body :global(h4) { margin: 1.6em 0 .6em; line-height: 1.3; }
  .document-body :global(> :first-child) { margin-top: 0; }
  .document-body :global(p), .document-body :global(ul), .document-body :global(ol) { margin: 0 0 1em; }
  .document-body :global(li) { margin-bottom: .3em; }
  .document-body :global(li > p) { margin-bottom: .3em; }
  .document-body :global(pre) { padding: 1rem; background: var(--pico-background-color); border: 1px solid var(--pico-muted-border-color); border-radius: 8px; overflow: auto; white-space: pre; }
  .document-body :global(code) { font-size: .85em; }
  .document-body :global(pre code) { padding: 0; background: transparent; color: inherit; }
  .document-body :global(table) { display: block; max-width: 100%; overflow-x: auto; font-size: .9em; }
  .document-body :global(th), .document-body :global(td) { padding: .6rem .8rem; }
  .document-body :global(img) { max-width: 100%; height: auto; }
  .document-body :global(blockquote) { margin: 1rem 0; padding: .5rem 1rem; border-left: 3px solid var(--pico-primary); }
</style>
