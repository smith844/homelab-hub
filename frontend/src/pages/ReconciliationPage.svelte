<script>
  import { onMount } from 'svelte';
  import { del, get, post } from '../lib/api.js';
  import { adminHeaders, getAdminToken, setAdminToken } from '../lib/admin.js';
  import { addToast } from '../lib/stores.js';
  import { FILTERS, changedFieldCount, filterContainers, summarizeReport } from '../lib/reconciliationView.js';

  let hosts = [], host = '', report = null, raw = '', snapshot = null;
  let loading = false, error = '', preview = null, bulkPreview = null, selected = {}, dirty = false;
  let filter = 'all', query = '', busyWrites = false;
  let exclusionName = '', exclusionReason = '';
  let savedToken = getAdminToken(), token = savedToken;
  let tokenSaved = false;
  const value = v => v === null || v === undefined || v === '' ? '(not recorded)' : String(v);
  const labels = {matched: 'Matched', older_observation: 'Older than recorded observation', missing_inventory: 'Missing from inventory', duplicate: 'Potential duplicate', confirmed_absent: 'Absent in this snapshot', excluded: 'Excluded from warnings', unknown: 'Unknown', unmatched: 'Unmatched', unverified: 'Unverified'};

  $: summary = summarizeReport(report);
  $: visibleContainers = filterContainers(report?.containers || [], filter, query);
  $: exclusions = report?.exclusions || [];
  $: bulkEligible = Boolean(report && report.scan?.status === 'success' && report.scan?.fresh
    && report.scan?.authoritative && summary.matched > 0);
  $: changeCount = changedFieldCount(bulkPreview?.plan);

  onMount(async () => {
    try {
      const result = await get('/reconciliation'); hosts = result.hosts;
      if (hosts.length) { host = hosts[0].key; await compare(); }
    } catch (e) { error = e.message; }
  });
  async function compare() {
    if (!host) return;
    loading = true; error = ''; preview = null; bulkPreview = null;
    try { report = await post('/reconciliation/compare', {host_key: host, snapshot}); }
    catch (e) { error = e.message; report = null; }
    finally { loading = false; }
  }
  async function changeHost() {
    snapshot = null; raw = ''; selected = {}; dirty = false;
    filter = 'all'; query = ''; exclusionName = ''; exclusionReason = '';
    await compare();
  }
  async function readFile(event) {
    preview = null; bulkPreview = null; dirty = true;
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { error = 'Snapshot exceeds 5 MB'; return; }
    raw = await file.text(); await loadSnapshot();
  }
  async function loadSnapshot() {
    preview = null; bulkPreview = null;
    try { snapshot = raw.trim() ? JSON.parse(raw) : null; }
    catch { error = 'Invalid JSON. Check the exported snapshot file.'; snapshot = null; report = null; return; }
    dirty = false; await compare();
  }
  async function review(row, kind) {
    error = ''; preview = null; bulkPreview = null; loading = true;
    try {
      preview = await post('/reconciliation/preview', {host_key: host, snapshot,
        action: {kind, container_key: row.container_key, app_id: kind === 'match' ? Number(selected[row.container_key]) : row.app_id}});
    } catch (e) { error = e.message; }
    finally { loading = false; }
  }
  async function apply() {
    if (!preview || !confirm('Apply this reviewed inventory change? No inventory records will be deleted.')) return;
    loading = true; error = '';
    try {
      await post('/reconciliation/apply', {token: preview.token}, {headers: adminHeaders()});
      addToast('Reviewed change applied', 'success'); await compare();
    } catch (e) { error = e.message; preview = null; }
    finally { loading = false; }
  }
  async function reviewBulk() {
    error = ''; preview = null; bulkPreview = null; loading = true;
    try {
      bulkPreview = await post('/reconciliation/preview-bulk', {host_key: host, snapshot});
      filter = 'matched';
    } catch (e) { error = e.message; }
    finally { loading = false; }
  }
  async function applyBulk() {
    if (!bulkPreview || !confirm(`Apply metadata updates to ${bulkPreview.plan.app_count} applications? Names, notes, parents and grouping will not change.`)) return;
    loading = true; error = '';
    try {
      const result = await post('/reconciliation/apply-bulk', {token: bulkPreview.token}, {headers: adminHeaders()});
      addToast(`Metadata updated for ${result.updated} applications`, 'success');
      bulkPreview = null; await compare();
    } catch (e) { error = e.message; bulkPreview = null; }
    finally { loading = false; }
  }
  async function saveExclusion(name, reason) {
    const containerName = String(name || '').trim();
    if (!containerName) { error = 'Enter a Docker container name to exclude.'; return; }
    busyWrites = true; error = '';
    try {
      await post('/reconciliation/exclusions', {host_key: host, container_name: containerName, reason},
        {headers: adminHeaders()});
      addToast(`Excluded ${containerName} from missing-inventory warnings`, 'success');
      exclusionName = ''; exclusionReason = ''; await compare();
    } catch (e) { error = e.message; }
    finally { busyWrites = false; }
  }
  async function submitExclusion() { await saveExclusion(exclusionName, exclusionReason); }
  async function addExclusionFor(name) {
    await saveExclusion(name, 'Operator exclusion from the discovered container list');
  }
  async function removeExclusion(item) {
    if (!confirm(`Remove the exclusion for ${item.container_name}? This only restores missing-inventory warnings.`)) return;
    busyWrites = true; error = '';
    try {
      await del(`/reconciliation/exclusions/${item.id}`, undefined, {headers: adminHeaders()});
      addToast('Exclusion removed', 'success'); await compare();
    } catch (e) { error = e.message; }
    finally { busyWrites = false; }
  }
  function saveToken() {
    setAdminToken(token.trim()); savedToken = token.trim(); tokenSaved = Boolean(savedToken);
    if (savedToken) addToast('Admin token saved for this browser session', 'success');
  }
</script>

<section class="reconciliation">
  <h1>Infrastructure reconciliation</h1>
  <p>Compare observations with inventory. Nothing changes until you preview and apply a specific action. Inventory records are never automatically deleted.</p>
  <div class="controls">
    <label>Root host<select bind:value={host} on:change={changeHost} disabled={loading}>
      <option value="" disabled>Select a host</option>
      {#each hosts as item}<option value={item.key}>{item.name}</option>{/each}
    </select></label>
    <a href="#/groups">Manage container groups and overrides</a>
  </div>
  {#if !hosts.length}<p>Add a hardware host to inventory before comparing resources.</p>{/if}
  <article>
    <h2>Discovery input</h2>
    <p>Upload a saved network scanner status response, or a separately collected Docker snapshot. Network hosts and ports do not establish Docker identities. Snapshots stay in this page only; there is no scan history or live scanner connection.</p>
    <label>JSON snapshot file<input type="file" accept=".json,application/json" on:change={readFile} disabled={loading || !host} /></label>
    <details><summary>Paste snapshot JSON</summary>
      <textarea aria-label="Snapshot JSON" bind:value={raw} rows="7" on:input={() => {preview = null; bulkPreview = null; dirty = true;}}></textarea>
      <button on:click={loadSnapshot} disabled={loading || !host}>Compare snapshot</button>
    </details>
    <button class="secondary outline" on:click={async () => {snapshot = null; raw = ''; dirty = false; await compare();}} disabled={loading || !host}>Clear snapshot</button>
    <details><summary>Container snapshot contract</summary>
      <p>This is HomeLab-Hub's input contract for a separate container collector, not an API supplied by the network scanner. A complete scan must include stopped containers. Do not mark partial/running-only output complete.</p>
      <pre>{JSON.stringify({schema_version: 1, host_key: 'host-name', source: 'your container collector', status: 'success', complete: true, coverage: 'all_containers', completed_at: 'ISO-8601 UTC scan completion time', containers: [{container_name: 'docker-name', container_id: 'optional observed ID', image_id: 'optional observed image ID', image: 'optional image reference'}]}, null, 2)}</pre>
    </details>
  </article>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if loading}<p aria-busy="true">Comparing inventory…</p>{/if}
  {#if report}
    <div class="summary" role="region" aria-label="Reconciliation summary">
      <button type="button" class="summary-item" class:active={filter === 'matched'} on:click={() => filter = 'matched'}><strong>{summary.matched}</strong> Matched</button>
      <button type="button" class="summary-item" class:active={filter === 'unmatched'} on:click={() => filter = 'unmatched'}><strong>{summary.unmatched}</strong> Unmatched</button>
      <button type="button" class="summary-item" class:active={filter === 'excluded'} on:click={() => filter = 'excluded'}><strong>{summary.excluded}</strong> Excluded</button>
      <button type="button" class="summary-item" class:active={filter === 'uncertain'} on:click={() => filter = 'uncertain'}><strong>{summary.uncertain}</strong> Uncertain</button>
      <span class="summary-item muted"><strong>{summary.not_seen}</strong> Inventory not seen</span>
    </div>
    <article class="scan-status">
      <h2>Evidence and coverage</h2>
      <p><strong>{report.scan.source}</strong> · {report.scan.status} · {report.scan.coverage}</p>
      <p>{report.scan.reason}</p>
      <p>Completion: {value(report.scan.completed_at)}. Freshness limit: 24 hours. Coverage and success are declarations in the uploaded snapshot, not an independent live probe.</p>
    </article>
    <article class="bulk-update">
      <h2>Bulk metadata update</h2>
      <p>Preview one reviewed update for confidently matched containers. Only container ID, image ID, image reference and observation time change. Application IDs, names, descriptions, user notes, parents, grouping overrides and map customisations are preserved. No applications are created or deleted.</p>
      <button on:click={reviewBulk} disabled={loading || dirty || !bulkEligible}>Preview bulk metadata update for {summary.matched} matched container{summary.matched === 1 ? '' : 's'}</button>
      {#if !bulkEligible}<small>Bulk updates require a fresh, complete, successful all-container snapshot and at least one confidently matched container.</small>{/if}
      {#if bulkPreview}
        <div class="preview bulk-preview" role="region" aria-label="Bulk reconciliation preview">
          <h3>Bulk preview for {bulkPreview.plan.app_count} applications</h3>
          <p>{changeCount} field value{changeCount === 1 ? '' : 's'} will change. The whole reviewed update is applied in one database transaction.</p>
          {#if bulkPreview.plan.skipped?.length}
            <details><summary>{bulkPreview.plan.skipped.length} observation{bulkPreview.plan.skipped.length === 1 ? '' : 's'} not eligible</summary>
              <ul>{#each bulkPreview.plan.skipped as item}<li><strong>{item.container_name}</strong> — {labels[item.classification] || item.classification}: {item.reason}</li>{/each}</ul>
            </details>
          {/if}
          <details><summary>Review per-application changes</summary>
            <div class="table-scroll"><table><thead><tr><th>Application</th><th>Metadata changes</th></tr></thead><tbody>
              {#each bulkPreview.plan.applications as item}<tr><td>{item.name}<small>{item.container_name}</small></td>
                <td>{#each item.fields as field}<div>{field.field}: {value(field.before)} → {value(field.after)}</div>{/each}</td></tr>{/each}
            </tbody></table></div>
          </details>
          <button on:click={applyBulk} disabled={loading || !savedToken}>Apply bulk update</button>
          <button class="secondary outline" on:click={() => bulkPreview = null}>Cancel bulk preview</button>
        </div>
      {/if}
    </article>
    {#if report.network}
      <h2>Network observations — {report.network.type} ({report.network.status})</h2>
      <p>{report.network.reason} No network observation is converted into a Docker container or applied automatically.</p>
      <div class="table-scroll"><table><thead><tr><th>Endpoint</th><th>Observation</th><th>Comparison</th><th>Inventory candidates</th></tr></thead><tbody>
        {#each report.network.rows as row}<tr><td>{row.ip || 'Unknown IP'}{row.port ? ':' + row.port : ''}</td><td>{row.name}</td><td>{labels[row.classification]}<small>{row.reason}</small></td><td>{row.matches.map(m => m.name).join(', ') || 'None in selected host scope'}</td></tr>{/each}
        {#if !report.network.rows.length}<tr><td colspan="4">No network results supplied. This is not proof of resource absence.</td></tr>{/if}
      </tbody></table></div>
    {/if}
    <h2>Discovered containers ({report.containers.length})</h2>
    <div class="controls filters">
      <label>Show<select bind:value={filter} aria-label="Container filter" disabled={loading}>
        {#each FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
      </select></label>
      <label>Search<input bind:value={query} aria-label="Container search" placeholder="Container or application name" /></label>
      <span>{visibleContainers.length} shown</span>
    </div>
    <div class="table-scroll"><table><thead><tr><th>Container</th><th>Comparison</th><th>Recorded changes</th><th>Review action</th></tr></thead><tbody>
      {#each visibleContainers as row}
        <tr><td><strong>{row.container_name}</strong><small>{row.app_name || 'No inventory match'}</small></td>
          <td>{labels[row.classification]}<small>{row.reason}</small></td>
          <td>{#each row.changes as field}<div>{field.field}: {value(field.before)} → {value(field.after)}</div>{/each}{#if !row.changes.length}No changed IDs/image metadata recorded.{/if}</td>
          <td>{#if !dirty && ['matched', 'missing_inventory'].includes(row.classification) && report.scan.status === 'success' && report.scan.fresh}
            {#if row.app_id}<button class="secondary outline" on:click={() => review(row, 'update')} disabled={loading}>Preview metadata update</button>
            {:else}<button class="secondary outline" on:click={() => review(row, 'add')} disabled={loading}>Preview addition</button>
              <select aria-label={`Match ${row.container_name} to inventory`} bind:value={selected[row.container_key]} on:change={() => preview = null}>
                <option value={undefined}>Select existing application</option>
                {#each report.applications as app}<option value={String(app.id)}>{app.name} ({app.container_key})</option>{/each}
              </select>
              <button class="secondary outline" on:click={() => review(row, 'match')} disabled={loading || !selected[row.container_key]}>Preview manual match</button>
            {/if}
          {:else if row.classification === 'excluded'}<span>Excluded from warnings. Remove it in the Excluded containers section.</span>
          {:else}<span>Read-only; resolve coverage or duplicate identities first.</span>{/if}
          {#if row.classification === 'missing_inventory' && report.scan.status === 'success' && report.scan.fresh}
            <button class="secondary outline" on:click={() => addExclusionFor(row.container_name)} disabled={loading || busyWrites || !savedToken}>Exclude from warnings</button>
          {/if}</td>
        </tr>
      {/each}
      {#if !report.containers.length}<tr><td colspan="4">No container observations. Upload a Docker snapshot to compare container identities.</td></tr>
      {:else if !visibleContainers.length}<tr><td colspan="4">No containers match this filter or search.</td></tr>{/if}
    </tbody></table></div>
    {#if preview}
      <article class="preview" aria-label="Reconciliation preview">
        <h2>Preview {preview.plan.kind}: {preview.plan.name}</h2>
        <p>Existing names, parents, icons, addresses and user notes remain intact. Only a generated discovery metadata block is added/updated. Additions attach to the selected root host.</p>
        <table><thead><tr><th>Field</th><th>Before</th><th>After</th></tr></thead><tbody>
          {#each preview.plan.fields as field}<tr><td>{field.field}</td><td>{value(field.before)}</td><td>{value(field.after)}</td></tr>{/each}
        </tbody></table>
        <p>{preview.plan.group_override}</p><p>Preview expires in 10 minutes or after inventory/grouping changes. Server restart also invalidates it.</p>
        <button on:click={apply} disabled={loading || !savedToken}>Apply reviewed change</button>
        <button class="secondary outline" on:click={() => preview = null}>Cancel preview</button>
      </article>
    {/if}
    <h2>Inventory without a discovered container match ({report.inventory.length})</h2>
    <div class="table-scroll"><table><thead><tr><th>Application</th><th>Identity</th><th>Evidence</th></tr></thead><tbody>
      {#each report.inventory as row}<tr><td><a href={`#/inventory/apps/${row.app_id}`}>{row.name}</a></td><td>{row.container_key}</td><td>{labels[row.classification]}<small>{row.reason}</small></td></tr>{/each}
      {#if !report.inventory.length}<tr><td colspan="3">No unmatched inventory applications in this host scope.</td></tr>{/if}
    </tbody></table></div>
    <h2>Potential duplicate identities ({report.duplicates.length})</h2>
    {#each report.duplicates as item}<p>{item.container_key}: inventory IDs {item.inventory_ids.join(', ') || 'none'}, discovered rows {item.discovered_count}. Review records in inventory; no automatic merge.</p>{:else}<p>No duplicate identities in this comparison.</p>{/each}
    <article class="exclusions">
      <h2>Excluded containers ({exclusions.length})</h2>
      <p>Exclusions are host-scoped, keyed by stable Docker container name, and only suppress ordinary missing-inventory warnings. They are shown here rather than discarded, never delete Docker or inventory records, and never change grouping.</p>
      <form class="controls" on:submit|preventDefault={submitExclusion}>
        <input aria-label="Exclusion container name" bind:value={exclusionName} placeholder="Docker container name" />
        <input aria-label="Exclusion reason" bind:value={exclusionReason} placeholder="Reason (optional)" />
        <button type="submit" disabled={busyWrites || !savedToken}>Add exclusion</button>
      </form>
      {#if !savedToken}<small>Adding or removing exclusions requires the admin token.</small>{/if}
      {#if exclusions.length}
        <div class="table-scroll"><table><thead><tr><th>Container</th><th>Reason</th><th>Snapshot</th><th>Action</th></tr></thead><tbody>
          {#each exclusions as item}<tr><td><strong>{item.container_name}</strong><small>{item.container_key}</small></td>
            <td>{item.reason || 'No reason recorded.'}</td>
            <td>{item.observed ? 'Observed in this snapshot' : 'Not observed'}</td>
            <td><button class="secondary outline" on:click={() => removeExclusion(item)} disabled={busyWrites || !savedToken}>Remove exclusion</button></td></tr>{/each}
        </tbody></table></div>
      {:else}<p>No exclusions for this host.</p>{/if}
    </article>
    <div class="investigations">
      <article><h2>FolderView without inventory ({report.folderview_unmatched.length})</h2>
        <p>Investigation targets, not necessarily errors. No inventory is created from FolderView alone.</p>
        {#each report.folderview_unmatched as item}<p><strong>{item.container_key}</strong> · {item.group_name}{item.group_active ? '' : ' (archived)'}<small>{item.reason}</small></p>{/each}
      </article>
      <article><h2>Ungrouped applications ({report.ungrouped.length})</h2>
        <p>These may be intentional. Review assignments in Container groups.</p>
        {#each report.ungrouped as item}<p><a href={`#/inventory/apps/${item.app_id}`}>{item.name}</a><small>{item.reason}</small></p>{/each}
      </article>
    </div>
  {/if}
  <article><h2>Administrative access</h2>
    <p>Comparison and previews are read-only. Applying bulk updates or changing exclusions requires the configured server admin token. It is stored only in this browser session.</p>
    <div class="controls"><input type="password" aria-label="Reconciliation admin token" bind:value={token} placeholder="Admin token" /><button class="secondary outline" on:click={saveToken}>Save session token</button></div>
    {#if tokenSaved}<small>Token saved for this browser session.</small>{/if}
  </article>
</section>
<style>
  .reconciliation { max-width: 1280px; }
  h1 { margin-bottom: .5rem; }
  h2 { font-size: 1.1rem; }
  h3 { font-size: 1rem; }
  p { font-size: .85rem; }
  small { display: block; color: var(--pico-muted-color); margin-top: .3rem; }
  article { border: 1px solid var(--pico-muted-border-color); box-shadow: none; }
  .controls { display: flex; align-items: center; flex-wrap: wrap; gap: .8rem; }
  .controls input { max-width: 24rem; }
  .controls button { width: auto; }
  .controls label { min-width: 14rem; }
  .filters { margin-bottom: .8rem; }
  .filters label { min-width: 11rem; }
  .filters span { font-size: .8rem; color: var(--pico-muted-color); }
  .summary { display: flex; align-items: stretch; flex-wrap: wrap; gap: .5rem; margin: .8rem 0 1rem; }
  .summary-item { display: inline-flex; flex-direction: row; align-items: baseline; justify-content: flex-start; gap: .3rem; width: auto; margin: 0; padding: .45rem .8rem; font-size: .8rem; border: 1px solid var(--hlh-control-border); background: transparent; color: var(--hlh-control-fg); box-shadow: none; }
  .summary-item strong { display: inline; font-size: 1.05rem; }
  .summary-item.active { border-color: var(--pico-primary); background: var(--hlh-control-active-bg); color: var(--hlh-control-active-fg); }
  .summary-item.muted { padding: .45rem .8rem; color: var(--pico-muted-color); }
  .bulk-update h2 { margin-top: 0; }
  .bulk-preview { margin-top: 1rem; padding: 1rem; border: 1px solid var(--pico-primary); }
  .bulk-preview td:last-child { min-width: 0; }
  .bulk-preview table { min-width: 0; }
  .bulk-preview table { width: 100%; }
  .bulk-preview button { width: auto; margin: .25rem .5rem .25rem 0; }
  .table-scroll { overflow-x: auto; margin-bottom: 1.4rem; }
  table { font-size: .8rem; min-width: 650px; }
  td { vertical-align: top; overflow-wrap: anywhere; }
  td button, td select { font-size: .75rem; margin: 0 0 .5rem; }
  td:last-child { min-width: 220px; }
  pre { padding: .7rem; white-space: pre-wrap; font-size: .75rem; }
  .investigations { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1rem; }
  .exclusions form { margin-bottom: .8rem; }
  .preview { border-color: var(--pico-primary); }
  .preview td { white-space: pre-wrap; }
  [role="alert"] { border-left: 3px solid var(--pico-primary); padding: .7rem; }
  @media (max-width: 760px) {
    .bulk-preview { padding: .7rem; }
    .bulk-preview table, .bulk-preview thead, .bulk-preview tbody, .bulk-preview tr,
    .bulk-preview td, .bulk-preview th { display: block; }
    .bulk-preview thead { display: none; }
    .bulk-preview tr { border-bottom: 1px solid var(--pico-muted-border-color); padding: .4rem 0; }
    .bulk-preview td, .bulk-preview th { padding: .15rem 0; }
  }
</style>
