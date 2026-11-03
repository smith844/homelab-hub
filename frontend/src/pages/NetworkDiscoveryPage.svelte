<script>
  import { onDestroy, onMount } from 'svelte';
  import { get, post } from '../lib/api.js';
  import { adminHeaders, getAdminToken, setAdminToken } from '../lib/admin.js';
  import { addToast } from '../lib/stores.js';
  import {
    DEVICE_TYPE_FILTERS,
    HOST_MATCH_FILTERS,
    SERVICE_MATCH_FILTERS,
    SOURCE_FILTERS,
    UNIFI_STATE_FILTERS,
    candidateGroups,
    deviceIdentityCount,
    filterCandidates,
    filterHostRows,
    filterServiceRows,
    filterUnifiOnlyRows,
    networkLabel,
    networksFromResult,
    primaryIdentity,
    scanIsTerminal,
    serviceIdentityCount,
    summarizeNetworkComparison,
  } from '../lib/networkDiscovery.js';

  let config = null, loading = true, error = '';
  let approvedTarget = '', customTarget = '', scanType = 'discover', ports = '';
  let scan = null, scanning = false, reconciling = false, pollTimer = null, pollCount = 0;
  let comparison = null, comparisonError = '';
  let hostFilter = 'all', serviceFilter = 'all', query = '';
  let sourceFilter = 'all', stateFilter = 'all', networkFilter = '', typeFilter = 'all';
  let unifiStatus = null, unifiError = '', unifiLoading = false;
  let appQueries = {};
  let tokenSaved = false;
  let savedToken = getAdminToken(), token = savedToken;
  const value = v => v === null || v === undefined || v === '' ? '(not recorded)' : String(v);
  const matchLabels = {
    matched: 'Matched', plausible: 'Plausible / review', shared: 'Shared endpoint',
    ambiguous: 'Ambiguous', unmatched: 'Unmatched', unverified: 'Unverified',
  };

  $: activeTarget = customTarget.trim() || approvedTarget;
  $: summary = summarizeNetworkComparison(comparison);
  $: hostRows = filterHostRows(comparison?.hosts || [], hostFilter, query, {
    source: sourceFilter, network: networkFilter, state: stateFilter, type: typeFilter,
  });
  $: serviceRows = filterServiceRows(comparison?.services || [], serviceFilter, query);
  $: uniFiOnlyRows = (sourceFilter === 'both' || sourceFilter === 'nmap') ? [] :
    filterUnifiOnlyRows(comparison?.unifi_only || [], query, stateFilter,
      networkFilter, typeFilter)
      .filter(row => hostFilter === 'all' || row.classification === hostFilter);
  $: networks = networksFromResult(comparison);
  $: unifi = unifiStatus || comparison?.unifi || {};
  $: canStart = Boolean(activeTarget && config?.configured && savedToken && !scanning);


  onMount(async () => {
    try {
      config = await get('/network-discovery/config');
      approvedTarget = config.approved_ranges?.[0] || '';
      ports = config.default_ports || '';
      try {
        const status = await get('/network-discovery/unifi/status');
        unifiStatus = status.unifi;
      } catch (e) {
        unifiError = e.message;
      }
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
      if (scanIsTerminal(scan.status)) { await reconcile(); }
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
      if (scanIsTerminal(scan.status)) { stopPolling(); await reconcile(); }
    } catch (e) {
      stopPolling(); error = e.message;
    }
  }

  async function reconcile() {
    if (!scan) return;
    comparisonError = ''; reconciling = true;
    try {
      comparison = await post('/network-discovery/reconcile', { scan },
        { headers: adminHeaders() });
      if (comparison.unifi) unifiStatus = comparison.unifi;
      hostFilter = 'all'; serviceFilter = 'all'; sourceFilter = 'all';
      stateFilter = 'all'; networkFilter = ''; typeFilter = 'all'; query = '';
      appQueries = {};
    } catch (e) {
      comparison = null; comparisonError = e.message;
    } finally { reconciling = false; }
  }

  async function refreshUnifi() {
    if (!savedToken) { unifiError = 'Save the admin token before refreshing UniFi.'; return; }
    unifiLoading = true; unifiError = '';
    try {
      const result = await post('/network-discovery/unifi/refresh', {},
        { headers: adminHeaders() });
      unifiStatus = result.unifi;
      if (scanIsTerminal(scan?.status)) await reconcile();
    } catch (e) {
      unifiError = e.message;
      try {
        const status = await get('/network-discovery/unifi/status');
        unifiStatus = status.unifi;
      } catch (statusError) { /* keep the primary refresh error */ }
    } finally { unifiLoading = false; }
  }

  function candidateHref(candidate) {
    return `#/inventory/${candidate.type}/${candidate.id}`;
  }

  function saveToken() {
    setAdminToken(token.trim()); savedToken = token.trim(); tokenSaved = Boolean(savedToken);
    if (savedToken) addToast('Admin token saved for this browser session', 'success');
  }

  function clearScan() {
    stopPolling(); scan = null; comparison = null; comparisonError = ''; error = '';
    hostFilter = 'all'; serviceFilter = 'all'; sourceFilter = 'all';
    stateFilter = 'all'; networkFilter = ''; typeFilter = 'all'; query = '';
    appQueries = {}; reconciling = false;
  }
</script>

<section class="network-discovery">
  <h1>Network discovery</h1>
  <p>A separate, restricted Nmap scanner discovers reachable IPv4 devices and basic TCP services. Matching below searches the entire inventory, while Docker reconciliation remains host-scoped. Everything here is read-only: no inventory record or map layout is changed.</p>

  {#if error}<p role="alert">{error}</p>{/if}
  {#if loading}<p aria-busy="true">Loading discovery configuration…</p>{/if}
  {#if config?.error}<p role="alert">{config.error}</p>{/if}
  {#if config && !config.configured}
    <article class="notice">
      <h2>Scanner not configured</h2>
      <p>The web app needs <code>HLH_SCANNER_URL</code> and <code>HLH_SCANNER_TOKEN</code>. The scanner runs separately with its own token and approved ranges; no nmap or elevated networking is required in this web container.</p>
    </article>
  {/if}

  <article class="unifi-status">
    <h2>UniFi integration</h2>
    {#if unifi.configured}
      <p>Read-only UniFi Network Integration evidence is cached separately from HomeLab-Hub inventory and Nmap results. Refreshing this cache does not start an Nmap scan.</p>
      <p>{unifi.has_data ? `Last successful refresh: ${value(unifi.last_success)}` : 'No successful UniFi refresh has completed.'}{#if unifi.stale} · <strong>Stale</strong>{/if}{#if unifi.version} · Network {unifi.version}{/if}</p>
      <div class="summary unifi-counts">
        <span class="chip">{value(unifi.infrastructure_devices)} infrastructure devices</span>
        <span class="chip">{value(unifi.clients)} clients</span>
        <span class="chip">{value(unifi.current_clients)} current</span>
        <span class="chip">{value(unifi.historical_clients)} offline / historical</span>
      </div>
    {:else}
      <p>UniFi is not configured. Nmap discovery and matching continue to work normally. Configure <code>HLH_UNIFI_URL</code>, <code>HLH_UNIFI_API_KEY</code> and optionally <code>HLH_UNIFI_SITE</code>/<code>HLH_UNIFI_CA_FILE</code> to add read-only evidence.</p>
    {/if}
    {#if unifi.error}<p role="alert">{unifi.error}</p>{/if}
    {#if unifiError}<p role="alert">{unifiError}</p>{/if}
    <div class="controls">
      <button class="secondary outline" on:click={refreshUnifi} disabled={!savedToken || unifiLoading || !unifi.configured}>{unifiLoading ? 'Refreshing UniFi...' : 'Refresh UniFi observations'}</button>
      {#if !savedToken}<small>Save the admin token below to refresh.</small>{/if}
    </div>
  </article>

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
      <p>{value(scan.hosts_up)} hosts up · {value(scan.hosts?.length)} reported hosts · {value(scan.results?.length)} open services · {value(scan.hosts_down)} hosts down</p>
      {#if scan.status === 'partial'}<p role="alert">Partial scan. Results are retained for review, but completion, coverage and device absence cannot be asserted.</p>{/if}
      {#if scan.status === 'failed'}<p role="alert">The scan failed. No device or service is confirmed absent.</p>{/if}
      {#if scan.error}<p role="alert">{scan.error}</p>{/if}
      {#if scan.warnings?.length}
        <details><summary>{scan.warnings.length} scan warning{scan.warnings.length === 1 ? '' : 's'}</summary>
          <ul>{#each scan.warnings as warning}<li>{warning}</li>{/each}</ul>
        </details>
      {/if}
    </article>

    {#if reconciling}<p aria-busy="true">Matching scan observations against the full inventory…</p>{/if}
    {#if comparisonError}<p role="alert">{comparisonError}</p>{/if}

    {#if comparison}
      <article class="match-summary">
        <h2>Network-wide inventory matching</h2>
        <p>{comparison.reason}</p>
        {#if comparison.scan.uncertain}<p role="alert">This comparison is unverified because the scan is partial, failed or incomplete. No absence is inferred.</p>{/if}
        <div class="summary-groups">
          <section aria-label="Host matching summary">
            <h3>Hosts ({summary.hosts_discovered})</h3>
            <div class="summary" role="region" aria-label="Host match summary">
              <button type="button" class="summary-item" class:active={hostFilter === 'matched'} on:click={() => hostFilter = 'matched'}><strong>{summary.hosts_matched}</strong> Matched</button>
              <button type="button" class="summary-item" class:active={hostFilter === 'plausible'} on:click={() => hostFilter = 'plausible'}><strong>{summary.hosts_plausible}</strong> Plausible</button>
              <button type="button" class="summary-item" class:active={hostFilter === 'shared'} on:click={() => hostFilter = 'shared'}><strong>{summary.hosts_shared}</strong> Shared</button>
              <button type="button" class="summary-item" class:active={hostFilter === 'ambiguous'} on:click={() => hostFilter = 'ambiguous'}><strong>{summary.hosts_ambiguous}</strong> Ambiguous</button>
              <button type="button" class="summary-item" class:active={hostFilter === 'unmatched'} on:click={() => hostFilter = 'unmatched'}><strong>{summary.hosts_unmatched}</strong> Unmatched</button>
              <button type="button" class="summary-item" class:active={hostFilter === 'unverified'} on:click={() => hostFilter = 'unverified'}><strong>{summary.hosts_unverified}</strong> Unverified</button>
            </div>
          </section>
          <section aria-label="Service matching summary">
            <h3>Services ({summary.services_discovered})</h3>
            <div class="summary" role="region" aria-label="Service match summary">
              <button type="button" class="summary-item" class:active={serviceFilter === 'matched'} on:click={() => serviceFilter = 'matched'}><strong>{summary.services_matched}</strong> Matched</button>
              <button type="button" class="summary-item" class:active={serviceFilter === 'plausible'} on:click={() => serviceFilter = 'plausible'}><strong>{summary.services_plausible}</strong> Plausible</button>
              <button type="button" class="summary-item" class:active={serviceFilter === 'ambiguous'} on:click={() => serviceFilter = 'ambiguous'}><strong>{summary.services_ambiguous}</strong> Ambiguous</button>
              <button type="button" class="summary-item" class:active={serviceFilter === 'unmatched'} on:click={() => serviceFilter = 'unmatched'}><strong>{summary.services_unmatched}</strong> Unmatched</button>
              <button type="button" class="summary-item" class:active={serviceFilter === 'unverified'} on:click={() => serviceFilter = 'unverified'}><strong>{summary.services_unverified}</strong> Unverified</button>
            </div>
          </section>
        </div>
        <div class="summary unifi-counts" aria-label="UniFi matching summary">
          <span class="chip"><strong>{value(summary.nmap_hosts_with_unifi)}</strong> Nmap hosts with UniFi evidence</span>
          <span class="chip"><strong>{value(summary.unifi_only)}</strong> UniFi-only devices</span>
          <span class="chip"><strong>{value(summary.unifi_source_conflicts)}</strong> source conflicts</span>
          {#if unifi.configured}<span class="chip">{value(unifi.current_clients)} current UniFi clients</span>{/if}
        </div>
        <div class="controls filters">
          <label>Host match<select bind:value={hostFilter} aria-label="Host match filter">
            {#each HOST_MATCH_FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
          </select></label>
          <label>Service match<select bind:value={serviceFilter} aria-label="Service match filter">
            {#each SERVICE_MATCH_FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
          </select></label>
          <label>Source<select bind:value={sourceFilter} aria-label="Observation source filter">
            {#each SOURCE_FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
          </select></label>
          <label>UniFi state<select bind:value={stateFilter} aria-label="UniFi state filter">
            {#each UNIFI_STATE_FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
          </select></label>
          <label>Network<select bind:value={networkFilter} aria-label="Network filter">
            <option value="">All networks</option>
            {#each networks as item}<option value={item}>{item}</option>{/each}
          </select></label>
          <label>Device type<select bind:value={typeFilter} aria-label="Device type filter">
            {#each DEVICE_TYPE_FILTERS as item}<option value={item.value}>{item.label}</option>{/each}
          </select></label>
          <label>Search<input bind:value={query} aria-label="Search network matching" placeholder="IP, hostname, inventory name or classification" /></label>
          <span>{hostRows.length} of {comparison.hosts.length} hosts · {serviceRows.length} of {comparison.services.length} services · {uniFiOnlyRows.length} UniFi-only</span>
        </div>
      </article>

      <h2>Host matching ({hostRows.length} shown / {comparison.hosts.length})</h2>
      <div class="table-scroll"><table class="matching-table"><thead><tr><th>Host</th><th>Identity evidence</th><th>Match</th><th>Proposed inventory identity</th></tr></thead><tbody>
        {#each hostRows as row}
          {@const groups = candidateGroups(row)}
          {@const primary = primaryIdentity(row)}
          {@const devices = deviceIdentityCount(row)}
          {@const services = serviceIdentityCount(row)}
          <tr class:uncertain-row={row.classification === 'unverified'}>
            <td><code>{row.ip}</code>{#if row.hostname}<small class="hostname">{row.hostname}</small>{/if}{#if row.mac || row.vendor}<small>{value(row.mac)} · {value(row.vendor)}</small>{/if}{#if row.os}<small>OS: {row.os}</small>{/if}{#if row.network}<small>{networkLabel(row)}</small>{/if}{#if row.open_ports}<small>{row.open_ports} open port{row.open_ports === 1 ? '' : 's'}</small>{/if}</td>
            <td>{#if row.sources?.includes('unifi')}<span class="chip source-unifi">UniFi</span>{:else}<span class="chip">Nmap</span>{/if}{#each row.evidence as item}<span class="chip">{item}</span>{/each}{#if row.source_conflict}<span class="chip conflict">Source conflict</span>{/if}</td>
            <td><span class="match {row.classification}">{matchLabels[row.classification] || row.classification}</span><small>{row.reason}</small></td>
            <td>
              <details class="candidates">
                <summary>
                  <strong>{primary?.name || 'No reliable match'}</strong>
                  {#if devices > 1}<span>+{devices - 1} device{devices === 2 ? '' : 's'}</span>{/if}
                  {#if services}<span class="service-count">· {services} application{services === 1 ? '' : 's'} / service{services === 1 ? '' : 's'}</span>{/if}
                </summary>
                {#if row.unifi_matches?.length}
                  <h4>UniFi evidence</h4>
                  <ul class="unifi-list">
                    {#each row.unifi_matches as item}
                      <li><strong>{item.name || item.hostname || item.mac || item.ip}</strong><small>{item.kind} · {item.device_type || 'unknown type'} · {item.online === true ? 'online/current' : item.online === false ? 'offline/historical' : 'state unknown'}{item.last_seen ? ` · last seen ${item.last_seen}` : ''}</small>{#if item.mac}<small>{item.mac}{item.ip ? ` · ${item.ip}` : ''}</small>{/if}{#if item.ips?.length > 1}<small>Addresses: {item.ips.join(', ')}</small>{/if}{#if item.vendor || item.model}<small>{item.vendor || ''}{item.vendor && item.model ? ' · ' : ''}{item.model || ''}</small>{/if}{#if item.uplink_device_id}<small>Uplink device: {item.uplink_device_id}</small>{/if}{#if item.network}<small>{item.network.name || 'Network'}{item.network.vlan_id !== null && item.network.vlan_id !== undefined ? ` · VLAN ${item.network.vlan_id}` : ''}</small>{/if}</li>
                    {/each}
                  </ul>
                {/if}
                {#if groups.physical.length}
                  <h4>Physical / network devices</h4>
                  <ul>{#each groups.physical as candidate}<li><a href={candidateHref(candidate)}>{candidate.name}</a><small>{candidate.category}{candidate.parent ? ` · parent ${candidate.parent.name}` : ''}</small><small>Evidence: {candidate.evidence.join(', ') || 'none recorded'}</small></li>{/each}</ul>
                {/if}
                {#if groups.runtimes.length}
                  <h4>VMs / runtimes</h4>
                  <ul>{#each groups.runtimes as candidate}<li><a href={candidateHref(candidate)}>{candidate.name}</a><small>{candidate.category}{candidate.parent ? ` · parent ${candidate.parent.name}` : ''}</small><small>Evidence: {candidate.evidence.join(', ') || 'none recorded'}</small></li>{/each}</ul>
                {/if}
                {#if groups.services.length}
                  <h4>Applications / services ({groups.services.length})</h4>
                  {#if groups.services.length > 8}
                    <input aria-label={`Filter services for ${row.ip}`} bind:value={appQueries[row.ip]} placeholder="Filter applications/services by name or port" />
                  {/if}
                  <ul>{#each filterCandidates(groups.services, appQueries[row.ip]) as candidate}<li><a href={candidateHref(candidate)}>{candidate.name}</a><small>{candidate.category}{candidate.port ? ` · port ${candidate.port}` : ''}{candidate.parent ? ` · parent ${candidate.parent.name}` : ''}</small><small>Evidence: {candidate.evidence.join(', ')}</small></li>{/each}</ul>
                  {#if !filterCandidates(groups.services, appQueries[row.ip]).length}<p>No applications match this filter.</p>{/if}
                {/if}
                {#if !groups.physical.length && !groups.runtimes.length && !groups.services.length && !row.unifi_matches?.length}
                  <p>No candidate inventory identity was found for this address.</p>
                {/if}
              </details>
            </td>
          </tr>
        {/each}
        {#if !comparison.hosts.length}<tr><td colspan="4">No hosts were observed. This never proves that inventory devices are absent.</td></tr>
        {:else if !hostRows.length}<tr><td colspan="4">No hosts match this filter or search.</td></tr>{/if}
      </tbody></table></div>

      <h2>Service matching ({serviceRows.length} shown / {comparison.services.length})</h2>
      {#if comparison.services.length}
        <div class="table-scroll"><table class="matching-table"><thead><tr><th>Endpoint</th><th>Observed service</th><th>Match</th><th>Application endpoints</th></tr></thead><tbody>
          {#each serviceRows as row}
            <tr class:uncertain-row={row.classification === 'unverified'}>
              <td><code>{row.ip}:{row.port}</code>{#if row.hostname}<small class="hostname">{row.hostname}</small>{/if}</td>
              <td>{value(row.service_name)}<small>{value(row.service_version)}</small></td>
              <td><span class="match {row.classification}">{matchLabels[row.classification] || row.classification}</span><small>{row.reason}</small></td>
              <td>{#if row.candidates.length}<details class="candidates"><summary><strong>{primaryIdentity(row)?.name}</strong>{#if row.candidates.length > 1}<span> +{row.candidates.length - 1} more</span>{/if}</summary><ul>{#each row.candidates as candidate}<li><a href={candidateHref(candidate)}>{candidate.name}</a><small>{candidate.category}{candidate.parent ? ` · parent ${candidate.parent.name}` : ''}</small><small>Evidence: {candidate.evidence.join(', ')}</small></li>{/each}</ul></details>{:else}<span class="muted">No application endpoint recorded</span>{/if}</td>
            </tr>
          {/each}
          {#if !serviceRows.length}<tr><td colspan="4">No services match this filter or search.</td></tr>{/if}
        </tbody></table></div>
      {:else}
        <p>No TCP services were observed. Run a “Hosts and TCP services” scan to compare application endpoints.</p>
      {/if}

      {#if comparison.unifi_only.length}
        <h2>UniFi-only known devices ({uniFiOnlyRows.length} shown / {comparison.unifi_only.length})</h2>
        <p class="hint">These devices are known to UniFi but were not observed in this Nmap scan. They are not current Nmap discoveries and are never used to infer absence.</p>
        <div class="table-scroll"><table class="matching-table"><thead><tr><th>UniFi device</th><th>State</th><th>Inventory match</th><th>Evidence</th></tr></thead><tbody>
          {#each uniFiOnlyRows as row}
            {@const primary = primaryIdentity(row)}
            {@const groups = candidateGroups(row)}
            <tr class:uncertain-row={row.online === false}>
              <td><strong>{value(row.unifi_matches?.[0]?.name || row.hostname || row.ip)}</strong>{#if row.hostname}<small class="hostname">{row.hostname}</small>{/if}{#if row.unifi_matches?.[0]?.mac}<small>{row.unifi_matches[0].mac}{row.ip ? ` · ${row.ip}` : ''}</small>{/if}{#if row.device_type}<small>{row.device_type}</small>{/if}{#if row.network}<small>{networkLabel(row)}</small>{/if}</td>
              <td><span class="match {row.online === false ? 'ambiguous' : row.online === true ? 'matched' : 'unverified'}">{row.online === false ? 'Offline / historical' : row.online === true ? 'Online / current' : 'Unknown state'}</span>{#if row.last_seen}<small>Last seen: {row.last_seen}</small>{/if}</td>
              <td><span class="match {row.classification}">{matchLabels[row.classification] || row.classification}</span><small>{row.reason}</small></td>
              <td>
                <details class="candidates">
                  <summary><strong>{primary?.name || 'No reliable match'}</strong>{#if groups.physical.length + groups.runtimes.length > 1}<span> +{groups.physical.length + groups.runtimes.length - 1} device</span>{/if}{#if groups.services.length}<span class="service-count"> · {groups.services.length} service{groups.services.length === 1 ? '' : 's'}</span>{/if}</summary>
                  {#if groups.physical.length || groups.runtimes.length || groups.services.length}
                    <ul>{#each [...groups.physical, ...groups.runtimes, ...groups.services] as candidate}<li><a href={candidateHref(candidate)}>{candidate.name}</a><small>{candidate.category}{candidate.parent ? ` · parent ${candidate.parent.name}` : ''}</small><small>Evidence: {candidate.evidence.join(', ') || 'UniFi source evidence only'}</small></li>{/each}</ul>
                  {:else}<p>No inventory candidate matches this UniFi record.</p>{/if}
                  {#if row.unifi_evidence?.length}<small>{row.unifi_evidence.join(' · ')}</small>{/if}
                </details>
              </td>
            </tr>
          {/each}
          {#if !uniFiOnlyRows.length}<tr><td colspan="4">No UniFi-only devices match this filter or search.</td></tr>{/if}
        </tbody></table></div>
      {/if}
    {/if}
  {/if}

  <article>
    <h2>Administrative access</h2>
    <p>Starting a scan requires the configured server admin token. It is stored only in this browser session. Matching and comparison remain read-only and separate from inventory edits and map changes.</p>
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
  h3 { font-size: .9rem; margin-bottom: .45rem; }
  h4 { font-size: .8rem; margin: .7rem 0 .3rem; }
  p { font-size: .85rem; }
  small { display: block; color: var(--pico-muted-color); margin-top: .25rem; overflow-wrap: anywhere; }
  article { border: 1px solid var(--pico-muted-border-color); box-shadow: none; }
  .controls { display: flex; align-items: center; flex-wrap: wrap; gap: .8rem; }
  .controls button { width: auto; }
  .controls input { max-width: 24rem; }
  .controls label { min-width: 13rem; }
  .hint { color: var(--pico-muted-color); }
  .notice { border-left: 3px solid var(--pico-primary); }
  .unifi-status { margin-top: 1rem; border-left: 3px solid var(--pico-muted-border-color); }
  .unifi-counts { align-items: center; }
  .unifi-list { margin: .3rem 0; padding-left: 1rem; }
  .service-count { font-weight: 400; color: var(--pico-muted-color); }
  .source-unifi { border-color: var(--pico-primary); color: var(--pico-primary); }
  .conflict { border-color: #b04a3a; }
  .scan-status, .match-summary { margin-top: 1rem; }
  .candidates input { margin: .4rem 0; max-width: 22rem; }
  .summary-groups { display: grid; grid-template-columns: minmax(0, 3fr) minmax(0, 2fr); gap: 1rem; margin: .8rem 0; }
  .summary { display: flex; flex-wrap: wrap; gap: .4rem; }
  .summary-item { display: inline-flex; align-items: baseline; gap: .25rem; width: auto; margin: 0; padding: .4rem .6rem; font-size: .75rem; border: 1px solid var(--hlh-control-border); background: transparent; color: var(--hlh-control-fg); box-shadow: none; }
  .summary-item strong { display: inline; font-size: .95rem; }
  .summary-item.active { border-color: var(--pico-primary); background: var(--hlh-control-active-bg); color: var(--hlh-control-active-fg); }
  .filters { margin: .8rem 0; }
  .filters label { min-width: 11rem; }
  .filters span { font-size: .8rem; color: var(--pico-muted-color); }
  .table-scroll { overflow-x: auto; margin-bottom: 1.4rem; }
  .matching-table { font-size: .8rem; min-width: 860px; }
  td { vertical-align: top; overflow-wrap: anywhere; }
  td:last-child { min-width: 260px; }
  .hostname { font-size: .75rem; }
  .chip { display: inline-block; border: 1px solid var(--pico-muted-border-color); border-radius: 999px; padding: .05rem .4rem; margin: 0 .25rem .25rem 0; font-size: .7rem; }
  .match { display: inline-block; border-radius: 999px; padding: .1rem .45rem; font-size: .72rem; font-weight: 650; border: 1px solid var(--pico-muted-border-color); }
  .match.matched { border-color: #2e8b57; }
  .match.plausible { border-color: #b8860b; }
  .match.shared { border-color: var(--pico-primary); }
  .match.ambiguous { border-color: #b04a3a; }
  .match.unverified { border-style: dashed; }
  .muted { color: var(--pico-muted-color); }
  .candidates summary { cursor: pointer; }
  .candidates ul { margin: .4rem 0; padding-left: 1rem; }
  .candidates li { margin-bottom: .35rem; }
  .uncertain-row { background: var(--hlh-tint); }
  code { overflow-wrap: anywhere; white-space: nowrap; }
  [role="alert"] { border-left: 3px solid var(--pico-primary); padding: .7rem; }
  @media (max-width: 900px) {
    .summary-groups { grid-template-columns: 1fr; }
  }
  @media (max-width: 760px) {
    .controls label, .controls input { min-width: 0; max-width: none; width: 100%; }
    .matching-table, .matching-table thead, .matching-table tbody,
    .matching-table tr, .matching-table td, .matching-table th { display: block; }
    .matching-table thead { display: none; }
    .matching-table tr { border-bottom: 1px solid var(--pico-muted-border-color); padding: .55rem 0; }
    .matching-table td, .matching-table th { padding: .15rem 0; }
    .matching-table td:last-child { min-width: 0; }
  }
</style>
