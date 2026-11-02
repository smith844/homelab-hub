<script>
  import { onDestroy, onMount } from 'svelte';
  import { get, post } from '../lib/api.js';
  import { adminHeaders, getAdminToken, setAdminToken } from '../lib/admin.js';
  import { addToast } from '../lib/stores.js';
  import {
    COMPARISON_FILTERS,
    discoveryCategories,
    filterComparisonRows,
    filterScanRows,
    scanIsTerminal,
    summarizeScan,
  } from '../lib/networkDiscovery.js';

  let config = null, hosts = [], host = '', loading = true, error = '';
  let approvedTarget = '', customTarget = '', scanType = 'discover', ports = '';
  let scan = null, scanning = false, pollTimer = null, pollCount = 0;
  let comparison = null, comparisonError = '';
  let filter = 'all', query = '', scanQuery = '';
  let tokenSaved = false;
  let savedToken = getAdminToken(), token = savedToken;
  const value = v => v === null || v === undefined || v === '' ? '(not recorded)' : String(v);
  const labels = {matched: 'Matched', unmatched: 'Unmatched', duplicate: 'Potential duplicate',
    unverified: 'Unverified / partial', unknown: 'Unknown'};

  $: activeTarget = customTarget.trim() || approvedTarget;
  $: summary = summarizeScan(scan);
  $: comparisonRows = comparison?.network?.rows || [];
  $: categories = discoveryCategories(comparisonRows);
  $: visibleComparison = filterComparisonRows(comparisonRows, filter, query);
  $: visibleHosts = filterScanRows(scan?.hosts || [], scanQuery);
  $: visibleServices = filterScanRows(scan?.results || [], scanQuery);
  $: canStart = Boolean(activeTarget && config?.configured && savedToken && !scanning);

  onMount(async () => {
    try {
      config = await get('/network-discovery/config');
      approvedTarget = config.approved_ranges?.[0] || '';
      ports = config.default_ports || '';
      const inventory = await get('/reconciliation');
      hosts = inventory.hosts || [];
      host = hosts[0]?.key || '';
    } catch (e) { error = e.message; }
    finally { loading = false; }
  });

  onDestroy(() => stopPolling());

  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  async function startScan() {
    if (!savedToken) { error = 'Save the admin token before starting a scan.'; return; }
    if (!activeTarget) { error = 'Choose or enter an approved target.'; return; }
    stopPolling(); error = ''; comparison = null; comparisonError = '';
    scanning = true; scan = null; pollCount = 0;
    try {
      const result = await post('/network-discovery/scan', {
        target: activeTarget,
        scan_type: scanType,
        ports: scanType === 'services' ? ports : null,
      }, { headers: adminHeaders() });
      scan = result.scan;
      if (scanIsTerminal(scan.status)) { await compare(); }
      else { pollTimer = setInterval(() => pollScan(scan.scan_id), 1500); }
    } catch (e) { error = e.message; }
    finally { scanning = false; }
  }

  async function pollScan(scanId) {
    pollCount += 1;
    if (pollCount > 240) {
      stopPolling(); error = 'Scan is taking too long to report; check the scanner service.';
      return;
    }
    try {
      const result = await get(`/network-discovery/scan/${scanId}`);
      scan = result.scan;
      if (scanIsTerminal(scan.status)) { stopPolling(); await compare(); }
    } catch (e) {
      stopPolling(); error = e.message;
    }
  }

  async function compare() {
    if (!scan || !host) return;
    comparisonError = '';
    try {
      comparison = await post('/reconciliation/compare', {
        host_key: host,
        snapshot: { data: scan },
      });
      filter = 'all'; query = '';
    } catch (e) {
      comparison = null; comparisonError = e.message;
    }
  }

  async function changeHost() {
    if (scanIsTerminal(scan?.status)) await compare();
  }

  function saveToken() {
    setAdminToken(token.trim()); savedToken = token.trim(); tokenSaved = Boolean(savedToken);
    if (savedToken) addToast('Admin token saved for this browser session', 'success');
  }

  function clearScan() {
    stopPolling(); scan = null; comparison = null; comparisonError = ''; error = '';
    filter = 'all'; query = ''; scanQuery = '';
  }
</script>

<section class="network-discovery">
  <h1>Network discovery</h1>
  <p>A separate, restricted Nmap scanner discovers reachable IPv4 devices and basic TCP services. HomeLab-Hub validates the target, proxies the request and compares observations read-only. Nothing is added to inventory or changed on a map automatically.</p>

  {#if error}<p role="alert">{error}</p>{/if}
  {#if loading}<p aria-busy="true">Loading discovery configuration…</p>{/if}
  {#if config?.error}<p role="alert">{config.error}</p>{/if}
  {#if config && !config.configured}
    <article class="notice">
      <h2>Scanner not configured</h2>
      <p>The web app needs <code>HLH_SCANNER_URL</code> and <code>HLH_SCANNER_TOKEN</code>. The scanner runs separately with its own token and approved ranges; no nmap or elevated networking is required in this web container.</p>
    </article>
  {/if}

  <article class="scan-request">
    <h2>Scan request</h2>
    <div class="controls">
      <label>Approved range<select bind:value={approvedTarget} aria-label="Approved target range" disabled={scanning || !config?.approved_ranges?.length}>
        {#if !config?.approved_ranges?.length}<option value="">No approved ranges configured</option>{/if}
        {#each config?.approved_ranges || [] as item}<option value={item}>{item}</option>{/each}
      </select></label>
      <label>Specific host or CIDR<input bind:value={customTarget} aria-label="Specific scan target" placeholder="Optional; must be inside an approved range" disabled={scanning} /></label>
      <label>Scan type<select bind:value={scanType} aria-label="Scan type" disabled={scanning}>
        {#each config?.scan_types || [] as item}<option value={item.value}>{item.label}</option>{/each}
      </select></label>
      {#if scanType === 'services'}
        <label>TCP ports<input bind:value={ports} aria-label="TCP ports" placeholder="22,80,443,8000-8100" disabled={scanning} /></label>
      {/if}
      <label>Compare with root host<select bind:value={host} on:change={changeHost} aria-label="Discovery comparison host" disabled={scanning}>
        {#if !hosts.length}<option value="">No root hosts in inventory</option>{/if}
        {#each hosts as item}<option value={item.key}>{item.name}</option>{/each}
      </select></label>
    </div>
    <p class="hint">Explicit targets only; ranges are configured by the operator. VLAN numbers are never converted into subnets. Port scanning is an unprivileged TCP connect scan; no OS detection or NSE scripts are used.</p>
    <div class="controls">
      <button on:click={startScan} disabled={!canStart}>Start {scanType === 'services' ? 'discovery + service' : 'host discovery'} scan</button>
      {#if scan}<button class="secondary outline" on:click={clearScan} disabled={scanning}>Clear results</button>{/if}
    </div>
    {#if !savedToken}<small>Save the admin token below before starting a scan.</small>{/if}
    {#if !config?.approved_ranges?.length}<small>No approved ranges are configured; scans are disabled.</small>{/if}
  </article>

  {#if scan}
    <article class="scan-status">
      <h2>Scan status: {scan.status}</h2>
      <p><strong>{scan.type === 'portscan' ? 'Hosts and TCP services' : 'Host discovery'}</strong> · target <code>{value(scan.target)}</code></p>
      <p>Started: {value(scan.started_at)} · Completed: {value(scan.completed_at)} · Progress: {value(scan.progress)}%</p>
      <p>{summary.hosts_up} hosts up · {summary.hosts} reported hosts · {summary.services} open services · {summary.hosts_down} hosts down</p>
      {#if scan.status === 'partial'}<p role="alert">Partial scan. Results are retained for review, but completion, coverage and device absence cannot be asserted.</p>{/if}
      {#if scan.status === 'failed'}<p role="alert">The scan failed. No device or service is confirmed absent.</p>{/if}
      {#if scan.error}<p role="alert">{scan.error}</p>{/if}
      {#if scan.warnings?.length}
        <details><summary>{scan.warnings.length} scan warning{scan.warnings.length === 1 ? '' : 's'}</summary>
          <ul>{#each scan.warnings as warning}<li>{warning}</li>{/each}</ul>
        </details>
      {/if}
    </article>

    <div class="controls filters">
      <label>Search discoveries<input bind:value={scanQuery} aria-label="Search discoveries" placeholder="IP, hostname, MAC, vendor, port or service" /></label>
      <span>{visibleHosts.length} of {scan.hosts?.length || 0} hosts · {visibleServices.length} of {scan.results?.length || 0} results shown</span>
    </div>

    <h2>Discovered hosts ({scan.hosts?.length || 0})</h2>
    <div class="table-scroll"><table><thead><tr><th>IP address</th><th>Hostname</th><th>MAC / vendor</th><th>OS / role hint</th><th>Open ports</th></tr></thead><tbody>
      {#each visibleHosts as row}<tr><td><code>{row.ip}</code></td><td>{value(row.hostname)}</td><td>{value(row.mac)}<small>{value(row.vendor)}</small></td><td>{value(row.os)}</td><td>{value(row.open_ports)}</td></tr>{/each}
      {#if !scan.hosts?.length}<tr><td colspan="5">No reachable hosts reported. A failed or partial scan never proves absence.</td></tr>
      {:else if !visibleHosts.length}<tr><td colspan="5">No hosts match this search.</td></tr>{/if}
    </tbody></table></div>

    {#if scan.type === 'portscan'}
      <h2>Discovered services ({scan.results?.length || 0})</h2>
      <div class="table-scroll"><table><thead><tr><th>Host</th><th>Port</th><th>Service</th><th>Version / banner</th><th>MAC / vendor</th></tr></thead><tbody>
        {#each visibleServices as row}<tr><td><code>{row.ip}</code><small>{value(row.hostname)}</small></td><td>{value(row.port)}/{value(row.protocol)}</td><td>{value(row.service_name)}<small>{value(row.state)}</small></td><td>{value(row.service_version)}</td><td>{value(row.mac)}<small>{value(row.vendor)}</small></td></tr>{/each}
        {#if !scan.results?.length}<tr><td colspan="5">No open TCP services reported for this scan.</td></tr>
        {:else if !visibleServices.length}<tr><td colspan="5">No services match this search.</td></tr>{/if}
      </tbody></table></div>
    {/if}

    <article class="comparison">
      <h2>Inventory comparison</h2>
      {#if comparisonError}<p role="alert">{comparisonError}</p>{/if}
      {#if comparison}
        <p>{comparison.network?.reason} No inventory records are created, overwritten or deleted here.</p>
        <div class="summary" role="region" aria-label="Network comparison summary">
          <button type="button" class="summary-item" class:active={filter === 'matched'} on:click={() => filter = 'matched'}><strong>{categories.matched}</strong> Matched</button>
          <button type="button" class="summary-item" class:active={filter === 'unmatched'} on:click={() => filter = 'unmatched'}><strong>{categories.unmatched}</strong> Unmatched</button>
          <button type="button" class="summary-item" class:active={filter === 'uncertain'} on:click={() => filter = 'uncertain'}><strong>{categories.uncertain}</strong> Uncertain</button>
          <button type="button" class="summary-item" class:active={filter === 'unknown'} on:click={() => filter = 'unknown'}><strong>{categories.other}</strong> Unknown</button>
        </div>
        <div class="controls filters">
          <label>Show<select bind:value={filter} aria-label="Network comparison filter">
            {#each COMPARISON_FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
          </select></label>
          <label>Search comparison<input bind:value={query} aria-label="Search network comparison" placeholder="IP, port, service or inventory name" /></label>
        </div>
        <div class="table-scroll"><table><thead><tr><th>Endpoint</th><th>Observation</th><th>Comparison</th><th>Inventory candidates</th></tr></thead><tbody>
          {#each visibleComparison as row}<tr><td><code>{value(row.ip)}{row.port ? ':' + row.port : ''}</code></td><td>{value(row.name)}</td><td>{labels[row.classification] || row.classification}<small>{row.reason}</small></td><td>{row.matches.map(match => match.name).join(', ') || 'None in selected host scope'}</td></tr>{/each}
          {#if !comparisonRows.length}<tr><td colspan="4">No network observations to compare.</td></tr>
          {:else if !visibleComparison.length}<tr><td colspan="4">No observations match this filter or search.</td></tr>{/if}
        </tbody></table></div>
        <p class="hint">Matched means an IP/MAC or IP+port candidate exists in inventory; it does not prove a Docker identity, availability or that the inventory record is current.</p>
      {:else if !comparisonError && scanIsTerminal(scan.status) && host}
        <p>Comparison will appear after the scan completes.</p>
      {/if}
    </article>
  {/if}

  <article>
    <h2>Administrative access</h2>
    <p>Starting a scan requires the configured server admin token. It is stored only in this browser session. Scanning and comparison remain separate from inventory edits and map changes.</p>
    <div class="controls">
      <input type="password" aria-label="Network discovery admin token" bind:value={token} placeholder="Admin token" />
      <button class="secondary outline" on:click={saveToken}>Save session token</button>
    </div>
    {#if tokenSaved}<small>Token saved for this browser session.</small>{/if}
  </article>
</section>
<style>
  .network-discovery { max-width: 1280px; }
  h1 { margin-bottom: .5rem; }
  h2 { font-size: 1.1rem; }
  p { font-size: .85rem; }
  small { display: block; color: var(--pico-muted-color); margin-top: .3rem; }
  article { border: 1px solid var(--pico-muted-border-color); box-shadow: none; }
  .controls { display: flex; align-items: center; flex-wrap: wrap; gap: .8rem; }
  .controls button { width: auto; }
  .controls input { max-width: 24rem; }
  .controls label { min-width: 13rem; }
  .hint { color: var(--pico-muted-color); }
  .notice { border-left: 3px solid var(--pico-primary); }
  .scan-status, .comparison { margin-top: 1rem; }
  .filters { margin: .8rem 0; }
  .filters label { min-width: 12rem; }
  .filters span { font-size: .8rem; color: var(--pico-muted-color); }
  .summary { display: flex; align-items: stretch; flex-wrap: wrap; gap: .5rem; margin: .8rem 0 1rem; }
  .summary-item { display: inline-flex; align-items: baseline; gap: .3rem; width: auto; margin: 0; padding: .45rem .8rem; font-size: .8rem; border: 1px solid var(--hlh-control-border); background: transparent; color: var(--hlh-control-fg); box-shadow: none; }
  .summary-item strong { display: inline; font-size: 1.05rem; }
  .summary-item.active { border-color: var(--pico-primary); background: var(--hlh-control-active-bg); color: var(--hlh-control-active-fg); }
  .table-scroll { overflow-x: auto; margin-bottom: 1.4rem; }
  table { font-size: .8rem; min-width: 650px; }
  td { vertical-align: top; overflow-wrap: anywhere; }
  td button, td select { font-size: .75rem; margin: 0 0 .5rem; }
  code { overflow-wrap: anywhere; }
  [role="alert"] { border-left: 3px solid var(--pico-primary); padding: .7rem; }
  @media (max-width: 760px) {
    .controls label, .controls input { min-width: 0; max-width: none; width: 100%; }
  }
</style>
