<script>
  import { params } from 'svelte-spa-router';
  import { onMount, onDestroy } from 'svelte';
  import { get, post, del } from '../lib/api.js';
  import { addToast } from '../lib/stores.js';
  import { readPreference, savePreference } from '../lib/preferences.js';
  import { documentSaves as saves, subscribeDocumentSaves } from '../lib/documentSession.js';
  import DocEditor from '../components/docs/DocEditor.svelte';
  import DocumentBody from '../components/docs/DocumentBody.svelte';

  let docs = [], activeDoc = null, loading = true, loadingDoc = false;
  let search = '', editing = false, actionsOpen = false, loadError = '';
  let revision = 0, requestId = 0, destroyed = false, listEl, newDocumentId = null;
  const storedWidth = readPreference('hlh.docsListWidth', 340);
  let listWidth = typeof storedWidth === 'number' && Number.isFinite(storedWidth) ? Math.max(260, Math.min(560, storedWidth)) : 340;
  const unsubscribeSaves = subscribeDocumentSaves(() => revision++);
  $: docId = $params?.id ? parseInt($params.id, 10) : null;
  $: loadDoc(docId);
  $: filteredDocs = docs.filter(d => d.title.toLowerCase().includes(search.trim().toLowerCase()));
  $: saveState = (revision, activeDoc ? saves.state(activeDoc.id) : 'saved');
  $: unsavedIds = (revision, saves.unsaved());

  async function loadDocs() {
    try { docs = (await get('/docs')).data.map(doc => ({ ...doc, ...saves.draft(doc.id) })); }
    catch (e) { addToast(e.message, 'error'); }
    loading = false;
  }
  async function loadDoc(id) {
    const currentRequest = ++requestId;
    if (activeDoc) saves.flush(activeDoc.id);
    activeDoc = null; editing = false; actionsOpen = false; loadError = '';
    loadingDoc = Boolean(id);
    if (!id) return;
    try {
      const doc = (await get(`/docs/${id}`)).data;
      if (currentRequest !== requestId || destroyed) return;
      activeDoc = { ...doc, ...saves.draft(id) };
      if (newDocumentId === id) { editing = true; newDocumentId = null; }
    } catch (e) { if (currentRequest === requestId && !destroyed) loadError = e.message; }
    finally { if (currentRequest === requestId && !destroyed) loadingDoc = false; }
  }
  onMount(loadDocs);
  onDestroy(() => { destroyed = true; requestId++; saves.flushAll(); unsubscribeSaves(); stopResize(); });

  async function createDoc() {
    try {
      const doc = (await post('/docs', { title: 'Untitled' })).data;
      docs = [...docs, doc];
      search = '';
      newDocumentId = doc.id;
      window.location.hash = `/docs/${doc.id}`;
    } catch (e) { addToast(e.message, 'error'); }
  }
  async function deleteDoc() {
    const id = activeDoc?.id;
    if (!id || !confirm(`Delete “${activeDoc.title}”? This cannot be undone.`)) return;
    if (!(await saves.flush(id))) { addToast('Save failed. Retry before deleting this document.', 'error'); return; }
    try {
      await del(`/docs/${id}`);
      saves.forget(id); docs = docs.filter(d => d.id !== id); revision++;
      if (activeDoc?.id === id) window.location.hash = '/docs';
      addToast('Document deleted', 'success');
    } catch (e) { addToast(e.message, 'error'); }
  }
  function changed(content) {
    if (!activeDoc) return;
    activeDoc = { ...activeDoc, content };
    queueSave();
  }
  function queueSave() {
    if (!activeDoc) return;
    docs = docs.map(d => d.id === activeDoc.id ? { ...d, title: activeDoc.title } : d);
    saves.update(activeDoc.id, activeDoc);
  }
  async function finishEditing() {
    const id = activeDoc.id;
    if (await saves.flush(id)) { if (activeDoc?.id === id) editing = false; }
  }
  function resizeTo(width) {
    listWidth = Math.max(260, Math.min(560, width));
    savePreference('hlh.docsListWidth', listWidth);
  }
  let resizeStartX = 0, resizeStartWidth = 0;
  function moveResize(event) { resizeTo(resizeStartWidth + event.clientX - resizeStartX); }
  function stopResize() { window.removeEventListener('pointermove', moveResize); window.removeEventListener('pointerup', stopResize); window.removeEventListener('pointercancel', stopResize); }
  function startResize(event) {
    if (event.button !== 0) return;
    event.preventDefault(); resizeStartX = event.clientX; resizeStartWidth = listEl.getBoundingClientRect().width;
    window.addEventListener('pointermove', moveResize); window.addEventListener('pointerup', stopResize); window.addEventListener('pointercancel', stopResize);
  }
  function resizeKey(event) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    resizeTo(event.key === 'Home' ? 260 : event.key === 'End' ? 560 : listWidth + (event.key === 'ArrowRight' ? 20 : -20));
  }
</script>

<div class="docs-page" style="--document-list-width: {listWidth}px">
  <aside class="doc-list" bind:this={listEl} aria-label="Documents">
    <div class="doc-list-header"><div><h1>Documents</h1><small>Your homelab reference notes</small></div><button class="outline small" on:click={createDoc}>+ New</button></div>
    <label class="search-label">Find a document<input type="search" bind:value={search} placeholder="Search titles…" /></label>
    {#if loading}<p aria-busy="true">Loading documents…</p>{:else}
      <small class="document-count">{filteredDocs.length} of {docs.length} documents</small>
      <nav class="document-links" aria-label="Document list"><ul>
        {#each filteredDocs as doc (doc.id)}<li><a class:active={docId === doc.id} aria-current={docId === doc.id ? 'page' : undefined} href={'#/docs/' + doc.id}><span class="doc-symbol" aria-hidden="true">▤</span><span>{doc.title || 'Untitled'}</span></a></li>{/each}
      </ul></nav>
      {#if !filteredDocs.length}<p class="list-empty">{search ? 'No matching titles. Try another search.' : 'Create your first reference note.'}</p>{/if}
    {/if}
  </aside>
  <!-- Focusable separator follows the WAI-ARIA window splitter pattern. -->
  <!-- svelte-ignore a11y-no-noninteractive-tabindex a11y-no-noninteractive-element-interactions -->
  <div class="list-divider" role="separator" aria-label="Resize document list" aria-orientation="vertical" aria-valuemin="260" aria-valuemax="560" aria-valuenow={listWidth} tabindex="0" on:pointerdown={startResize} on:keydown={resizeKey}></div>
  <section class="doc-content" aria-label="Document workspace">
    {#if unsavedIds.some(id => id !== activeDoc?.id && saves.state(id) === 'error')}
      <div class="save-alert" role="alert">A previous document could not be saved. Your edits are retained in this tab. <button class="outline small" on:click={() => saves.flushAll()}>Retry saves</button></div>
    {/if}
    {#if loadingDoc}<p class="placeholder" aria-busy="true">Loading document…</p>
    {:else if loadError}<div class="placeholder" role="alert">Could not load this document: {loadError} <button on:click={() => loadDoc(docId)}>Retry</button></div>
    {:else if activeDoc}
      <header class="document-header">
        <div class="document-heading"><small>{editing ? 'EDITING DOCUMENT' : 'REFERENCE NOTE'}</small>
          {#if editing}<label class="title-label">Document title<input class="doc-title" bind:value={activeDoc.title} on:input={queueSave} /></label>{:else}<h2>{activeDoc.title || 'Untitled'}</h2>{/if}
        </div>
        <div class="document-actions">
          <span class:error={saveState === 'error'} class="save-status" role="status">{saveState === 'saving' ? 'Saving…' : saveState === 'pending' ? 'Unsaved changes' : saveState === 'error' ? 'Save failed' : 'Saved'}</span>
          {#if saveState === 'error'}<button class="outline small" on:click={() => saves.flush(activeDoc.id)}>Retry save</button>{/if}
          {#if editing}<button class="small" on:click={finishEditing}>Done editing</button>{:else}<button class="small" on:click={() => editing = true}>Edit document</button>{/if}
          <div class="actions-menu"><button class="outline secondary small" aria-label="Document actions" aria-expanded={actionsOpen} on:click={() => actionsOpen = !actionsOpen}>•••</button>{#if actionsOpen}<div class="actions-popover"><button class="outline small" on:click={deleteDoc}>Delete document…</button></div>{/if}</div>
        </div>
      </header>
      {#key activeDoc.id}
        {#if editing}<DocEditor content={activeDoc.content} onChange={changed}/>
        {:else}<div class="document-reader"><article class="reading-page">{#if activeDoc.content}<DocumentBody content={activeDoc.content}/>{:else}<p class="placeholder">This note is empty. Select Edit document to start writing.</p>{/if}</article></div>{/if}
      {/key}
    {:else}<div class="welcome"><span class="welcome-symbol" aria-hidden="true">▤</span><h2>Your homelab knowledge, in one place</h2><p>Select a document to read your notes, configuration details and useful commands.</p><button on:click={createDoc}>Create a document</button></div>{/if}
  </section>
</div>

<style>
  .docs-page { display:flex; min-height:560px; height:calc(100dvh - 140px); border:1px solid var(--pico-muted-border-color); border-radius:12px; overflow:hidden; background:var(--pico-card-background-color); }
  .doc-list { width:var(--document-list-width); max-width:45%; flex-shrink:0; padding:1.15rem; overflow:auto; background:var(--pico-background-color); }
  .doc-list-header { display:flex; justify-content:space-between; align-items:center; gap:.5rem; margin-bottom:1.3rem; }
  .doc-list-header h1 { font-size:1.15rem; margin:0 0 .2rem; }
  .doc-list-header small { font-size:.7rem; color:var(--pico-muted-color); }
  .small { padding:.45rem .65rem; margin:0; font-size:.75rem; white-space:nowrap; }
  .search-label { font-size:.75rem; }
  .search-label input { font-size:.8rem; height:2.5rem; margin:.4rem 0 .6rem; }
  .document-count { display:block; font-size:.7rem; color:var(--pico-muted-color); margin-bottom:.65rem; }
  .document-links { display:block; }
  .document-links ul { display:block; list-style:none; padding:0; margin:0; }
  .document-links li { display:block; padding:0; margin:.2rem 0; }
  .document-links a { display:flex; gap:.6rem; padding:.7rem; margin:0; border:1px solid transparent; border-radius:7px; text-decoration:none; color:var(--pico-color); font-size:.82rem; line-height:1.45; white-space:normal; overflow-wrap:anywhere; }
  .document-links a:hover { background:var(--hlh-tint); }
  .document-links a.active { background:var(--hlh-tint); border-color:var(--pico-primary); font-weight:600; }
  .doc-symbol { color:var(--pico-muted-color); flex-shrink:0; }
  .list-divider { width:7px; flex-shrink:0; cursor:col-resize; background:var(--pico-muted-border-color); touch-action:none; }
  .list-divider:hover,.list-divider:focus-visible { background:var(--pico-primary); }
  .doc-content { flex:1; min-width:0; display:flex; flex-direction:column; overflow:hidden; }
  .document-header { display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap; padding:1rem 1.4rem; border-bottom:1px solid var(--pico-muted-border-color); }
  .document-heading { flex:1; min-width:180px; }
  .document-heading>small { font-size:.6rem; letter-spacing:.1em; color:var(--pico-muted-color); }
  .document-heading h2 { font-size:1.25rem; line-height:1.4; overflow-wrap:anywhere; margin:.3rem 0 0; }
  .title-label { font-size:.7rem; margin:0; }
  .doc-title { font-size:1.1rem; font-weight:600; margin:.3rem 0 0; padding:.5rem; height:auto; }
  .document-actions { display:flex; flex-wrap:wrap; align-items:center; gap:.6rem; }
  .save-status { color:var(--pico-muted-color); font-size:.7rem; }
  .save-status.error { color:var(--pico-del-color); }
  .actions-menu { position:relative; }
  .actions-popover { position:absolute; top:calc(100% + .5rem); right:0; z-index:5; padding:.5rem; background:var(--pico-card-background-color); border:1px solid var(--pico-muted-border-color); border-radius:8px; box-shadow:0 4px 14px #0003; }
  .document-reader { flex:1; min-height:0; overflow:auto; }
  .reading-page { max-width:960px; margin:0 auto; padding:2rem 2.5rem 4rem; background:transparent; border:0; border-radius:0; box-shadow:none; }
  .placeholder,.list-empty { padding:1rem; color:var(--pico-muted-color); font-size:.85rem; }
  .welcome { margin:auto; padding:2rem; max-width:620px; text-align:center; }
  .welcome h2 { font-size:1.5rem; }.welcome p { color:var(--pico-muted-color); font-size:.9rem; }.welcome-symbol { font-size:3rem; color:var(--pico-primary); }
  .save-alert { padding:.7rem; background:var(--hlh-tint); font-size:.8rem; }
  @media(max-width:1000px) { .reading-page { padding:1.5rem; } .document-header { padding:1rem; } }
  @media(max-width:760px) { .docs-page { flex-direction:column; height:auto; min-height:600px; } .doc-list { width:100%; max-width:none; max-height:300px; border-bottom:1px solid var(--pico-muted-border-color); } .list-divider { display:none; } .doc-content { min-height:500px; } .document-reader { overflow:visible; } }
</style>
